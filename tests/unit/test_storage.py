from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest

from linguaspindle.config import Settings
from linguaspindle.errors import ErrorCode, LinguaError
from linguaspindle.storage import ArtifactStore


class ChunkOnlyStream(io.BytesIO):
    def __init__(self, payload: bytes):
        super().__init__(payload)
        self.read_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        assert size > 0, "stream storage must never request an unbounded read"
        self.read_sizes.append(size)
        return super().read(size)


def test_write_stream_is_chunked_and_computes_size_and_checksum(tmp_path: Path) -> None:
    store = ArtifactStore(Settings(data_dir=tmp_path / "data"))
    payload = b"a" * (2 * 1024 * 1024 + 17)
    source = ChunkOnlyStream(payload)

    stored = store.write_stream(
        project_id="project",
        artifact_id="artifact",
        filename="stream.bin",
        source=source,
        max_bytes=len(payload),
    )

    assert len(source.read_sizes) >= 3
    assert stored.size == len(payload)
    assert stored.checksum == hashlib.sha256(payload).hexdigest()
    with store.open_read(stored.storage_key) as opened:
        assert opened.read() == payload
    assert store.path(stored.storage_key).is_file()


def test_write_stream_limit_keeps_existing_payload_and_cleans_pending_file(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(Settings(data_dir=tmp_path / "data"))
    existing = store.write_bytes(
        project_id="project",
        artifact_id="artifact",
        filename="source.bin",
        payload=b"existing",
    )

    with pytest.raises(LinguaError) as caught:
        store.write_stream(
            project_id="project",
            artifact_id="artifact",
            filename="source.bin",
            source=ChunkOnlyStream(b"replacement is too large"),
            max_bytes=5,
        )

    assert caught.value.code == ErrorCode.UPLOAD_TOO_LARGE
    assert store.read_bytes(existing.storage_key) == b"existing"
    assert list(store.root.rglob(".pending-*")) == []


def test_write_file_and_copy_to_atomic_do_not_publish_partial_destinations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ArtifactStore(Settings(data_dir=tmp_path / "data"))
    source_path = tmp_path / "large-source.bin"
    source_path.write_bytes(b"copied payload")
    stored = store.write_file(
        project_id="project",
        artifact_id="artifact",
        filename="copy.bin",
        source_path=source_path,
        max_bytes=source_path.stat().st_size,
    )
    destination = tmp_path / "exports" / "copy.bin"

    assert store.copy_to_atomic(stored.storage_key, destination) == destination
    assert destination.read_bytes() == b"copied payload"

    destination.write_bytes(b"previous complete export")

    def fail_replace(_source: str, _destination: Path) -> None:
        raise OSError("synthetic replace failure")

    monkeypatch.setattr("linguaspindle.storage.os.replace", fail_replace)
    with pytest.raises(OSError, match="synthetic replace failure"):
        store.copy_to_atomic(stored.storage_key, destination)

    assert destination.read_bytes() == b"previous complete export"
    assert list(destination.parent.glob(".pending-*")) == []


def test_store_initialization_cleans_only_managed_pending_files(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    settings.ensure_directories()
    pending = settings.artifacts_dir / "projects" / "p" / "a" / ".pending-interrupted"
    retained = pending.with_name("published.bin")
    pending.parent.mkdir(parents=True)
    pending.write_bytes(b"partial")
    retained.write_bytes(b"complete")

    store = ArtifactStore(settings)

    assert not pending.exists()
    assert retained.read_bytes() == b"complete"
    assert store.cleanup_pending() == 0
