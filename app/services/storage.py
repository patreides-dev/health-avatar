from pathlib import Path
from typing import BinaryIO


class StorageError(ValueError):
    pass


class ArtifactStorage:
    backend_name = "abstract"

    def put(self, key: str, content: bytes) -> None:
        raise NotImplementedError

    def get(self, key: str) -> bytes:
        raise NotImplementedError

    def exists(self, key: str) -> bool:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError

    def open_stream(self, key: str) -> BinaryIO:
        raise NotImplementedError


class LocalArtifactStorage(ArtifactStorage):
    backend_name = "local_filesystem"

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        if (
            not key
            or Path(key).is_absolute()
            or ".." in Path(key).parts
            or "\\" in key
            or ":" in key
        ):
            raise StorageError("Unsafe storage key")
        resolved = (self.root / key).resolve()
        if self.root not in resolved.parents:
            raise StorageError("Storage key escapes configured root")
        return resolved

    def put(self, key: str, content: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise StorageError("Storage key already exists")
        path.write_bytes(content)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def open_stream(self, key: str) -> BinaryIO:
        return self._path(key).open("rb")
