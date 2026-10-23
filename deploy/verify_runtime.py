"""Exercise an isolated localhost production stack, including media persistence.

Creates a disposable account and recreates web/nginx; never use on a live instance.
Uses only the Python standard library and the Docker Compose CLI.
"""

import argparse
import base64
import http.client
import http.cookies
import json
import re
import socket
import ssl
import subprocess
import time
from urllib.parse import urlencode
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=".env.production")
    parser.add_argument("--project", default="taskflow-runtime-check")
    parser.add_argument("--http-port", type=int, default=8080)
    parser.add_argument("--https-port", type=int, default=8443)
    parser.add_argument("--ca-file", default=".runtime/tls/fullchain.pem")
    args = parser.parse_args()
    if not args.project.endswith("-check"):
        parser.error("Use a disposable Compose project ending in -check.")
    compose = [
        "docker",
        "compose",
        "--env-file",
        args.env_file,
        "-f",
        "compose.production.yaml",
        "-p",
        args.project,
    ]

    def command(*parts):
        result = subprocess.run(
            [*compose, *parts],
            capture_output=True,
            text=True,
            timeout=90,
            check=True,
        )
        return result.stdout

    def require(condition, message):
        if not condition:
            raise RuntimeError(message)

    context = ssl.create_default_context(cafile=args.ca_file)
    cookies = http.cookies.SimpleCookie()
    origin = f"https://localhost:{args.https_port}"

    class LocalHTTPSConnection(http.client.HTTPSConnection):
        def connect(self):
            # Avoid IPv6 fallback delays while still verifying the localhost SAN/SNI.
            self.sock = context.wrap_socket(
                socket.create_connection(("127.0.0.1", self.port), self.timeout),
                server_hostname="localhost",
            )

    def request(path, method="GET", body=None, headers=None, secure=True):
        headers = dict(headers or {})
        headers.setdefault(
            "Cookie", "; ".join(f"{key}={value.value}" for key, value in cookies.items())
        )
        if secure:
            connection = LocalHTTPSConnection(
                "localhost", args.https_port, context=context, timeout=10
            )
        else:
            connection = http.client.HTTPConnection("127.0.0.1", args.http_port, timeout=10)
            headers.setdefault("Host", f"localhost:{args.http_port}")
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            payload = response.read()
            for key, value in response.getheaders():
                if key.lower() == "set-cookie":
                    cookies.load(value)
            return (
                response.status,
                dict((key.lower(), value) for key, value in response.getheaders()),
                payload,
            )
        finally:
            connection.close()

    def post(path, data):
        data["csrfmiddlewaretoken"] = cookies["csrftoken"].value
        return request(
            path,
            "POST",
            urlencode(data),
            {
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": origin,
            },
        )

    command("restart", "nginx")  # Clear rate-limit zones for repeatable local checks.
    status = None
    for _attempt in range(30):
        try:
            status, headers, page = request("/accounts/login/")
            if status == 200:
                break
        except (OSError, http.client.HTTPException):
            pass
        time.sleep(0.5)
    require(status == 200, "Login page failed to start.")
    require("Secure" in headers.get("set-cookie", ""), "CSRF cookie must be secure.")
    require(headers.get("strict-transport-security") == "max-age=3600", "Missing HSTS.")
    require(headers.get("x-content-type-options") == "nosniff", "Missing nosniff.")
    require(headers.get("x-frame-options") == "DENY", "Missing frame protection.")
    status, headers, _ = request(
        "/accounts/login/?next=%2Fworkspaces%2F",
        secure=False,
        headers={"X-Forwarded-Proto": "https"},
    )
    require(
        status == 308 and headers["location"] == origin + "/accounts/login/?next=%2Fworkspaces%2F",
        "Unsafe HTTP redirect.",
    )
    require(request("/", headers={"Host": "evil.example"})[0] == 400, "Unknown Host was accepted.")
    require(
        request("/", secure=False, headers={"Host": "evil.example"})[0] == 400,
        "HTTP Host was reflected.",
    )
    require(
        request(
            "/accounts/login/",
            headers={
                "X-Forwarded-Proto": "http",
                "X-Forwarded-Host": "evil.example",
                "Forwarded": "host=evil.example;proto=http",
                "SCRIPT_NAME": "/evil",
            },
        )[0]
        == 200,
        "Client headers crossed the proxy trust boundary.",
    )
    static_paths = re.findall(rb'(?:href|src)="(/static/[^"?]+)', page)
    require(bool(static_paths), "No static assets found.")
    for path in static_paths:
        path = path.decode()
        status, headers, _ = request(path)
        require(status == 200, f"Missing collected asset: {path}")
        require(bool(re.search(r"\.[0-9a-f]{12}\.", path)), "Static URL is not manifest hashed.")
        require(
            "immutable" in headers.get("cache-control", ""), "Missing immutable static caching."
        )
    print("PASS: TLS, proxy header/Host boundary, security headers and manifest static assets")

    email = f"runtime-{uuid4().hex}@example.com"
    password = f"Runtime!{uuid4().hex}"
    request("/accounts/register/")
    require(
        post(
            "/accounts/register/",
            {
                "email": email,
                "full_name": "کاربر آزمایشی",
                "password1": password,
                "password2": password,
            },
        )[0]
        == 302,
        "Registration failed.",
    )
    require(
        post("/accounts/login/", {"username": email, "password": password})[0] == 302,
        "Login failed.",
    )
    require(
        cookies["sessionid"]["secure"] and cookies["sessionid"]["httponly"],
        "Unsafe session cookie.",
    )
    # A genuine 1x1 PNG followed by an unwanted payload; the stored image must omit it.
    image = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
    )
    boundary = uuid4().hex
    body = b""
    for key, value in {
        "csrfmiddlewaretoken": cookies["csrftoken"].value,
        "full_name": "Runtime",
        "bio": "",
    }.items():
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
    body += f'--{boundary}\r\nContent-Disposition: form-data; name="avatar"; filename="untrusted.png"\r\nContent-Type: image/png\r\n\r\n'.encode()
    body += image + b"<script>discard</script>\r\n" + f"--{boundary}--\r\n".encode()
    require(
        request(
            "/accounts/profile/",
            "POST",
            body,
            {
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Origin": origin,
            },
        )[0]
        == 302,
        "Avatar upload failed.",
    )
    _, _, page = request("/accounts/profile/")
    match = re.search(rb"/media/avatars/[a-f0-9]{32}\.png", page)
    require(match is not None, "Normalized avatar URL missing.")
    avatar_path = match.group().decode()
    status, headers, avatar = request(avatar_path)
    require(status == 200 and headers.get("content-type") == "image/png", "Media delivery failed.")
    require(
        b"<script>" not in avatar and headers.get("x-content-type-options") == "nosniff",
        "Unsafe media response.",
    )
    require(request("/media/avatars/untrusted.html")[0] == 404, "Active media content was served.")
    require(request("/media/")[0] == 404, "Media directory listing enabled.")
    require(
        request(
            "/accounts/profile/",
            "POST",
            "full_name=forged",
            {
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://evil.example",
            },
        )[0]
        == 403,
        "Cross-origin write accepted.",
    )
    command("up", "-d", "--force-recreate", "web", "nginx")
    for _attempt in range(30):
        try:
            if request(avatar_path)[0] == 200:
                break
        except (OSError, http.client.HTTPException):
            pass
        time.sleep(0.5)
    require(request(avatar_path)[2] == avatar, "Media did not survive container recreation.")
    require(request("/accounts/profile/")[0] == 200, "Database/session did not survive recreation.")
    print("PASS: registration/login, CSRF, canonical avatar storage and persistent media/session")

    for path, count in [
        ("/accounts/login/", 9),
        ("/admin/login/", 9),
        ("/accounts/register/", 6),
        ("/accounts/password/reset/", 6),
        ("/workspaces/example/members/invite/", 6),
        ("/workspaces/example/invitations/1/resend/", 6),
        ("/workspaces/invitations/invalid/", 15),
        ("/accounts/password/reset/invalid/invalid/", 15),
    ]:
        responses = [
            request(path, "POST", "", {"X-Forwarded-For": f"192.0.2.{index}"})
            for index in range(count)
        ]
        limited = [response for response in responses if response[0] == 429]
        require(bool(limited), f"Rate limit missing: {path}")
        require(limited[0][1].get("retry-after") == "60", "Missing Retry-After.")
        require("لطفاً".encode() in limited[0][2], "Missing safe Persian 429 page.")
    require(request("/")[0] == 200, "Sensitive limits affected normal browsing.")
    config = json.loads(command("config", "--format", "json"))
    require(
        not config["services"]["web"].get("ports") and not config["services"]["db"].get("ports"),
        "Internal services expose host ports.",
    )
    command(
        "exec",
        "-T",
        "web",
        "python",
        "manage.py",
        "shell",
        "-c",
        "import os; from pathlib import Path; from django.db import connection; "
        "assert os.geteuid() != 0; "
        "assert not Path('/app/.runtime').exists(); "
        "assert not Path('/app/.env.production').exists(); "
        "assert not Path('/run/secrets/db_admin_password').exists(); "
        "c=connection.cursor(); c.execute('SELECT current_user, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls FROM pg_roles WHERE rolname=current_user'); "
        "row=c.fetchone(); assert row == ('taskflow_app', False, False, False, False, False), row; "
        "c.execute('CREATE TABLE runtime_permission_probe (id integer)'); "
        "c.execute('ALTER TABLE runtime_permission_probe ADD COLUMN title text'); "
        "c.execute('DROP TABLE runtime_permission_probe')",
    )
    print(
        "PASS: sensitive endpoint rate limits, spoof resistance, private ports and migration role privileges"
    )


if __name__ == "__main__":
    main()
