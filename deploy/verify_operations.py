"""Destructive outage/restore checks for two isolated localhost *-check projects.

Source must already pass verify_runtime.py; target must have fresh volumes.
Leaves both projects' volumes intact. Never use against live data.
"""

import argparse
import hashlib
import http.client
import json
import socket
import ssl
import time
from pathlib import Path
from uuid import uuid4

from backup import Operations


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="taskflow-ops-check")
    parser.add_argument("--target", default="taskflow-restore-check")
    parser.add_argument("--env-file", default=".env.production")
    parser.add_argument("--https-port", type=int, default=8443)
    parser.add_argument("--ca-file", default=".runtime/tls/fullchain.pem")
    args = parser.parse_args()
    if args.source == args.target or not all(
        name.endswith("-check") for name in (args.source, args.target)
    ):
        parser.error("Use distinct disposable source/target projects ending in -check.")
    source = Operations(project=args.source, env_file=args.env_file)
    target = Operations(project=args.target, env_file=args.env_file)
    context = ssl.create_default_context(cafile=args.ca_file)

    def request(path, headers=None):
        connection = http.client.HTTPConnection("localhost", args.https_port, timeout=7)
        connection.sock = context.wrap_socket(
            socket.create_connection(("127.0.0.1", args.https_port), 7), server_hostname="localhost"
        )
        try:
            connection.request("GET", path, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def wait_ready():
        for _attempt in range(40):
            try:
                if request("/health/ready/")[0] == 200:
                    return
            except (OSError, http.client.HTTPException):
                pass
            time.sleep(0.5)
        raise RuntimeError("Readiness did not recover.")

    def shell(operations, code):
        return operations.run(
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "web",
            "python",
            "manage.py",
            "shell",
            "-v",
            "0",
            "-c",
            code,
        ).strip()

    def snapshot(operations):
        database = operations.run(
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "web",
            "python",
            "manage.py",
            "dumpdata",
            "--all",
        )
        media = operations.run(
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "web",
            "python",
            "-c",
            "import hashlib,json; from pathlib import Path; root=Path('/app/media'); "
            "files={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob('*')) if p.is_file()}; "
            "assert files; print(hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest())",
        )
        return hashlib.sha256(database).hexdigest(), media.strip()

    wait_ready()
    require(request("/health/live/") == (200, b'{"status": "ok"}'), "Liveness response changed.")
    shell(
        source,
        "from apps.accounts.models import User; from apps.workspaces.models import Workspace; from apps.workspaces.services import create_workspace; "
        "from apps.projects.models import Project; from apps.boards.services import create_task; "
        "u=User.objects.first();\nif not Workspace.objects.filter(slug='ops-restore-probe').exists():\n "
        "w=create_workspace(user=u,name='Operations restore probe',slug='ops-restore-probe'); "
        "p=Project.objects.create(workspace=w,name='Restore probe'); "
        "create_task(column=p.board.columns.first(),actor=w.memberships.get(user=u),title='Restore sentinel',description='Operations verification',priority='medium',due_date=None,assignee=u)",
    )
    session = shell(
        source,
        "from django.contrib.sessions.models import Session; print(Session.objects.first().session_key)",
    ).decode()
    sentinel = "sensitive-" + uuid4().hex
    headers = {
        "Cookie": f"sessionid={session}; probe={sentinel}",
        "Authorization": sentinel,
        "X-Request-ID": sentinel,
    }
    request(f"/workspaces/invitations/{sentinel}/?password={sentinel}", headers)
    source.run("stop", "db")
    started = time.monotonic()
    require(request("/health/live/")[0] == 200, "Liveness depends on PostgreSQL.")
    require(
        request("/health/ready/") == (503, b'{"status": "unavailable"}'),
        "Readiness failed to report database outage safely.",
    )
    require(time.monotonic() - started < 7, "Readiness exceeded its bounded probe budget.")
    source.run("up", "-d", "db")
    wait_ready()
    try:
        source.run(
            "exec",
            "-T",
            "db",
            "psql",
            "-U",
            "postgres",
            "-d",
            "taskflow",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            "ALTER ROLE taskflow_app NOLOGIN; SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename='taskflow_app'",
        )
        require(
            request(f"/accounts/profile/?password={sentinel}", headers)[0] == 500,
            "Expected application database authentication failure was not exercised.",
        )
    finally:
        source.run(
            "exec",
            "-T",
            "db",
            "psql",
            "-U",
            "postgres",
            "-d",
            "taskflow",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            "ALTER ROLE taskflow_app LOGIN",
        )
    wait_ready()
    source.run("stop", "web")
    require(
        request(f"/accounts/password/reset/uid/{sentinel}/?secret={sentinel}", headers)[0]
        in {502, 504},
        "Proxy upstream failure was not exercised.",
    )
    logs = source.run("logs", "--no-color", "--no-log-prefix", "web", "nginx")
    require(
        sentinel.encode() not in logs and session.encode() not in logs,
        "Sensitive request material leaked to logs.",
    )
    events = [json.loads(line) for line in logs.splitlines() if line.startswith(b"{")]
    require(
        any(event.get("exception") for event in events),
        "Missing safe application exception diagnostics.",
    )
    require(
        any(
            event.get("event") == "proxy_error" and event.get("status") in {502, 504}
            for event in events
        ),
        "Missing proxy failure event.",
    )
    require(
        any(event.get("event") == "gunicorn_request" for event in events),
        "Missing safe Gunicorn request events.",
    )
    print(
        "PASS: database outage health checks and secret-free application/proxy/Gunicorn failure logs",
        flush=True,
    )
    source.run("stop", "nginx")
    original = snapshot(source)
    archive = source.backup(Path(".runtime/backups"))
    target.run("up", "-d", "db")
    # up -d does not wait for database bootstrap; the service dependency does.
    target.run("run", "--rm", "-T", "web", "python", "manage.py", "check")
    target.restore(archive)
    require(
        snapshot(target) == original, "Restored database rows or media bytes differ from source."
    )
    target.run("run", "--rm", "--no-deps", "-T", "web", "python", "manage.py", "migrate", "--check")
    target.run("up", "-d", "web", "nginx")
    wait_ready()
    print(
        "PASS: actual isolated PostgreSQL/media restoration; complete data and media digests match; restored app is ready",
        flush=True,
    )


if __name__ == "__main__":
    main()
