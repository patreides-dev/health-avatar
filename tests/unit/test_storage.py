import hashlib
from pathlib import Path

import pytest

from app.services.storage import LocalArtifactStorage, StorageError


def test_local_storage_round_trip_and_stream(tmp_path: Path) -> None:
    storage = LocalArtifactStorage(tmp_path / "root")
    storage.put("sha256/aa/synthetic", b"safe synthetic bytes")
    assert storage.exists("sha256/aa/synthetic")
    assert storage.get("sha256/aa/synthetic") == b"safe synthetic bytes"
    with storage.open_stream("sha256/aa/synthetic") as stream:
        assert hashlib.sha256(stream.read()).hexdigest()
    storage.delete("sha256/aa/synthetic")
    assert not storage.exists("sha256/aa/synthetic")


@pytest.mark.parametrize(
    "key", ["../escape", "safe/../../escape", "C:/absolute", "..\\windows-escape"]
)
def test_storage_rejects_path_traversal(tmp_path: Path, key: str) -> None:
    storage = LocalArtifactStorage(tmp_path / "root")
    with pytest.raises(StorageError):
        storage.put(key, b"x")


def test_storage_refuses_overwrite(tmp_path: Path) -> None:
    storage = LocalArtifactStorage(tmp_path / "root")
    storage.put("safe/key", b"one")
    with pytest.raises(StorageError, match="already exists"):
        storage.put("safe/key", b"two")
