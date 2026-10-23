"""Stream media archives inside the non-root application container."""

import sys
import tarfile
from pathlib import Path, PurePosixPath

ROOT = Path("/app/media")


def safe_member(member):
    path = PurePosixPath(member.name)
    if (
        path.is_absolute()
        or ".." in path.parts
        or "\\" in member.name
        or ":" in member.name
        or not path.parts
        or not (member.isdir() or member.isfile())
    ):
        raise ValueError("Unsafe media archive entry.")


def main():
    mode = sys.argv[1]
    if mode in {"check-empty", "restore"} and any(ROOT.iterdir()):
        raise ValueError("Media restore requires an empty volume.")
    if mode == "check-empty":
        return
    if mode == "backup":
        with tarfile.open(fileobj=sys.stdout.buffer, mode="w|gz", dereference=False) as archive:
            for path in sorted(ROOT.rglob("*")):
                if path.is_symlink() or not (path.is_dir() or path.is_file()):
                    raise ValueError("Media must contain only ordinary files and directories.")
                archive.add(path, arcname=path.relative_to(ROOT), recursive=False)
    elif mode == "restore":
        with tarfile.open(fileobj=sys.stdin.buffer, mode="r|gz") as archive:
            for member in archive:
                safe_member(member)
                target = ROOT / member.name
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True, mode=0o755)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
                    with archive.extractfile(member) as source, target.open("xb") as output:
                        while chunk := source.read(1024 * 1024):
                            output.write(chunk)
                    target.chmod(0o644)
    else:
        raise ValueError("Unknown media operation.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, EOFError, ValueError, tarfile.TarError):
        print("Media operation failed; keep the application stopped.", file=sys.stderr)
        sys.exit(1)
