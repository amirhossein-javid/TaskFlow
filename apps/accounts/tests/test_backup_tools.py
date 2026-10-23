import io
import json
import tarfile
from unittest.mock import Mock

import pytest

from deploy.backup import Operations, digest, verify_bundle


def bundle(tmp_path, name="avatars/image.png", kind=tarfile.REGTYPE):
    (tmp_path / "database.dump").write_bytes(b"test dump")
    with tarfile.open(tmp_path / "media.tar.gz", "w:gz") as archive:
        member = tarfile.TarInfo(name)
        member.type = kind
        member.linkname = "/etc/passwd" if kind != tarfile.REGTYPE else ""
        member.size = 0
        archive.addfile(member, io.BytesIO())
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "sha256": {
                    name: digest(tmp_path / name) for name in ("database.dump", "media.tar.gz")
                },
            }
        )
    )
    return tmp_path


def test_backup_integrity_rejects_modified_data(tmp_path):
    directory = bundle(tmp_path)
    assert verify_bundle(directory)["version"] == 1
    (directory / "database.dump").write_bytes(b"changed")
    with pytest.raises(ValueError, match="integrity"):
        verify_bundle(directory)


@pytest.mark.parametrize(
    "name,kind",
    [
        ("../escape", tarfile.REGTYPE),
        ("/absolute", tarfile.REGTYPE),
        ("C:/escape", tarfile.REGTYPE),
        ("avatars/link", tarfile.SYMTYPE),
        ("avatars/link", tarfile.LNKTYPE),
    ],
)
def test_restore_rejects_unsafe_media_before_contacting_docker(tmp_path, name, kind):
    directory = bundle(tmp_path, name, kind)
    operations = Operations(project="isolated-check", env_file=".env.production")
    operations.run = Mock()
    with pytest.raises(ValueError):
        operations.restore(directory)
    operations.run.assert_not_called()


def test_operations_require_stopped_writers_and_empty_database(tmp_path):
    operations = Operations(project="isolated-check", env_file=".env.production")
    operations.run = Mock(return_value=b"db\nweb\n")
    with pytest.raises(ValueError, match="stop"):
        operations.backup(tmp_path)
    directory = bundle(tmp_path)
    operations.run = Mock(side_effect=[b"db\n", b"1\n"])
    with pytest.raises(ValueError, match="empty database"):
        operations.restore(directory)
    assert operations.run.call_count == 2


def test_operation_failure_does_not_publish_partial_backup(tmp_path):
    operations = Operations(project="isolated-check", env_file=".env.production")
    operations.require_stopped = Mock()
    operations.run = Mock(side_effect=RuntimeError("failed"))
    with pytest.raises(RuntimeError):
        operations.backup(tmp_path)
    assert not list(tmp_path.glob("*.backup"))
    assert len(list(tmp_path.glob("*.partial"))) == 1
