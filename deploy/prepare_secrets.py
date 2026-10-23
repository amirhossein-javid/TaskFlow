"""Create local file secrets once; never overwrite credentials for existing volumes."""

import os
import secrets
from pathlib import Path


def main():
    directory = Path(".runtime/secrets")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    for name in ("django_secret_key", "db_admin_password", "db_app_password"):
        path = directory / name
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            print(f"Keeping existing {path}")
            continue
        with os.fdopen(descriptor, "w", newline="\n") as file:
            # Compose file secrets are bind mounts and ignore uid/gid/mode options.
            # Non-root containers need read access; the host directory stays 0700.
            if hasattr(os, "fchmod"):
                os.fchmod(file.fileno(), 0o644)
            file.write(secrets.token_urlsafe(64) + "\n")
        print(f"Created {path}")


if __name__ == "__main__":
    main()
