"""Side-effect-bounded input/output helpers used only during explicit calls."""

from __future__ import annotations

import io
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, TypeAlias

from ..errors import ErrorCode, LinguaError

SourceInput: TypeAlias = str | os.PathLike[str] | bytes | bytearray | BinaryIO
OutputTarget: TypeAlias = str | os.PathLike[str] | BinaryIO

_CHUNK_SIZE = 1024 * 1024


def source_output_alias(source: SourceInput, target: OutputTarget) -> bool:
    """Best-effort same-file detection across paths and open binary streams."""

    if source is target:
        return True
    source_path = _object_path(source)
    target_path = _object_path(target)
    if source_path is not None and target_path is not None:
        try:
            if source_path.resolve() == target_path.resolve():
                return True
        except OSError:
            pass
    source_inode = _object_inode(source, source_path)
    target_inode = _object_inode(target, target_path)
    return source_inode is not None and source_inode == target_inode


def _object_path(value: object) -> Path | None:
    candidate: object
    if isinstance(value, (str, os.PathLike)):
        candidate = value
    else:
        candidate = getattr(value, "name", None)
    return Path(candidate) if isinstance(candidate, (str, os.PathLike)) else None


def _object_inode(value: object, path: Path | None) -> tuple[int, int] | None:
    fileno = getattr(value, "fileno", None)
    if callable(fileno):
        try:
            status = os.fstat(fileno())
            return status.st_dev, status.st_ino
        except (OSError, TypeError, ValueError):
            pass
    if path is not None:
        try:
            status = path.stat()
            return status.st_dev, status.st_ino
        except OSError:
            pass
    return None


def source_filename(source: SourceInput, filename: str | None = None) -> str | None:
    if filename:
        return Path(filename).name
    if isinstance(source, (str, os.PathLike)):
        return Path(source).name
    name = getattr(source, "name", None)
    return Path(str(name)).name if name else None


def read_source_bytes(source: SourceInput, *, maximum_bytes: int) -> bytes:
    if isinstance(source, (bytes, bytearray)):
        payload = bytes(source)
        if len(payload) > maximum_bytes:
            raise LinguaError(
                ErrorCode.UPLOAD_TOO_LARGE,
                "Source exceeds the configured input limit",
                {"bytes": len(payload), "limit": maximum_bytes},
            )
        return payload

    if isinstance(source, (str, os.PathLike)):
        path = Path(source)
        try:
            size = path.stat().st_size
            if size > maximum_bytes:
                raise LinguaError(
                    ErrorCode.UPLOAD_TOO_LARGE,
                    "Source exceeds the configured input limit",
                    {"bytes": size, "limit": maximum_bytes},
                )
            with path.open("rb") as stream:
                return _bounded_read(stream, maximum_bytes)
        except LinguaError:
            raise
        except OSError as exc:
            raise LinguaError(
                ErrorCode.INVALID_FORMAT,
                "Source could not be read",
                {"reason": type(exc).__name__},
            ) from exc

    position: int | None = None
    try:
        if source.seekable():
            position = source.tell()
        return _bounded_read(source, maximum_bytes)
    except LinguaError:
        raise
    except (AttributeError, OSError, TypeError) as exc:
        raise LinguaError(
            ErrorCode.INVALID_FORMAT,
            "Source stream could not be read",
            {"reason": type(exc).__name__},
        ) from exc
    finally:
        if position is not None:
            try:
                source.seek(position)
            except (AttributeError, OSError):
                pass


def _bounded_read(stream: BinaryIO, maximum_bytes: int) -> bytes:
    buffer = io.BytesIO()
    total = 0
    while True:
        chunk = stream.read(min(_CHUNK_SIZE, maximum_bytes - total + 1))
        if not chunk:
            break
        if not isinstance(chunk, (bytes, bytearray)):
            raise LinguaError(ErrorCode.INVALID_FORMAT, "Source stream must be binary")
        total += len(chunk)
        if total > maximum_bytes:
            raise LinguaError(
                ErrorCode.UPLOAD_TOO_LARGE,
                "Source exceeds the configured input limit",
                {"bytes_at_least": total, "limit": maximum_bytes},
            )
        buffer.write(chunk)
    return buffer.getvalue()


def write_output(target: OutputTarget, payload: bytes, *, overwrite: bool = False) -> None:
    if not isinstance(target, (str, os.PathLike)):
        try:
            seekable = getattr(target, "seekable", None)
            if callable(seekable) and seekable():
                target.seek(0)
                target.truncate(0)
            written = 0
            view = memoryview(payload)
            while written < len(payload):
                count = target.write(view[written:])
                if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
                    raise OSError("Output stream returned a short or invalid write")
                if count > len(payload) - written:
                    raise OSError("Output stream reported writing beyond the supplied payload")
                written += count
            target.flush()
            return
        except (AttributeError, OSError, TypeError, ValueError) as exc:
            raise LinguaError(
                ErrorCode.STORAGE,
                "Output stream could not be written",
                {"reason": type(exc).__name__},
            ) from exc

    output = Path(target)
    if output.exists() and not overwrite:
        raise LinguaError(
            ErrorCode.INVALID_STATE,
            "Output already exists; enable overwrite explicitly",
            {"output": output.name},
        )
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, output)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    except LinguaError:
        raise
    except OSError as exc:
        raise LinguaError(
            ErrorCode.STORAGE,
            "Output could not be written atomically",
            {"reason": type(exc).__name__},
        ) from exc


@contextmanager
def materialized_path(payload: bytes, *, suffix: str) -> Iterator[Path]:
    """Expose in-memory input to a path-only parser, then remove it."""

    descriptor, name = tempfile.mkstemp(prefix="linguaspindle-core-", suffix=suffix)
    path = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
        yield path
    finally:
        path.unlink(missing_ok=True)


__all__ = [
    "OutputTarget",
    "SourceInput",
    "materialized_path",
    "read_source_bytes",
    "source_filename",
    "source_output_alias",
    "write_output",
]
