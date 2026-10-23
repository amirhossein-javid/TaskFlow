"""Back up/restore a stopped production stack; credentials never leave containers."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

try:
    from .media_archive import safe_member
except ImportError:  # Direct script execution.
    from media_archive import safe_member

REPOSITORY = Path(__file__).resolve().parents[1]
FILES = ("database.dump", "media.tar.gz")


def digest(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def verify_bundle(directory):
    manifest = json.loads((directory / "manifest.json").read_text())
    if (
        not isinstance(manifest, dict)
        or manifest.get("version") != 1
        or not isinstance(manifest.get("sha256"), dict)
        or set(manifest["sha256"]) != set(FILES)
    ):
        raise ValueError("Unsupported backup manifest.")
    for name in FILES:
        path = directory / name
        if path.is_symlink() or not path.is_file() or digest(path) != manifest["sha256"][name]:
            raise ValueError("Backup integrity verification failed.")
    # Validate all media paths/types before restoring any database content.
    names = set()
    with tarfile.open(directory / "media.tar.gz", mode="r:gz") as archive:
        for member in archive:
            safe_member(member)
            if member.name in names:
                raise ValueError("Duplicate media archive entry.")
            names.add(member.name)
            if member.isfile():
                with archive.extractfile(member) as file:
                    while file.read(1024 * 1024):
                        pass
    return manifest


class Operations:
    def __init__(self, *, project, env_file, timeout=300):
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", project):
            raise ValueError("Invalid Compose project name.")
        self.compose = [
            "docker",
            "compose",
            "--env-file",
            str(env_file),
            "-f",
            str(REPOSITORY / "compose.production.yaml"),
            "-p",
            project,
        ]
        self.timeout = timeout

    def run(self, *parts, input_file=None, output_file=None):
        result = subprocess.run(
            [*self.compose, *parts],
            stdin=input_file,
            stdout=output_file or subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=self.timeout,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(
                "Docker operation failed; keep services stopped and retain partial files."
            )
        return result.stdout or b""

    def require_stopped(self):
        running = self.run("ps", "--status", "running", "--services").decode().split()
        if "db" not in running or {"web", "nginx"}.intersection(running):
            raise ValueError("Run db and stop web/nginx before backup or restore.")

    def media(self, mode, **kwargs):
        return self.run(
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "web",
            "python",
            "deploy/media_archive.py",
            mode,
            **kwargs,
        )

    def backup(self, parent):
        self.require_stopped()
        parent = parent.resolve()
        if parent.is_relative_to(REPOSITORY) and not parent.is_relative_to(REPOSITORY / ".runtime"):
            raise ValueError("Repository backups must be kept under ignored .runtime/.")
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        name = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
        directory = parent / f"{name}.partial"
        directory.mkdir(mode=0o700)
        for filename in FILES:
            descriptor = os.open(directory / filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as output:
                if filename == "database.dump":
                    self.run(
                        "exec",
                        "-T",
                        "db",
                        "pg_dump",
                        "-U",
                        "taskflow_app",
                        "-d",
                        "taskflow",
                        "--format=custom",
                        "--no-owner",
                        "--no-acl",
                        output_file=output,
                    )
                else:
                    self.media("backup", output_file=output)
                output.flush()
                os.fsync(output.fileno())
        manifest = {
            "version": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "sha256": {name: digest(directory / name) for name in FILES},
            "images": self.run("images", "--format", "json").decode(),
        }
        with (directory / "manifest.json").open("x", encoding="utf-8") as file:
            json.dump(manifest, file, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        (directory / "manifest.json").chmod(0o600)
        verify_bundle(directory)
        target = directory.with_suffix(".backup")
        directory.rename(target)
        print(f"Backup complete: {target}")
        return target

    def restore(self, directory):
        verify_bundle(directory)
        self.require_stopped()
        objects = self.run(
            "exec",
            "-T",
            "db",
            "psql",
            "-U",
            "taskflow_app",
            "-d",
            "taskflow",
            "-At",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            "SELECT (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema') + (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema') + (SELECT count(*) FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema')",
        ).strip()
        if objects != b"0":
            raise ValueError(
                "Restore requires an empty database; no existing data will be overwritten."
            )
        self.media("check-empty")
        with (directory / "database.dump").open("rb") as source:
            self.run(
                "exec",
                "-T",
                "db",
                "pg_restore",
                "-U",
                "taskflow_app",
                "-d",
                "taskflow",
                "--clean",
                "--if-exists",
                "--single-transaction",
                "--exit-on-error",
                "--no-owner",
                "--no-acl",
                input_file=source,
            )
        with (directory / "media.tar.gz").open("rb") as source:
            self.media("restore", input_file=source)
        print(
            "Restore complete; verify migrations, health, data and media before starting traffic."
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["backup", "restore", "verify"])
    parser.add_argument("directory", type=Path)
    parser.add_argument("--project", required=True)
    parser.add_argument("--env-file", type=Path, default=REPOSITORY / ".env.production")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    try:
        if args.timeout <= 0:
            raise ValueError("Timeout must be positive.")
        if args.operation == "verify":
            verify_bundle(args.directory)
            print(
                "Backup checksums and media archive verified; this command does not test restoration."
            )
        else:
            operations = Operations(
                project=args.project, env_file=args.env_file, timeout=args.timeout
            )
            getattr(operations, args.operation)(args.directory)
    except (
        OSError,
        EOFError,
        ValueError,
        RuntimeError,
        tarfile.TarError,
        subprocess.TimeoutExpired,
    ):
        print(
            "Operation failed. Check prerequisites/integrity; keep services stopped. Partial files are not a verified backup.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
