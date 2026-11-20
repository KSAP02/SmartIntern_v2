"""File storage seam. LocalStorage now (Docker volume); an S3-compatible backend at deploy.

Callers use storage keys (e.g. "uploads/<sha256>.pdf"), never filesystem paths.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from backend.config import data_dir, get_settings


class StorageError(RuntimeError):
    """Storage is misconfigured or a file is missing."""


class LocalStorage:
    kind = "local"

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents:
            raise StorageError(f"Invalid storage key: {key}")
        return p

    def save(self, key: str, data: bytes) -> str:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(p)
        return key

    def read(self, key: str) -> bytes:
        p = self._path(key)
        if not p.is_file():
            raise StorageError(f"File not found in storage: {key}")
        return p.read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def check(self) -> str:
        probe = self.root / ".write-check"
        probe.write_text("ok")
        probe.unlink()
        return f"local disk at {self.root}"


@lru_cache
def get_storage() -> LocalStorage:
    backend = get_settings().storage_backend.strip().lower()
    if backend == "local":
        return LocalStorage(data_dir() / "files")
    raise StorageError(f"STORAGE_BACKEND '{backend}' is not available yet (S3 arrives at deploy, Phase 7).")
