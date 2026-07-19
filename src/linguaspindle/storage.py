"""File-backed immutable Artifact payload storage."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .errors import ErrorCode, LinguaError

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True, slots=True)
class StoredPayload:
    storage_key: str
    filename: str
    size: int
    checksum: str


def safe_filename(name: str) -> str:
    candidate = _SAFE_NAME.sub("_", Path(name).name).strip("._")
    return candidate[:180] or "artifact.bin"


class ArtifactStore:
    def __init__(self, settings: Settings):
        settings.ensure_directories()
        self.root = settings.artifacts_dir.resolve()

    def _resolve(self, storage_key: str) -> Path:
        if Path(storage_key).is_absolute():
            raise LinguaError(ErrorCode.STORAGE, "Artifact storage key must be relative")
        path = (self.root / storage_key).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise LinguaError(ErrorCode.STORAGE, "Artifact storage key escapes data root") from exc
        return path

    def write_bytes(
        self, *, project_id: str, artifact_id: str, filename: str, payload: bytes
    ) -> StoredPayload:
        clean_name = safe_filename(filename)
        storage_key = f"projects/{project_id}/{artifact_id}/{clean_name}"
        destination = self._resolve(storage_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(payload).hexdigest()
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=destination.parent, prefix=".pending-", delete=False
            ) as temporary:
                temporary_name = temporary.name
                temporary.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, destination)
        finally:
            if temporary_name and Path(temporary_name).exists():
                Path(temporary_name).unlink()
        return StoredPayload(storage_key, clean_name, len(payload), digest)

    def read_bytes(self, storage_key: str) -> bytes:
        path = self._resolve(storage_key)
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise LinguaError(ErrorCode.OUTPUT_MISSING, "Artifact payload is missing") from exc

    def path_for_adapter(self, storage_key: str) -> Path:
        """Resolve a private path only at the infrastructure boundary."""
        path = self._resolve(storage_key)
        if not path.is_file():
            raise LinguaError(ErrorCode.OUTPUT_MISSING, "Artifact payload is missing")
        return path

    def remove(self, storage_key: str) -> None:
        path = self._resolve(storage_key)
        if path.exists():
            path.unlink()
        parent = path.parent
        while parent != self.root and parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent

    def remove_project_payloads(self, project_id: str) -> None:
        project_root = self._resolve(f"projects/{project_id}")
        if not project_root.exists():
            return
        for path in sorted(project_root.rglob("*"), reverse=True):
            if path.is_file() or path.is_symlink():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        project_root.rmdir()
