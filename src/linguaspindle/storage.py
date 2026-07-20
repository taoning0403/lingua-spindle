"""File-backed immutable Artifact payload storage."""

from __future__ import annotations

import hashlib
import io
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from .config import Settings
from .errors import ErrorCode, LinguaError

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_COPY_CHUNK_BYTES = 1024 * 1024


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
        self.cleanup_pending()

    def cleanup_pending(self) -> int:
        """Remove only staging files owned by this store after an interrupted process."""

        removed = 0
        for pending in self.root.rglob(".pending-*"):
            if pending.is_file() or pending.is_symlink():
                pending.unlink(missing_ok=True)
                removed += 1
        return removed

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
        return self.write_stream(
            project_id=project_id,
            artifact_id=artifact_id,
            filename=filename,
            source=io.BytesIO(payload),
        )

    def write_stream(
        self,
        *,
        project_id: str,
        artifact_id: str,
        filename: str,
        source: BinaryIO,
        max_bytes: int | None = None,
    ) -> StoredPayload:
        """Publish a binary stream without loading it all into memory."""

        if max_bytes is not None and max_bytes < 0:
            raise ValueError("max_bytes cannot be negative")
        clean_name = safe_filename(filename)
        storage_key = f"projects/{project_id}/{artifact_id}/{clean_name}"
        destination = self._resolve(storage_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=destination.parent, prefix=".pending-", delete=False
            ) as temporary:
                temporary_name = temporary.name
                while True:
                    read_size = _COPY_CHUNK_BYTES
                    if max_bytes is not None:
                        read_size = min(read_size, max_bytes - size + 1)
                    chunk = source.read(read_size)
                    if not chunk:
                        break
                    if not isinstance(chunk, bytes):
                        raise TypeError("Artifact source must be a binary stream")
                    size += len(chunk)
                    if max_bytes is not None and size > max_bytes:
                        raise LinguaError(
                            ErrorCode.UPLOAD_TOO_LARGE,
                            "Artifact payload exceeds the configured upload limit",
                            {"limit": max_bytes, "observed": size},
                        )
                    digest.update(chunk)
                    temporary.write(chunk)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, destination)
        finally:
            if temporary_name and Path(temporary_name).exists():
                Path(temporary_name).unlink()
        return StoredPayload(storage_key, clean_name, size, digest.hexdigest())

    def write_file(
        self,
        *,
        project_id: str,
        artifact_id: str,
        filename: str,
        source_path: Path,
        max_bytes: int | None = None,
    ) -> StoredPayload:
        """Stream a file into the immutable Artifact store."""

        with source_path.open("rb") as source:
            return self.write_stream(
                project_id=project_id,
                artifact_id=artifact_id,
                filename=filename,
                source=source,
                max_bytes=max_bytes,
            )

    def read_bytes(self, storage_key: str) -> bytes:
        with self.open_read(storage_key) as source:
            return source.read()

    def path(self, storage_key: str) -> Path:
        """Resolve an existing payload path for service/infrastructure use only."""

        path = self._resolve(storage_key)
        if not path.is_file():
            raise LinguaError(ErrorCode.OUTPUT_MISSING, "Artifact payload is missing")
        return path

    def open_read(self, storage_key: str) -> BinaryIO:
        """Open a payload for bounded or streaming reads."""

        try:
            return self.path(storage_key).open("rb")
        except FileNotFoundError as exc:
            raise LinguaError(ErrorCode.OUTPUT_MISSING, "Artifact payload is missing") from exc

    def path_for_adapter(self, storage_key: str) -> Path:
        """Resolve a private path only at the infrastructure boundary."""
        return self.path(storage_key)

    def copy_to_atomic(self, storage_key: str, destination: Path) -> Path:
        """Copy a payload to a path, replacing the destination only after a durable write."""

        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_name: str | None = None
        try:
            with self.open_read(storage_key) as source:
                with tempfile.NamedTemporaryFile(
                    dir=destination.parent, prefix=".pending-", delete=False
                ) as temporary:
                    temporary_name = temporary.name
                    while chunk := source.read(_COPY_CHUNK_BYTES):
                        temporary.write(chunk)
                    temporary.flush()
                    os.fsync(temporary.fileno())
            os.replace(temporary_name, destination)
        finally:
            if temporary_name and Path(temporary_name).exists():
                Path(temporary_name).unlink()
        return destination

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
