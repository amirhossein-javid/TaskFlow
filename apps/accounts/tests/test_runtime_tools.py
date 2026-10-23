import os
import subprocess
import sys
from pathlib import Path


def test_secret_preparation_is_private_idempotent_and_uses_portable_line_endings(tmp_path):
    script = Path(__file__).resolve().parents[3] / "deploy" / "prepare_secrets.py"
    command = [sys.executable, str(script)]
    first = subprocess.run(command, cwd=tmp_path, capture_output=True, timeout=10, check=True)
    directory = tmp_path / ".runtime" / "secrets"
    files = sorted(directory.iterdir())
    original = {file.name: file.read_bytes() for file in files}
    assert set(original) == {"django_secret_key", "db_admin_password", "db_app_password"}
    assert len(set(original.values())) == 3
    assert all(len(value) >= 64 and b"\r" not in value for value in original.values())
    second = subprocess.run(command, cwd=tmp_path, capture_output=True, timeout=10, check=True)
    assert {file.name: file.read_bytes() for file in files} == original
    assert all(value.strip() not in first.stdout + second.stdout for value in original.values())
    if os.name == "posix":
        assert directory.stat().st_mode & 0o777 == 0o700
        assert all(file.stat().st_mode & 0o777 == 0o644 for file in files)
