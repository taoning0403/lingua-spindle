"""Shared application services used by Web, CLI, and HTTP interfaces."""

from __future__ import annotations

import hashlib
import io
import json
import mimetypes
import platform
import shutil
import socket
import stat
import subprocess
import tempfile
import unicodedata
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import IO, Any, BinaryIO

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import selectinload

from . import __version__
from .adapters import AdapterRegistry, MangaTranslationAdapter, MockMangaAdapter
from .config import Settings
from .core.manga import inspect_manga
from .database import Database
from .epub import inspect_epub, is_bcp47_language_tag
from .errors import ErrorCode, LinguaError
from .models import (
    Artifact,
    Job,
    Project,
    ProviderConfig,
    QaFinding,
    Source,
    StepLog,
    StepRun,
    TranslationProfile,
    TranslationSegment,
    new_id,
    utcnow,
)
from .orchestration.pipelines import PIPELINES, default_pipeline, get_pipeline
from .orchestration.state import (
    TERMINAL_JOB_STATUSES,
    JobStatus,
    StepStatus,
    ensure_job_transition,
    ensure_step_transition,
)
from .providers import MockProvider, ProviderRegistry, TranslationProvider
from .security import redact, redact_text
from .storage import ArtifactStore

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
_CONTENT_ARTIFACT_KINDS = {
    "epub_package_manifest",
    "epub_segments",
    "epub_translations",
    "manga_manifest",
    "manga_translation_result",
    "novel_export_json",
    "novel_export_txt",
    "novel_segments",
    "novel_text_extracted",
    "novel_translations",
}
_ARCHIVE_ARTIFACT_KINDS = {"manga_export_cbz", "novel_export_epub"}


def _loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() + ("Z" if value.tzinfo is None else "")


class ApplicationService:
    """The sole use-case boundary for every interface."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.database = Database(settings)
        self.store = ArtifactStore(settings)
        for pattern in ("epub-export-*", ".epub-export-*.tmp"):
            for temporary in settings.cache_dir.glob(pattern):
                if temporary.is_file() or temporary.is_symlink():
                    temporary.unlink(missing_ok=True)
        providers: list[TranslationProvider] = [MockProvider()]
        adapters: list[MangaTranslationAdapter] = [MockMangaAdapter()]
        try:
            from .providers.openai_compatible import (
                OpenAICompatibleProvider,
                OpenAIProviderConfig,
            )
        except ModuleNotFoundError as exc:
            if exc.name != "httpx":
                raise
        else:
            providers.append(
                OpenAICompatibleProvider(
                    OpenAIProviderConfig(
                        base_url=settings.openai_base_url,
                        model=settings.openai_model,
                        timeout_seconds=settings.openai_timeout_seconds,
                        api_key=settings.openai_api_key,
                    )
                )
            )
        try:
            from .adapters.manga_image_translator import (
                MangaImageTranslatorConfig,
                MangaImageTranslatorHttpAdapter,
            )
        except ModuleNotFoundError as exc:
            if exc.name != "httpx":
                raise
        else:
            adapters.append(
                MangaImageTranslatorHttpAdapter(
                    MangaImageTranslatorConfig(
                        base_url=settings.mit_base_url,
                        timeout_seconds=settings.mit_timeout_seconds,
                        request_config=json.loads(settings.mit_config_json),
                    )
                )
            )
        self.providers = ProviderRegistry(providers)
        self.adapters = AdapterRegistry(adapters)
        self._sync_provider_configs()

    def close(self) -> None:
        self.database.close()

    def redact_for_persistence(self, value: Any) -> Any:
        """Remove runtime Provider secrets and secret-shaped fields before serialization."""
        return redact(value, [self.settings.openai_api_key or ""])

    def _redact_text(self, value: str) -> str:
        return redact_text(value, [self.settings.openai_api_key or ""])

    @staticmethod
    def _provider_public_status(provider: TranslationProvider) -> dict[str, Any]:
        public_status = getattr(provider, "public_status", None)
        if callable(public_status):
            return dict(public_status())
        return {
            "id": provider.id,
            "display_name": getattr(provider, "display_name", provider.id),
            "configured": True,
        }

    def _redact_content_text(self, value: str) -> str:
        """Remove only the active runtime key without rewriting user-authored prose."""

        secret = self.settings.openai_api_key
        return value.replace(secret, "[REDACTED]") if secret else value

    def _redact_content_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._redact_content_text(value)
        if isinstance(value, dict):
            return {str(key): self._redact_content_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._redact_content_value(item) for item in value]
        return value

    def _reject_runtime_secret_fields(self, *values: str) -> None:
        secret = self.settings.openai_api_key
        if secret and any(secret in value for value in values):
            raise LinguaError(
                ErrorCode.CONFIGURATION,
                "Imported Project fields contain the runtime Provider secret; "
                "remove it before import",
            )

    def _sanitize_artifact_payload(self, payload: bytes, media_type: str, kind: str) -> bytes:
        base_type = media_type.partition(";")[0].strip().lower()
        is_json = base_type == "application/json" or base_type.endswith("+json")
        is_text = base_type.startswith("text/") or is_json
        content_payload = kind in _CONTENT_ARTIFACT_KINDS
        if is_text:
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError:
                text = ""
            if text:
                if is_json:
                    try:
                        structured = json.loads(text)
                    except json.JSONDecodeError:
                        pass
                    else:
                        sanitized = (
                            self._redact_content_value(structured)
                            if content_payload
                            else self.redact_for_persistence(structured)
                        )
                        return json.dumps(
                            sanitized,
                            ensure_ascii=False,
                            indent=2,
                        ).encode()
                sanitizer = self._redact_content_text if content_payload else self._redact_text
                return sanitizer(text).encode()
        secret = self.settings.openai_api_key
        if secret and secret.encode() in payload:
            raise LinguaError(
                ErrorCode.STORAGE,
                "Refusing to persist a binary Artifact containing the runtime Provider secret",
            )
        if secret and kind in _ARCHIVE_ARTIFACT_KINDS:
            try:
                with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
                    if self._archive_contains(archive, secret.encode()):
                        raise LinguaError(
                            ErrorCode.STORAGE,
                            "Refusing to persist an archive Artifact containing the runtime "
                            "Provider secret",
                        )
            except LinguaError:
                raise
            except zipfile.BadZipFile as exc:
                raise LinguaError(
                    ErrorCode.INVALID_FORMAT,
                    "Generated archive Artifact is not a valid ZIP file",
                ) from exc
        return payload

    def _sync_provider_configs(self) -> None:
        values = (
            {
                "id": "mock",
                "base_url": "",
                "model": "mock-v1",
                "timeout_seconds": 0.0,
                "concurrency_limit": 1,
                "max_retries": 0,
            },
            {
                "id": "openai-compatible",
                "base_url": self._redact_text(self.settings.openai_base_url),
                "model": self._redact_text(self.settings.openai_model),
                "timeout_seconds": self.settings.openai_timeout_seconds,
                "concurrency_limit": self.settings.openai_concurrency_limit,
                "max_retries": self.settings.openai_max_retries,
            },
        )
        with self.database.session() as session:
            for value in values:
                row = session.get(ProviderConfig, value["id"])
                if row is None:
                    session.add(ProviderConfig(**value))
                else:
                    for key, item in value.items():
                        setattr(row, key, item)

    @staticmethod
    def _validate_project_fields(
        name: str, kind: str, source_language: str, target_language: str
    ) -> tuple[str, str, str, str]:
        cleaned_name = name.strip()
        if not cleaned_name or len(cleaned_name) > 200:
            raise LinguaError(ErrorCode.CONFIGURATION, "Project name must be 1-200 characters")
        cleaned_kind = kind.lower().strip()
        if cleaned_kind not in {"novel", "manga"}:
            raise LinguaError(ErrorCode.CONFIGURATION, "Project kind must be novel or manga")
        source = source_language.strip()
        target = target_language.strip()
        if not source or not target:
            raise LinguaError(ErrorCode.CONFIGURATION, "Source and target languages are required")
        return cleaned_name, cleaned_kind, source, target

    @staticmethod
    def _source_kind(project_kind: str, filename: str) -> str:
        suffix = Path(filename).suffix.lower()
        if project_kind == "novel":
            if suffix == ".txt":
                return "txt"
            if suffix == ".epub":
                return "epub"
            raise LinguaError(ErrorCode.INVALID_FORMAT, "Novel sources must be TXT or EPUB")
        if suffix in {".cbz", ".zip"}:
            return "cbz"
        if suffix in _IMAGE_SUFFIXES:
            return "image"
        raise LinguaError(
            ErrorCode.INVALID_FORMAT,
            "Manga sources must be CBZ/ZIP or PNG/JPEG/WebP",
        )

    def create_project(
        self,
        *,
        name: str,
        kind: str,
        source_language: str,
        target_language: str,
        source_name: str,
        source_bytes: bytes,
        media_type: str | None = None,
    ) -> dict[str, Any]:
        return self.create_project_from_stream(
            name=name,
            kind=kind,
            source_language=source_language,
            target_language=target_language,
            source_name=source_name,
            source=io.BytesIO(source_bytes),
            media_type=media_type,
        )

    @staticmethod
    def _stream_contains(source: IO[bytes], needle: bytes) -> bool:
        if not needle:
            return False
        needles: tuple[bytes, ...]
        try:
            text_needle = needle.decode("utf-8")
        except UnicodeDecodeError:
            needles = (needle,)
        else:
            needles = tuple(
                dict.fromkeys(
                    (
                        needle,
                        text_needle.encode("utf-16-le"),
                        text_needle.encode("utf-16-be"),
                        text_needle.encode("utf-32-le"),
                        text_needle.encode("utf-32-be"),
                    )
                )
            )
        overlap = b""
        while chunk := source.read(1024 * 1024):
            candidate = overlap + chunk
            if any(encoded in candidate for encoded in needles):
                return True
            overlap_size = max(max(map(len, needles)) - 1, 0)
            overlap = candidate[-overlap_size:] if overlap_size else b""
        return False

    @classmethod
    def _path_contains(cls, path: Path, needle: bytes) -> bool:
        with path.open("rb") as handle:
            return cls._stream_contains(handle, needle)

    def _archive_contains(self, archive: zipfile.ZipFile, needle: bytes) -> bool:
        """Bounded scan of expanded ZIP members for one exact runtime secret."""

        members = archive.infolist()
        if len(members) > self.settings.max_archive_files:
            raise LinguaError(
                ErrorCode.ARCHIVE_LIMIT_EXCEEDED,
                "Archive contains too many members",
                {"member_count": len(members), "limit": self.settings.max_archive_files},
            )
        total = 0
        portable_names: set[str] = set()
        for member in members:
            safe_member = self.validate_archive_member(member.filename)
            portable_name = unicodedata.normalize("NFC", str(safe_member)).casefold()
            if portable_name in portable_names:
                raise LinguaError(
                    ErrorCode.ARCHIVE_UNSAFE,
                    "Archive contains duplicate or ambiguous paths",
                    {
                        "member": "[REDACTED]"
                        if needle and needle in member.filename.encode()
                        else member.filename
                    },
                )
            portable_names.add(portable_name)
            if member.flag_bits & 0x41:
                raise LinguaError(ErrorCode.INVALID_FORMAT, "Encrypted archives are not supported")
            unix_mode = member.external_attr >> 16
            if member.create_system == 3 and stat.S_IFMT(unix_mode) == stat.S_IFLNK:
                raise LinguaError(ErrorCode.ARCHIVE_UNSAFE, "Archive cannot contain symbolic links")
            if member.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                raise LinguaError(
                    ErrorCode.INVALID_FORMAT, "Archive uses an unsupported compression method"
                )
            if member.file_size > self.settings.max_archive_member_bytes:
                raise LinguaError(
                    ErrorCode.ARCHIVE_LIMIT_EXCEEDED,
                    "Archive member exceeds the configured size limit",
                    {
                        "expanded_bytes": member.file_size,
                        "limit": self.settings.max_archive_member_bytes,
                    },
                )
            total += member.file_size
            if total > self.settings.max_archive_uncompressed_bytes:
                raise LinguaError(
                    ErrorCode.ARCHIVE_LIMIT_EXCEEDED,
                    "Archive expands beyond the configured limit",
                    {
                        "expanded_bytes": total,
                        "limit": self.settings.max_archive_uncompressed_bytes,
                    },
                )
            ratio = (
                member.file_size / member.compress_size
                if member.compress_size > 0
                else (float("inf") if member.file_size else 0.0)
            )
            if ratio > self.settings.max_archive_compression_ratio:
                raise LinguaError(
                    ErrorCode.ARCHIVE_LIMIT_EXCEEDED,
                    "Archive member exceeds the configured compression ratio",
                    {"limit": self.settings.max_archive_compression_ratio},
                )
        if not needle:
            return False
        try:
            for member in members:
                if member.is_dir():
                    continue
                with archive.open(member, "r") as expanded:
                    if self._stream_contains(expanded, needle):
                        return True
        except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
            raise LinguaError(ErrorCode.INVALID_FORMAT, "Archive member could not be read") from exc
        return False

    def create_project_from_stream(
        self,
        *,
        name: str,
        kind: str,
        source_language: str,
        target_language: str,
        source_name: str,
        source: BinaryIO,
        media_type: str | None = None,
    ) -> dict[str, Any]:
        """Validate and atomically publish an imported Source from a bounded stream."""

        self._reject_runtime_secret_fields(
            name, kind, source_language, target_language, source_name, media_type or ""
        )
        name, kind, source_language, target_language = self._validate_project_fields(
            name,
            kind,
            source_language,
            target_language,
        )
        source_name = source_name.strip()
        source_kind = self._source_kind(kind, source_name)
        if source_kind == "epub" and not is_bcp47_language_tag(target_language):
            raise LinguaError(
                ErrorCode.CONFIGURATION,
                "EPUB target language must be a plausible BCP 47 language tag",
            )
        project_id = new_id()
        artifact_id = new_id()
        guessed_type = self._redact_content_text(
            media_type or mimetypes.guess_type(source_name)[0] or "application/octet-stream"
        )
        try:
            stored = self.store.write_stream(
                project_id=project_id,
                artifact_id=artifact_id,
                filename=source_name,
                source=source,
                max_bytes=self.settings.max_upload_bytes,
            )
            if stored.size == 0:
                raise LinguaError(ErrorCode.INVALID_FORMAT, "Imported source is empty")
            stored_path = self.store.path(stored.storage_key)
            secret = self.settings.openai_api_key
            if secret and self._path_contains(stored_path, secret.encode()):
                raise LinguaError(
                    ErrorCode.CONFIGURATION,
                    "Imported source contains the runtime Provider secret; remove it before import",
                )
            source_metadata: dict[str, Any] = {}
            if source_kind == "epub":
                inspection = inspect_epub(stored_path, self.settings.archive_limits())
                if secret:
                    with zipfile.ZipFile(stored_path, "r") as archive:
                        if self._archive_contains(archive, secret.encode()):
                            raise LinguaError(
                                ErrorCode.CONFIGURATION,
                                "Imported source contains the runtime Provider secret; "
                                "remove it before import",
                            )
                metadata = inspection.get("metadata", {})
                validation = inspection.get("validation", {})
                titles = list(metadata.get("titles", []))
                creators = list(metadata.get("creators", []))
                subjects = list(metadata.get("subjects", []))
                descriptions = list(metadata.get("descriptions", []))
                languages = list(metadata.get("languages", []))
                source_metadata = {
                    "format": "epub",
                    "epub_version": inspection["epub_version"],
                    "title": titles[0] if titles else None,
                    "titles": titles,
                    "creators": creators,
                    "subjects": subjects,
                    "descriptions": descriptions,
                    "language": languages[0] if languages else None,
                    "languages": languages,
                    "document_count": validation.get("document_count", 0),
                    "chapter_count": validation.get("spine_document_count", 0),
                    "resource_count": validation.get("resource_count", 0),
                    "text_unit_count": validation.get("text_unit_count", 0),
                    "cover_path": inspection.get("cover_path"),
                    "navigation_documents": inspection.get("navigation_documents", []),
                }
                guessed_type = "application/epub+zip"
            elif source_kind == "cbz":
                manga_manifest = inspect_manga(
                    stored_path,
                    filename=source_name,
                    archive_limits=self.settings.archive_limits(),
                    maximum_bytes=self.settings.max_upload_bytes,
                )
                source_metadata = {
                    "format": "cbz",
                    "page_count": len(manga_manifest.pages),
                }
                guessed_type = "application/vnd.comicbook+zip"
                if secret:
                    with zipfile.ZipFile(stored_path, "r") as archive:
                        contains_secret = self._archive_contains(archive, secret.encode())
                    if contains_secret:
                        raise LinguaError(
                            ErrorCode.CONFIGURATION,
                            "Imported source contains the runtime Provider secret; "
                            "remove it before import",
                        )
            with self.database.session() as session:
                project = Project(
                    id=project_id,
                    name=name,
                    kind=kind,
                    source_language=source_language,
                    target_language=target_language,
                )
                artifact = Artifact(
                    id=artifact_id,
                    project_id=project_id,
                    kind="source_original",
                    filename=stored.filename,
                    media_type=guessed_type,
                    size=stored.size,
                    checksum=stored.checksum,
                    storage_key=stored.storage_key,
                    metadata_json=json.dumps(
                        {
                            "original_name": source_name,
                            "immutable": True,
                            **source_metadata,
                        },
                        ensure_ascii=False,
                    ),
                )
                source_row = Source(
                    id=new_id(),
                    project_id=project_id,
                    kind=source_kind,
                    original_name=source_name,
                    media_type=guessed_type,
                    size=stored.size,
                    checksum=stored.checksum,
                    artifact_id=artifact_id,
                    metadata_json=json.dumps(source_metadata, ensure_ascii=False),
                )
                default_profile = TranslationProfile(
                    id=new_id(),
                    name=f"Default {source_language} → {target_language}",
                    source_language=source_language,
                    target_language=target_language,
                    provider_id="mock",
                    model="mock-v1",
                )
                session.add_all([project, artifact, source_row, default_profile])
        except Exception:
            self.store.remove_project_payloads(project_id)
            raise
        return self.get_project(project_id)

    def create_project_from_path(
        self,
        *,
        name: str,
        kind: str,
        source_language: str,
        target_language: str,
        source_path: Path,
    ) -> dict[str, Any]:
        path = source_path.expanduser().resolve()
        if not path.exists():
            raise LinguaError(ErrorCode.NOT_FOUND, f"Source path does not exist: {path}")
        media_type: str | None
        if path.is_dir():
            if kind.lower() != "manga":
                raise LinguaError(
                    ErrorCode.INVALID_FORMAT, "Only manga projects accept an image directory"
                )
            buffer = io.BytesIO()
            images = sorted(
                (
                    candidate
                    for candidate in path.rglob("*")
                    if candidate.is_file()
                    and not candidate.is_symlink()
                    and candidate.suffix.lower() in _IMAGE_SUFFIXES
                ),
                key=lambda candidate: candidate.relative_to(path).as_posix().casefold(),
            )
            if not images:
                raise LinguaError(ErrorCode.INVALID_FORMAT, "Image directory contains no images")
            if len(images) > self.settings.max_archive_files:
                raise LinguaError(ErrorCode.INVALID_FORMAT, "Image directory has too many files")
            total = sum(image.stat().st_size for image in images)
            if total > self.settings.max_upload_bytes:
                raise LinguaError(
                    ErrorCode.INVALID_FORMAT, "Image directory exceeds the size limit"
                )
            with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for image in images:
                    archive.write(image, arcname=image.relative_to(path).as_posix())
            source_name = f"{path.name}.cbz"
            media_type = "application/vnd.comicbook+zip"
            return self.create_project(
                name=name,
                kind=kind,
                source_language=source_language,
                target_language=target_language,
                source_name=source_name,
                source_bytes=buffer.getvalue(),
                media_type=media_type,
            )
        else:
            source_name = path.name
            media_type = mimetypes.guess_type(path.name)[0]
            with path.open("rb") as source:
                return self.create_project_from_stream(
                    name=name,
                    kind=kind,
                    source_language=source_language,
                    target_language=target_language,
                    source_name=source_name,
                    source=source,
                    media_type=media_type,
                )

    def list_projects(self) -> list[dict[str, Any]]:
        with self.database.session() as session:
            projects = session.scalars(
                select(Project)
                .options(selectinload(Project.jobs))
                .order_by(Project.created_at.desc())
            ).all()
            return [self._project_public(project, detailed=False) for project in projects]

    def get_project(self, project_id: str) -> dict[str, Any]:
        with self.database.session() as session:
            project = session.scalar(
                select(Project)
                .where(Project.id == project_id)
                .options(
                    selectinload(Project.sources),
                    selectinload(Project.jobs),
                    selectinload(Project.artifacts),
                )
            )
            if project is None:
                raise LinguaError(ErrorCode.NOT_FOUND, "Project not found")
            return self._project_public(project, detailed=True)

    def _project_public(self, project: Project, *, detailed: bool) -> dict[str, Any]:
        latest_job = max(project.jobs, key=lambda job: job.requested_at, default=None)
        value: dict[str, Any] = {
            "id": project.id,
            "name": project.name,
            "kind": project.kind,
            "source_language": project.source_language,
            "target_language": project.target_language,
            "created_at": _iso(project.created_at),
            "updated_at": _iso(project.updated_at),
            "latest_job": self._job_summary(latest_job) if latest_job else None,
        }
        if detailed:
            value["sources"] = [self._source_public(source) for source in project.sources]
            value["jobs"] = [
                self._job_summary(job)
                for job in sorted(project.jobs, key=lambda item: item.requested_at, reverse=True)
            ]
            value["artifacts"] = [
                self._artifact_public(artifact)
                for artifact in sorted(project.artifacts, key=lambda item: item.created_at)
            ]
        return value

    @staticmethod
    def _source_public(source: Source) -> dict[str, Any]:
        return {
            "id": source.id,
            "kind": source.kind,
            "original_name": source.original_name,
            "media_type": source.media_type,
            "size": source.size,
            "checksum": source.checksum,
            "artifact_id": source.artifact_id,
            "metadata": _loads(source.metadata_json, {}),
            "created_at": _iso(source.created_at),
        }

    def project_deletion_impact(self, project_id: str) -> dict[str, int]:
        with self.database.session() as session:
            project = session.get(Project, project_id)
            if project is None:
                raise LinguaError(ErrorCode.NOT_FOUND, "Project not found")
            return {
                "sources": session.scalar(
                    select(func.count()).select_from(Source).where(Source.project_id == project_id)
                )
                or 0,
                "jobs": session.scalar(
                    select(func.count()).select_from(Job).where(Job.project_id == project_id)
                )
                or 0,
                "artifacts": session.scalar(
                    select(func.count())
                    .select_from(Artifact)
                    .where(Artifact.project_id == project_id)
                )
                or 0,
            }

    def delete_project(self, project_id: str, *, confirmed: bool) -> dict[str, Any]:
        impact = self.project_deletion_impact(project_id)
        if not confirmed:
            raise LinguaError(
                ErrorCode.INVALID_STATE,
                "Project deletion requires explicit confirmation",
                {"impact": impact},
            )
        with self.database.session() as session:
            project = session.get(Project, project_id)
            if project is None:
                raise LinguaError(ErrorCode.NOT_FOUND, "Project not found")
            active_jobs = session.execute(
                select(Job.id, Job.status).where(
                    Job.project_id == project_id,
                    Job.status.not_in(TERMINAL_JOB_STATUSES),
                )
            ).all()
            if active_jobs:
                raise LinguaError(
                    ErrorCode.INVALID_STATE,
                    "Project cannot be deleted while it has active Jobs; cancel them first",
                    {
                        "active_jobs": [
                            {"id": job_id, "status": str(status)} for job_id, status in active_jobs
                        ]
                    },
                )
            session.delete(project)
        cleanup_error = None
        try:
            self.store.remove_project_payloads(project_id)
        except OSError as exc:
            cleanup_error = type(exc).__name__
        return {"deleted": project_id, "impact": impact, "cleanup_error": cleanup_error}

    def create_profile(
        self,
        *,
        name: str,
        source_language: str,
        target_language: str,
        provider_id: str,
        model: str | None = None,
        style: str = "Preserve tone and paragraph structure.",
        prompt_template: str | None = None,
        prompt_version: str = "v1",
        batch_size: int = 8,
        model_parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        cleaned_name = self._redact_content_text(name).strip()
        cleaned_source = self._redact_content_text(source_language).strip()
        cleaned_target = self._redact_content_text(target_language).strip()
        cleaned_style = self._redact_content_text(style).strip()
        cleaned_prompt = self._redact_content_text(
            prompt_template
            or (
                "Translate from {source_language} to {target_language}. "
                "Style guidance: {style}. Preserve dialogue and paragraph structure.\n\n{text}"
            )
        )
        cleaned_version = self._redact_content_text(prompt_version).strip()
        if not cleaned_name or len(cleaned_name) > 120:
            raise LinguaError(ErrorCode.CONFIGURATION, "Profile name must be 1-120 characters")
        if not cleaned_source or not cleaned_target:
            raise LinguaError(
                ErrorCode.CONFIGURATION, "Profile source and target languages are required"
            )
        if not cleaned_style or not cleaned_version:
            raise LinguaError(
                ErrorCode.CONFIGURATION, "Profile style and prompt version are required"
            )
        try:
            cleaned_prompt.format(
                source_language=cleaned_source,
                target_language=cleaned_target,
                style=cleaned_style,
                text="validation",
            )
        except (IndexError, KeyError, ValueError) as exc:
            raise LinguaError(
                ErrorCode.CONFIGURATION,
                "Profile prompt template contains an unsupported placeholder",
            ) from exc
        if "{text}" not in cleaned_prompt:
            raise LinguaError(
                ErrorCode.CONFIGURATION, "Profile prompt template must include {text}"
            )
        sanitized_parameters = self.redact_for_persistence(model_parameters or {})
        if not isinstance(sanitized_parameters, dict):
            raise LinguaError(ErrorCode.CONFIGURATION, "Profile model parameters must be an object")
        reserved = {"model", "messages"} & set(sanitized_parameters)
        if reserved:
            raise LinguaError(
                ErrorCode.CONFIGURATION,
                "Profile model parameters cannot override Provider request structure",
                {"reserved_keys": sorted(reserved)},
            )
        provider = self.providers.get(provider_id)
        if batch_size < 1 or batch_size > 100:
            raise LinguaError(ErrorCode.CONFIGURATION, "Profile batch size must be 1-100")
        profile = TranslationProfile(
            id=new_id(),
            name=cleaned_name,
            source_language=cleaned_source,
            target_language=cleaned_target,
            provider_id=provider_id,
            model=self._redact_text(
                model
                or str(
                    self._provider_public_status(provider).get("model")
                    or self.settings.openai_model
                )
            ),
            style=cleaned_style,
            prompt_template=cleaned_prompt,
            prompt_version=cleaned_version,
            batch_size=batch_size,
            model_parameters_json=json.dumps(sanitized_parameters, ensure_ascii=False),
        )
        with self.database.session() as session:
            session.add(profile)
        return self._profile_public(profile)

    def list_profiles(self) -> list[dict[str, Any]]:
        with self.database.session() as session:
            profiles = session.scalars(
                select(TranslationProfile).order_by(TranslationProfile.created_at)
            ).all()
            return [self._profile_public(profile) for profile in profiles]

    @staticmethod
    def _profile_public(profile: TranslationProfile) -> dict[str, Any]:
        return {
            "id": profile.id,
            "name": profile.name,
            "source_language": profile.source_language,
            "target_language": profile.target_language,
            "provider_id": profile.provider_id,
            "model": profile.model,
            "style": profile.style,
            "context_strategy": profile.context_strategy,
            "prompt_template": profile.prompt_template,
            "prompt_version": profile.prompt_version,
            "batch_size": profile.batch_size,
            "model_parameters": _loads(profile.model_parameters_json, {}),
            "created_at": _iso(profile.created_at),
            "updated_at": _iso(profile.updated_at),
        }

    def create_job(
        self,
        *,
        project_id: str,
        pipeline_key: str | None = None,
        profile_id: str | None = None,
        provider_id: str | None = None,
        adapter_id: str | None = None,
    ) -> dict[str, Any]:
        with self.database.session() as session:
            project = session.get(Project, project_id)
            if project is None:
                raise LinguaError(ErrorCode.NOT_FOUND, "Project not found")
            source = session.scalar(
                select(Source)
                .where(Source.project_id == project_id)
                .order_by(Source.created_at.desc())
            )
            if source is None:
                raise LinguaError(ErrorCode.INVALID_STATE, "Project has no imported source")
            pipeline = (
                get_pipeline(pipeline_key)
                if pipeline_key
                else default_pipeline(project.kind, source.kind)
            )
            if pipeline.project_kind != project.kind:
                raise LinguaError(
                    ErrorCode.CONFIGURATION, "Pipeline does not support this project kind"
                )
            if source.kind not in pipeline.source_kinds:
                raise LinguaError(
                    ErrorCode.CONFIGURATION,
                    "Pipeline does not support the Project source format",
                    {"pipeline_key": pipeline.key, "source_kind": source.kind},
                )
            profile = session.get(TranslationProfile, profile_id) if profile_id else None
            if profile_id and profile is None:
                raise LinguaError(ErrorCode.NOT_FOUND, "Translation Profile not found")
            if profile and (
                profile.source_language != project.source_language
                or profile.target_language != project.target_language
            ):
                raise LinguaError(
                    ErrorCode.CONFIGURATION,
                    "Translation Profile language pair does not match the Project",
                )
            selected_provider = provider_id or (profile.provider_id if profile else "mock")
            provider = self.providers.get(selected_provider)
            if profile is None:
                profile = TranslationProfile(
                    id=new_id(),
                    name=f"Job profile {project.source_language} → {project.target_language}",
                    source_language=project.source_language,
                    target_language=project.target_language,
                    provider_id=selected_provider,
                    model=self._redact_text(
                        str(self._provider_public_status(provider).get("model") or "unknown")
                    ),
                )
                session.add(profile)
                session.flush()
            if project.kind == "manga":
                adapter_id = adapter_id or "mock-manga"
                self.adapters.get(adapter_id, "manga_full_pipeline")
            snapshot = self._profile_public(profile)
            snapshot["provider_id"] = selected_provider
            snapshot["model"] = self._redact_text(
                str(self._provider_public_status(provider).get("model") or "unknown")
            )
            job = Job(
                id=new_id(),
                project_id=project_id,
                translation_profile_id=profile.id,
                pipeline_key=pipeline.key,
                pipeline_version=pipeline.version,
                provider_id=selected_provider,
                adapter_id=adapter_id,
                status=JobStatus.QUEUED,
                profile_snapshot_json=json.dumps(snapshot, ensure_ascii=False),
            )
            session.add(job)
            session.flush()
            for index, definition in enumerate(pipeline.steps):
                executor_id = None
                if definition.executor_type == "provider":
                    executor_id = selected_provider
                elif definition.executor_type == "adapter":
                    executor_id = adapter_id
                session.add(
                    StepRun(
                        id=new_id(),
                        job_id=job.id,
                        step_key=definition.key,
                        step_order=index,
                        capability=definition.capability,
                        executor_type=definition.executor_type,
                        executor_id=executor_id,
                        status=StepStatus.PENDING,
                        config_snapshot_json=json.dumps(
                            {
                                "pipeline": pipeline.key,
                                "pipeline_version": pipeline.version,
                                "executor_id": executor_id,
                            },
                            ensure_ascii=False,
                        ),
                    )
                )
        return self.get_job(job.id)

    def list_jobs(
        self, *, project_id: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        statement = select(Job).order_by(Job.requested_at.desc())
        if project_id:
            statement = statement.where(Job.project_id == project_id)
        if status:
            statement = statement.where(Job.status == status)
        with self.database.session() as session:
            jobs = session.scalars(statement).all()
            return [self._job_summary(job) for job in jobs]

    @staticmethod
    def _job_summary(job: Job) -> dict[str, Any]:
        return {
            "id": job.id,
            "project_id": job.project_id,
            "pipeline_key": job.pipeline_key,
            "provider_id": job.provider_id,
            "adapter_id": job.adapter_id,
            "status": job.status,
            "progress": job.progress,
            "control_request": job.control_request,
            "requested_at": _iso(job.requested_at),
            "started_at": _iso(job.started_at),
            "ended_at": _iso(job.ended_at),
            "error": (
                {
                    "code": job.error_code,
                    "message": job.error_message,
                    "details": _loads(job.error_details_json, {}),
                }
                if job.error_code
                else None
            ),
        }

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self.database.session() as session:
            job = session.scalar(
                select(Job)
                .where(Job.id == job_id)
                .options(selectinload(Job.steps).selectinload(StepRun.logs))
            )
            if job is None:
                raise LinguaError(ErrorCode.NOT_FOUND, "Job not found")
            value = self._job_summary(job)
            value["profile_snapshot"] = _loads(job.profile_snapshot_json, {})
            value["steps"] = [self._step_public(step) for step in job.steps]
            value["artifacts"] = self.list_artifacts(project_id=job.project_id, job_id=job.id)
            return value

    @staticmethod
    def _step_public(step: StepRun) -> dict[str, Any]:
        return {
            "id": step.id,
            "key": step.step_key,
            "order": step.step_order,
            "capability": step.capability,
            "executor_type": step.executor_type,
            "executor_id": step.executor_id,
            "status": step.status,
            "attempt_count": step.attempt_count,
            "progress": step.progress,
            "started_at": _iso(step.started_at),
            "ended_at": _iso(step.ended_at),
            "input_artifact_ids": _loads(step.input_artifact_ids_json, []),
            "output_artifact_ids": _loads(step.output_artifact_ids_json, []),
            "config_snapshot": _loads(step.config_snapshot_json, {}),
            "error": (
                {
                    "code": step.error_code,
                    "message": step.error_message,
                    "details": _loads(step.error_details_json, {}),
                }
                if step.error_code
                else None
            ),
            "logs": [
                {
                    "id": log.id,
                    "level": log.level,
                    "message": log.message,
                    "details": _loads(log.details_json, {}),
                    "created_at": _iso(log.created_at),
                }
                for log in step.logs
            ],
        }

    def pause_job(self, job_id: str) -> dict[str, Any]:
        with self.database.session() as session:
            job = session.get(Job, job_id)
            if job is None:
                raise LinguaError(ErrorCode.NOT_FOUND, "Job not found")
            if job.status == JobStatus.QUEUED:
                ensure_job_transition(job.status, JobStatus.PAUSED)
                job.status = JobStatus.PAUSED
            elif job.status == JobStatus.RUNNING:
                job.control_request = "pause"
            else:
                raise LinguaError(ErrorCode.INVALID_STATE, "Only queued or running Jobs can pause")
            job.updated_at = utcnow()
        return self.get_job(job_id)

    def resume_job(self, job_id: str) -> dict[str, Any]:
        with self.database.session() as session:
            job = session.get(Job, job_id)
            if job is None:
                raise LinguaError(ErrorCode.NOT_FOUND, "Job not found")
            ensure_job_transition(job.status, JobStatus.QUEUED)
            job.status = JobStatus.QUEUED
            job.control_request = None
            job.runner_token = None
            for step in session.scalars(
                select(StepRun).where(StepRun.job_id == job_id, StepRun.status == StepStatus.PAUSED)
            ):
                ensure_step_transition(step.status, StepStatus.PENDING)
                step.status = StepStatus.PENDING
            job.updated_at = utcnow()
        return self.get_job(job_id)

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        with self.database.session() as session:
            job = session.get(Job, job_id)
            if job is None:
                raise LinguaError(ErrorCode.NOT_FOUND, "Job not found")
            if job.status in {JobStatus.QUEUED, JobStatus.PAUSED}:
                ensure_job_transition(job.status, JobStatus.CANCELLED)
                job.status = JobStatus.CANCELLED
                job.ended_at = utcnow()
                job.control_request = None
                job.runner_token = None
                job.error_code = ErrorCode.CANCELLED
                job.error_message = "Job was cancelled before further work began"
                for step in session.scalars(
                    select(StepRun).where(
                        StepRun.job_id == job_id,
                        StepRun.status.in_([StepStatus.PENDING, StepStatus.PAUSED]),
                    )
                ):
                    ensure_step_transition(step.status, StepStatus.CANCELLED)
                    step.status = StepStatus.CANCELLED
                    step.ended_at = utcnow()
                    step.error_code = ErrorCode.CANCELLED
                    step.error_message = "Step did not run because the Job was cancelled"
            elif job.status == JobStatus.RUNNING:
                ensure_job_transition(job.status, JobStatus.CANCELLING)
                job.status = JobStatus.CANCELLING
                job.control_request = "cancel"
            elif job.status == JobStatus.CANCELLING:
                pass
            else:
                raise LinguaError(ErrorCode.INVALID_STATE, "This Job cannot be cancelled")
            job.updated_at = utcnow()
        return self.get_job(job_id)

    def retry_job(self, job_id: str) -> dict[str, Any]:
        with self.database.session() as session:
            job = session.scalar(
                select(Job).where(Job.id == job_id).options(selectinload(Job.steps))
            )
            if job is None:
                raise LinguaError(ErrorCode.NOT_FOUND, "Job not found")
            if job.status not in {JobStatus.FAILED, JobStatus.PARTIALLY_SUCCEEDED}:
                raise LinguaError(
                    ErrorCode.INVALID_STATE, "Only failed or partially succeeded Jobs can retry"
                )
            retryable = [
                step
                for step in job.steps
                if step.status
                in {StepStatus.FAILED, StepStatus.PARTIALLY_SUCCEEDED, StepStatus.CANCELLED}
            ]
            if not retryable:
                raise LinguaError(ErrorCode.INVALID_STATE, "Job has no failed Step to retry")
            restart_order = min(step.step_order for step in retryable)
            has_legacy_segments = bool(
                session.scalar(
                    select(func.count())
                    .select_from(TranslationSegment)
                    .where(
                        TranslationSegment.job_id == job_id,
                        TranslationSegment.segment_key.is_(None),
                    )
                )
            )
            has_legacy_manga_manifest = False
            if job.pipeline_key == "manga_full_v1":
                manga_manifest = session.scalar(
                    select(Artifact)
                    .where(
                        Artifact.job_id == job_id,
                        Artifact.kind == "manga_manifest",
                    )
                    .order_by(Artifact.created_at.desc())
                    .limit(1)
                )
                if manga_manifest is not None:
                    try:
                        manifest_payload = json.loads(
                            self.store.read_bytes(manga_manifest.storage_key)
                        )
                    except (LinguaError, json.JSONDecodeError, UnicodeDecodeError):
                        has_legacy_manga_manifest = True
                    else:
                        has_legacy_manga_manifest = not (
                            isinstance(manifest_payload, dict)
                            and manifest_payload.get("schema_version")
                            == "runtime-manga-manifest.v1"
                        )
            if has_legacy_segments or has_legacy_manga_manifest:
                # v0.2 Segment rows and Manga manifests predate the canonical
                # v0.3 IDs/DTOs. Re-run pure preparation from the immutable
                # Source instead of trusting or rewriting historical outputs.
                restart_order = min(step.step_order for step in job.steps)
            for step in job.steps:
                if step.step_order < restart_order:
                    continue
                self._append_log(
                    session,
                    step,
                    "INFO",
                    "Step scheduled for retry",
                    {
                        "previous_status": step.status,
                        "previous_error": step.error_code,
                        "previous_started_at": _iso(step.started_at),
                        "previous_ended_at": _iso(step.ended_at),
                    },
                )
                if step.status != StepStatus.PENDING:
                    ensure_step_transition(step.status, StepStatus.PENDING)
                step.status = StepStatus.PENDING
                step.started_at = None
                step.ended_at = None
                step.progress = 0.0
                step.input_artifact_ids_json = "[]"
                step.output_artifact_ids_json = "[]"
                step.error_code = None
                step.error_message = None
                step.error_details_json = None
            session.execute(
                update(TranslationSegment)
                .where(
                    TranslationSegment.job_id == job_id,
                    TranslationSegment.status == "failed",
                )
                .values(
                    status="pending",
                    translated_text=None,
                    error_code=None,
                    error_message=None,
                )
            )
            ensure_job_transition(job.status, JobStatus.QUEUED)
            job.status = JobStatus.QUEUED
            job.progress = sum(
                get_pipeline(job.pipeline_key).steps[index].weight
                for index, step in enumerate(job.steps)
                if step.status == StepStatus.SUCCEEDED
            )
            job.control_request = None
            job.runner_token = None
            job.ended_at = None
            job.error_code = None
            job.error_message = None
            job.error_details_json = None
            job.updated_at = utcnow()
        return self.get_job(job_id)

    def recover_interrupted_jobs(self) -> int:
        recovered = 0
        with self.database.session() as session:
            jobs = session.scalars(
                select(Job)
                .where(Job.status.in_([JobStatus.RUNNING, JobStatus.CANCELLING]))
                .options(selectinload(Job.steps))
            ).all()
            for job in jobs:
                active = next(
                    (
                        step
                        for step in job.steps
                        if step.status in {StepStatus.RUNNING, StepStatus.CANCELLING}
                    ),
                    None,
                )
                if active:
                    active.status = StepStatus.FAILED
                    active.ended_at = utcnow()
                    active.error_code = ErrorCode.PROCESS_INTERRUPTED
                    active.error_message = "Step was interrupted by process restart"
                    self._append_log(
                        session,
                        active,
                        "ERROR",
                        "Process restart interrupted this Step; retry is available",
                        {"error_code": ErrorCode.PROCESS_INTERRUPTED},
                    )
                session.execute(
                    update(TranslationSegment)
                    .where(
                        TranslationSegment.job_id == job.id,
                        TranslationSegment.status == "running",
                    )
                    .values(
                        status="failed",
                        error_code=ErrorCode.PROCESS_INTERRUPTED,
                        error_message="Segment was interrupted by process restart",
                        updated_at=utcnow(),
                    )
                )
                job.status = JobStatus.FAILED
                job.runner_token = None
                job.control_request = None
                job.ended_at = utcnow()
                job.error_code = ErrorCode.PROCESS_INTERRUPTED
                job.error_message = "Job was interrupted by process restart"
                recovered += 1
        return recovered

    def claim_next_job(self, runner_token: str) -> str | None:
        with self.database.session() as session:
            candidate = session.scalar(
                select(Job.id)
                .where(Job.status == JobStatus.QUEUED)
                .order_by(Job.requested_at)
                .limit(1)
            )
            if candidate is None:
                return None
            now = utcnow()
            claimed = session.scalar(
                update(Job)
                .where(Job.id == candidate, Job.status == JobStatus.QUEUED)
                .values(
                    status=JobStatus.RUNNING,
                    runner_token=runner_token,
                    started_at=func.coalesce(Job.started_at, now),
                    updated_at=now,
                )
                .returning(Job.id)
            )
            return claimed

    def create_artifact(
        self,
        *,
        project_id: str,
        kind: str,
        filename: str,
        media_type: str,
        payload: bytes,
        job_id: str | None = None,
        step_run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Artifact:
        artifact_id = new_id()
        filename = self._redact_content_text(filename)
        media_type = self._redact_content_text(media_type)
        payload = self._sanitize_artifact_payload(payload, media_type, kind)
        stored = self.store.write_bytes(
            project_id=project_id,
            artifact_id=artifact_id,
            filename=filename,
            payload=payload,
        )
        artifact = Artifact(
            id=artifact_id,
            project_id=project_id,
            job_id=job_id,
            step_run_id=step_run_id,
            kind=kind,
            filename=stored.filename,
            media_type=media_type,
            size=stored.size,
            checksum=stored.checksum,
            storage_key=stored.storage_key,
            metadata_json=json.dumps(
                self._redact_content_value(metadata or {})
                if kind in _CONTENT_ARTIFACT_KINDS
                else self.redact_for_persistence(metadata or {}),
                ensure_ascii=False,
            ),
        )
        try:
            with self.database.session() as session:
                session.add(artifact)
        except Exception:
            self.store.remove(stored.storage_key)
            raise
        return artifact

    def create_artifact_from_path(
        self,
        *,
        project_id: str,
        kind: str,
        filename: str,
        media_type: str,
        source_path: Path,
        job_id: str | None = None,
        step_run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Artifact:
        """Publish a generated file without materializing it as one in-memory byte string."""

        artifact_id = new_id()
        filename = self._redact_content_text(filename)
        media_type = self._redact_content_text(media_type)
        secret = self.settings.openai_api_key
        if secret and self._path_contains(source_path, secret.encode()):
            raise LinguaError(
                ErrorCode.STORAGE,
                "Refusing to persist an Artifact containing the runtime Provider secret",
            )
        if secret and kind in _ARCHIVE_ARTIFACT_KINDS:
            try:
                with zipfile.ZipFile(source_path, "r") as archive:
                    if self._archive_contains(archive, secret.encode()):
                        raise LinguaError(
                            ErrorCode.STORAGE,
                            "Refusing to persist an archive Artifact containing the runtime "
                            "Provider secret",
                        )
            except LinguaError:
                raise
            except zipfile.BadZipFile as exc:
                raise LinguaError(
                    ErrorCode.INVALID_FORMAT,
                    "Generated archive Artifact is not a valid ZIP file",
                ) from exc
        stored = self.store.write_file(
            project_id=project_id,
            artifact_id=artifact_id,
            filename=filename,
            source_path=source_path,
        )
        artifact = Artifact(
            id=artifact_id,
            project_id=project_id,
            job_id=job_id,
            step_run_id=step_run_id,
            kind=kind,
            filename=stored.filename,
            media_type=media_type,
            size=stored.size,
            checksum=stored.checksum,
            storage_key=stored.storage_key,
            metadata_json=json.dumps(
                self._redact_content_value(metadata or {})
                if kind in _CONTENT_ARTIFACT_KINDS
                else self.redact_for_persistence(metadata or {}),
                ensure_ascii=False,
            ),
        )
        try:
            with self.database.session() as session:
                session.add(artifact)
        except Exception:
            self.store.remove(stored.storage_key)
            raise
        return artifact

    @staticmethod
    def _artifact_public(artifact: Artifact) -> dict[str, Any]:
        return {
            "id": artifact.id,
            "project_id": artifact.project_id,
            "job_id": artifact.job_id,
            "step_run_id": artifact.step_run_id,
            "kind": artifact.kind,
            "filename": artifact.filename,
            "media_type": artifact.media_type,
            "size": artifact.size,
            "checksum": artifact.checksum,
            "metadata": _loads(artifact.metadata_json, {}),
            "created_at": _iso(artifact.created_at),
            "download_url": f"/api/artifacts/{artifact.id}/download",
        }

    def list_artifacts(self, *, project_id: str, job_id: str | None = None) -> list[dict[str, Any]]:
        statement = select(Artifact).where(Artifact.project_id == project_id)
        if job_id:
            statement = statement.where(Artifact.job_id == job_id)
        with self.database.session() as session:
            artifacts = session.scalars(statement.order_by(Artifact.created_at)).all()
            return [self._artifact_public(artifact) for artifact in artifacts]

    def get_artifact(self, artifact_id: str) -> dict[str, Any]:
        with self.database.session() as session:
            artifact = session.get(Artifact, artifact_id)
            if artifact is None:
                raise LinguaError(ErrorCode.NOT_FOUND, "Artifact not found")
            return self._artifact_public(artifact)

    def read_artifact(self, artifact_id: str) -> tuple[dict[str, Any], bytes]:
        with self.database.session() as session:
            artifact = session.get(Artifact, artifact_id)
            if artifact is None:
                raise LinguaError(ErrorCode.NOT_FOUND, "Artifact not found")
            public = self._artifact_public(artifact)
            payload = self.store.read_bytes(artifact.storage_key)
            if len(payload) != artifact.size:
                raise LinguaError(ErrorCode.OUTPUT_MISSING, "Artifact payload size is inconsistent")
            return public, payload

    def artifact_path(self, artifact_id: str) -> tuple[dict[str, Any], Path]:
        """Return verified download metadata and a private path for an interface response."""

        with self.database.session() as session:
            artifact = session.get(Artifact, artifact_id)
            if artifact is None:
                raise LinguaError(ErrorCode.NOT_FOUND, "Artifact not found")
            public = self._artifact_public(artifact)
            path = self.store.path(artifact.storage_key)
            if path.stat().st_size != artifact.size:
                raise LinguaError(ErrorCode.OUTPUT_MISSING, "Artifact payload size is inconsistent")
            return public, path

    def copy_artifact(self, artifact_id: str, destination: Path) -> tuple[dict[str, Any], Path]:
        """Copy an Artifact through the application boundary using an atomic streamed write."""

        with self.database.session() as session:
            artifact = session.get(Artifact, artifact_id)
            if artifact is None:
                raise LinguaError(ErrorCode.NOT_FOUND, "Artifact not found")
            public = self._artifact_public(artifact)
            path = self.store.copy_to_atomic(
                artifact.storage_key, destination.expanduser().resolve()
            )
            if path.stat().st_size != artifact.size:
                path.unlink(missing_ok=True)
                raise LinguaError(ErrorCode.OUTPUT_MISSING, "Copied Artifact size is inconsistent")
            return public, path

    def export_project(
        self, project_id: str, *, format_name: str | None = None
    ) -> list[dict[str, Any]]:
        with self.database.session() as session:
            project = session.get(Project, project_id)
            if project is None:
                raise LinguaError(ErrorCode.NOT_FOUND, "Project not found")
            kinds = (
                {"novel_export_txt", "novel_export_json", "novel_export_epub"}
                if project.kind == "novel"
                else {"manga_export_cbz", "manga_export_image", "manga_page_translated"}
            )
            if format_name:
                normalized = format_name.lower().lstrip(".")
                kinds = {
                    kind
                    for kind in kinds
                    if kind.endswith(f"_{normalized}")
                    or (normalized == "image" and kind == "manga_page_translated")
                }
            artifacts = session.scalars(
                select(Artifact)
                .where(Artifact.project_id == project_id, Artifact.kind.in_(kinds))
                .order_by(Artifact.created_at.desc())
            ).all()
            if not artifacts:
                raise LinguaError(
                    ErrorCode.OUTPUT_MISSING,
                    "Project has no matching completed export; run its Pipeline first",
                )
            latest_job_id = artifacts[0].job_id
            return [
                self._artifact_public(artifact)
                for artifact in artifacts
                if artifact.job_id == latest_job_id
            ]

    def source_artifact(self, project_id: str) -> Artifact:
        with self.database.session() as session:
            source = session.scalar(
                select(Source)
                .where(Source.project_id == project_id)
                .order_by(Source.created_at.desc())
            )
            if source is None:
                raise LinguaError(ErrorCode.NOT_FOUND, "Project source not found")
            artifact = session.get(Artifact, source.artifact_id)
            if artifact is None:
                raise LinguaError(ErrorCode.OUTPUT_MISSING, "Source Artifact metadata is missing")
            session.expunge(artifact)
            return artifact

    def artifact_rows(self, artifact_ids: list[str]) -> list[Artifact]:
        if not artifact_ids:
            return []
        with self.database.session() as session:
            rows = session.scalars(select(Artifact).where(Artifact.id.in_(artifact_ids))).all()
            by_id = {artifact.id: artifact for artifact in rows}
            return [by_id[item] for item in artifact_ids if item in by_id]

    def replace_segments(
        self,
        *,
        project_id: str,
        job_id: str,
        profile: dict[str, Any],
        texts: list[str] | None = None,
        segments: list[dict[str, Any]] | None = None,
    ) -> int:
        if (texts is None) == (segments is None):
            raise ValueError("Provide exactly one of texts or segments")
        records = (
            [{"sequence": sequence, "source_text": text} for sequence, text in enumerate(texts)]
            if texts is not None
            else list(segments or [])
        )
        profile_json = json.dumps(profile, ensure_ascii=False)
        reused = 0
        with self.database.session() as session:
            source_checksum = (
                session.scalar(
                    select(Source.checksum)
                    .where(Source.project_id == project_id)
                    .order_by(Source.created_at.desc())
                    .limit(1)
                )
                or ""
            )
            current_successes = {
                (row.sequence, row.source_text): (row.translated_text, row.model)
                for row in session.scalars(
                    select(TranslationSegment).where(
                        TranslationSegment.job_id == job_id,
                        TranslationSegment.status == "succeeded",
                        TranslationSegment.translated_text.is_not(None),
                    )
                )
            }
            session.execute(delete(QaFinding).where(QaFinding.job_id == job_id))
            session.execute(delete(TranslationSegment).where(TranslationSegment.job_id == job_id))
            for fallback_sequence, record in enumerate(records):
                sequence = int(record.get("sequence", fallback_sequence))
                text = str(record["source_text"])
                input_hash = record.get("translation_input_hash")
                previous = None
                if isinstance(input_hash, str) and input_hash:
                    previous = session.scalar(
                        select(TranslationSegment)
                        .where(
                            TranslationSegment.project_id == project_id,
                            TranslationSegment.job_id != job_id,
                            TranslationSegment.translation_input_hash == input_hash,
                            TranslationSegment.status == "succeeded",
                            TranslationSegment.translated_text.is_not(None),
                        )
                        .order_by(TranslationSegment.updated_at.desc())
                        .limit(1)
                    )
                if previous is not None:
                    reused += 1
                current_success = current_successes.get((sequence, text))
                if previous is None and current_success is not None:
                    # A v0.2 retry may need to regenerate canonical Segment IDs
                    # from the immutable Source. Preserve successful work from
                    # that same Job when sequence and source text still match.
                    reused += 1
                translated_text = (
                    previous.translated_text
                    if previous is not None
                    else current_success[0]
                    if current_success is not None
                    else None
                )
                translated_model = (
                    previous.model
                    if previous is not None
                    else current_success[1]
                    if current_success is not None
                    else None
                )
                locator = record.get("locator", {})
                segment_key = str(record.get("segment_id") or "") or self._stable_segment_key(
                    source_checksum=source_checksum,
                    sequence=sequence,
                    source_text=text,
                    locator=locator if isinstance(locator, dict) else {},
                )
                session.add(
                    TranslationSegment(
                        id=new_id(),
                        segment_key=segment_key,
                        project_id=project_id,
                        job_id=job_id,
                        sequence=sequence,
                        source_text=text,
                        translated_text=translated_text,
                        status="succeeded" if translated_text is not None else "pending",
                        model=translated_model,
                        profile_snapshot_json=profile_json,
                        prompt_version=str(profile.get("prompt_version", "v1")),
                        source_artifact_id=record.get("source_artifact_id"),
                        source_document=record.get("source_document"),
                        content_role=record.get("content_role"),
                        locator_json=json.dumps(record.get("locator", {}), ensure_ascii=False),
                        source_text_hash=record.get("source_text_hash"),
                        translation_input_hash=input_hash,
                        reused_from_segment_id=previous.id if previous else None,
                    )
                )
        return reused

    @staticmethod
    def _stable_segment_key(
        *,
        source_checksum: str,
        sequence: int,
        source_text: str,
        locator: dict[str, Any],
    ) -> str:
        source_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        location: dict[str, Any] | int = locator if locator else sequence
        payload = json.dumps(
            {
                "schema_version": "runtime-segment-key.v1",
                "source_checksum": source_checksum,
                "location": location,
                "source_hash": source_hash,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def segment_rows(self, job_id: str) -> list[TranslationSegment]:
        with self.database.session() as session:
            rows = session.scalars(
                select(TranslationSegment)
                .where(TranslationSegment.job_id == job_id)
                .order_by(TranslationSegment.sequence)
            ).all()
            for row in rows:
                session.expunge(row)
            return list(rows)

    def update_segment(
        self,
        segment_id: str,
        *,
        status: str,
        translated_text: str | None = None,
        model: str | None = None,
        error: LinguaError | None = None,
    ) -> None:
        with self.database.session() as session:
            segment = session.get(TranslationSegment, segment_id)
            if segment is None:
                raise LinguaError(ErrorCode.NOT_FOUND, "Translation segment not found")
            segment.status = status
            segment.translated_text = (
                self._redact_content_text(translated_text) if translated_text is not None else None
            )
            segment.model = self._redact_text(model) if model is not None else None
            segment.error_code = error.code if error else None
            segment.error_message = self._redact_text(error.message) if error else None
            segment.updated_at = utcnow()

    def list_segments(self, project_id: str, job_id: str | None = None) -> list[dict[str, Any]]:
        with self.database.session() as session:
            selected_job_id = job_id
            if selected_job_id is None:
                selected_job_id = session.scalar(
                    select(TranslationSegment.job_id)
                    .where(TranslationSegment.project_id == project_id)
                    .order_by(TranslationSegment.created_at.desc())
                    .limit(1)
                )
            if selected_job_id is None:
                return []
            statement = select(TranslationSegment).where(
                TranslationSegment.project_id == project_id,
                TranslationSegment.job_id == selected_job_id,
            )
            rows = session.scalars(statement.order_by(TranslationSegment.sequence)).all()
            finding_rows = session.scalars(
                select(QaFinding).where(
                    QaFinding.project_id == project_id,
                    QaFinding.job_id == selected_job_id,
                )
            ).all()
            findings: dict[str, list[dict[str, Any]]] = {}
            for finding in finding_rows:
                if finding.segment_id:
                    findings.setdefault(finding.segment_id, []).append(
                        {
                            "category": finding.category,
                            "severity": finding.severity,
                            "message": finding.message,
                        }
                    )
            return [
                {
                    "id": row.id,
                    "segment_id": row.segment_key
                    or self._stable_segment_key(
                        source_checksum="legacy-v0.2",
                        sequence=row.sequence,
                        source_text=row.source_text,
                        locator=_loads(row.locator_json, {}),
                    ),
                    "job_id": row.job_id,
                    "sequence": row.sequence,
                    "source_artifact_id": row.source_artifact_id,
                    "source_document": row.source_document,
                    "content_role": row.content_role,
                    "locator": _loads(row.locator_json, {}),
                    "source_text_hash": row.source_text_hash,
                    "translation_input_hash": row.translation_input_hash,
                    "reused_from_segment_id": row.reused_from_segment_id,
                    "source_text": row.source_text,
                    "translated_text": row.translated_text,
                    "status": row.status,
                    "model": row.model,
                    "prompt_version": row.prompt_version,
                    "error": (
                        {"code": row.error_code, "message": row.error_message}
                        if row.error_code
                        else None
                    ),
                    "qa_findings": findings.get(row.id, []),
                }
                for row in rows
            ]

    def replace_qa(self, job_id: str, project_id: str, findings: list[dict[str, str]]) -> None:
        with self.database.session() as session:
            session.execute(delete(QaFinding).where(QaFinding.job_id == job_id))
            for finding in findings:
                session.add(
                    QaFinding(
                        project_id=project_id,
                        job_id=job_id,
                        segment_id=finding.get("segment_id"),
                        category=finding["category"],
                        severity=finding["severity"],
                        message=finding["message"],
                    )
                )

    def job_control(self, job_id: str) -> tuple[str, str | None]:
        with self.database.session() as session:
            job = session.get(Job, job_id)
            if job is None:
                raise LinguaError(ErrorCode.NOT_FOUND, "Job not found")
            return job.status, job.control_request

    def step_inputs(self, step_id: str, artifact_ids: list[str]) -> None:
        with self.database.session() as session:
            step = session.get(StepRun, step_id)
            if step is None:
                raise LinguaError(ErrorCode.NOT_FOUND, "Step not found")
            step.input_artifact_ids_json = json.dumps(artifact_ids)

    def start_step(self, step_id: str) -> StepRun:
        with self.database.session() as session:
            step = session.get(StepRun, step_id)
            if step is None:
                raise LinguaError(ErrorCode.NOT_FOUND, "Step not found")
            ensure_step_transition(step.status, StepStatus.RUNNING)
            step.status = StepStatus.RUNNING
            step.attempt_count += 1
            step.started_at = utcnow()
            step.ended_at = None
            step.progress = 0.0
            step.error_code = None
            step.error_message = None
            step.error_details_json = None
            session.flush()
            session.expunge(step)
            return step

    def finish_step(
        self,
        step_id: str,
        *,
        status: StepStatus,
        output_artifact_ids: list[str] | None = None,
        error: LinguaError | None = None,
    ) -> None:
        with self.database.session() as session:
            step = session.get(StepRun, step_id)
            if step is None:
                raise LinguaError(ErrorCode.NOT_FOUND, "Step not found")
            ensure_step_transition(step.status, status)
            step.status = status
            step.ended_at = utcnow()
            step.progress = (
                1.0
                if status
                in {
                    StepStatus.SUCCEEDED,
                    StepStatus.PARTIALLY_SUCCEEDED,
                }
                else step.progress
            )
            if output_artifact_ids is not None:
                step.output_artifact_ids_json = json.dumps(output_artifact_ids)
            step.error_code = error.code if error else None
            step.error_message = self._redact_text(error.message) if error else None
            step.error_details_json = (
                json.dumps(self.redact_for_persistence(error.details or {}), ensure_ascii=False)
                if error
                else None
            )

    def set_progress(self, job_id: str, step_id: str, step_progress: float) -> None:
        bounded = max(0.0, min(step_progress, 1.0))
        with self.database.session() as session:
            step = session.get(StepRun, step_id)
            job = session.get(Job, job_id)
            if step is None or job is None:
                raise LinguaError(ErrorCode.NOT_FOUND, "Job or Step not found")
            step.progress = bounded
            pipeline = get_pipeline(job.pipeline_key)
            completed = 0.0
            for candidate in session.scalars(select(StepRun).where(StepRun.job_id == job_id)):
                definition = pipeline.steps[candidate.step_order]
                if candidate.status in {
                    StepStatus.SUCCEEDED,
                    StepStatus.PARTIALLY_SUCCEEDED,
                }:
                    completed += definition.weight
                elif candidate.id == step_id:
                    completed += definition.weight * bounded
            job.progress = min(completed, 1.0)
            job.updated_at = utcnow()

    def finish_job(
        self,
        job_id: str,
        *,
        status: JobStatus,
        error: LinguaError | None = None,
    ) -> None:
        with self.database.session() as session:
            job = session.get(Job, job_id)
            if job is None:
                raise LinguaError(ErrorCode.NOT_FOUND, "Job not found")
            ensure_job_transition(job.status, status)
            job.status = status
            job.runner_token = None
            job.control_request = None
            job.ended_at = utcnow()
            if status == JobStatus.SUCCEEDED:
                job.progress = 1.0
            job.error_code = error.code if error else None
            job.error_message = self._redact_text(error.message) if error else None
            job.error_details_json = (
                json.dumps(self.redact_for_persistence(error.details or {}), ensure_ascii=False)
                if error
                else None
            )
            job.updated_at = utcnow()

    def pause_running_job(self, job_id: str, step_id: str) -> None:
        with self.database.session() as session:
            job = session.get(Job, job_id)
            step = session.get(StepRun, step_id)
            if job is None or step is None:
                raise LinguaError(ErrorCode.NOT_FOUND, "Job or Step not found")
            ensure_step_transition(step.status, StepStatus.PAUSED)
            step.status = StepStatus.PAUSED
            step.ended_at = utcnow()
            ensure_job_transition(job.status, JobStatus.PAUSED)
            job.status = JobStatus.PAUSED
            job.control_request = None
            job.runner_token = None
            job.updated_at = utcnow()

    def pause_between_steps(self, job_id: str) -> None:
        with self.database.session() as session:
            job = session.get(Job, job_id)
            if job is None:
                raise LinguaError(ErrorCode.NOT_FOUND, "Job not found")
            ensure_job_transition(job.status, JobStatus.PAUSED)
            job.status = JobStatus.PAUSED
            job.control_request = None
            job.runner_token = None
            job.updated_at = utcnow()

    def cancel_running_job(self, job_id: str, step_id: str) -> None:
        with self.database.session() as session:
            job = session.get(Job, job_id)
            step = session.get(StepRun, step_id)
            if job is None or step is None:
                raise LinguaError(ErrorCode.NOT_FOUND, "Job or Step not found")
            if step.status == StepStatus.RUNNING:
                ensure_step_transition(step.status, StepStatus.CANCELLED)
                step.status = StepStatus.CANCELLED
                step.ended_at = utcnow()
                step.error_code = ErrorCode.CANCELLED
                step.error_message = "Step cancelled at a safe boundary"
            for pending in session.scalars(
                select(StepRun).where(
                    StepRun.job_id == job_id,
                    StepRun.status.in_([StepStatus.PENDING, StepStatus.PAUSED]),
                )
            ):
                ensure_step_transition(pending.status, StepStatus.CANCELLED)
                pending.status = StepStatus.CANCELLED
                pending.ended_at = utcnow()
                pending.error_code = ErrorCode.CANCELLED
                pending.error_message = "Step did not run because the Job was cancelled"
            if job.status == JobStatus.RUNNING:
                ensure_job_transition(job.status, JobStatus.CANCELLING)
                job.status = JobStatus.CANCELLING
            ensure_job_transition(job.status, JobStatus.CANCELLED)
            job.status = JobStatus.CANCELLED
            job.control_request = None
            job.runner_token = None
            job.ended_at = utcnow()
            job.error_code = ErrorCode.CANCELLED
            job.error_message = "Job cancelled at a safe boundary"

    def cancel_between_steps(self, job_id: str) -> None:
        with self.database.session() as session:
            job = session.get(Job, job_id)
            if job is None:
                raise LinguaError(ErrorCode.NOT_FOUND, "Job not found")
            if job.status == JobStatus.RUNNING:
                ensure_job_transition(job.status, JobStatus.CANCELLING)
                job.status = JobStatus.CANCELLING
            for pending in session.scalars(
                select(StepRun).where(
                    StepRun.job_id == job_id,
                    StepRun.status.in_([StepStatus.PENDING, StepStatus.PAUSED]),
                )
            ):
                ensure_step_transition(pending.status, StepStatus.CANCELLED)
                pending.status = StepStatus.CANCELLED
                pending.ended_at = utcnow()
                pending.error_code = ErrorCode.CANCELLED
                pending.error_message = "Step did not run because the Job was cancelled"
            ensure_job_transition(job.status, JobStatus.CANCELLED)
            job.status = JobStatus.CANCELLED
            job.control_request = None
            job.runner_token = None
            job.ended_at = utcnow()
            job.error_code = ErrorCode.CANCELLED
            job.error_message = "Job cancelled at a safe boundary"

    def add_log(
        self,
        step_id: str,
        level: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        with self.database.session() as session:
            step = session.get(StepRun, step_id)
            if step is None:
                raise LinguaError(ErrorCode.NOT_FOUND, "Step not found")
            self._append_log(session, step, level, message, details or {})

    def _append_log(
        self,
        session: Any,
        step: StepRun,
        level: str,
        message: str,
        details: dict[str, Any],
    ) -> None:
        session.add(
            StepLog(
                job_id=step.job_id,
                step_run_id=step.id,
                level=level.upper(),
                message=self._redact_text(message),
                details_json=json.dumps(self.redact_for_persistence(details), ensure_ascii=False),
            )
        )

    def pipeline_catalog(self) -> list[dict[str, object]]:
        return [preset.public() for preset in PIPELINES.values()]

    def provider_statuses(self) -> list[dict[str, Any]]:
        return [self.redact_for_persistence(status) for status in self.providers.statuses()]

    def adapter_statuses(self) -> list[dict[str, Any]]:
        return [self.redact_for_persistence(status) for status in self.adapters.statuses()]

    def system_summary(self) -> dict[str, Any]:
        with self.database.session() as session:
            projects = session.scalar(select(func.count()).select_from(Project)) or 0
            active_jobs = (
                session.scalar(
                    select(func.count())
                    .select_from(Job)
                    .where(
                        Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.CANCELLING])
                    )
                )
                or 0
            )
            recent = session.scalars(select(Job).order_by(Job.requested_at.desc()).limit(10)).all()
        return {
            "version": __version__,
            "project_count": projects,
            "active_job_count": active_jobs,
            "recent_jobs": [self._job_summary(job) for job in recent],
            "data_dir": self._redact_text(str(self.settings.data_dir)),
            "bind_default": "127.0.0.1",
            "limits": {
                "max_upload_bytes": self.settings.max_upload_bytes,
                "max_archive_files": self.settings.max_archive_files,
                "max_archive_uncompressed_bytes": self.settings.max_archive_uncompressed_bytes,
                "max_archive_member_bytes": self.settings.max_archive_member_bytes,
                "max_archive_compression_ratio": self.settings.max_archive_compression_ratio,
                "max_archive_path_depth": self.settings.max_archive_path_depth,
            },
        }

    def health(self) -> dict[str, Any]:
        try:
            self.database.check()
            database_status = "ok"
        except Exception:
            database_status = "error"
        return {
            "status": "ok" if database_status == "ok" else "error",
            "version": __version__,
            "database": database_status,
        }

    def doctor(self, *, port: int | None = None) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        try:
            self.settings.ensure_directories()
            with tempfile.NamedTemporaryFile(dir=self.settings.data_dir, delete=True):
                pass
            checks.append(
                {"name": "data_directory", "ok": True, "detail": str(self.settings.data_dir)}
            )
        except OSError as exc:
            checks.append({"name": "data_directory", "ok": False, "detail": type(exc).__name__})
        try:
            self.database.check()
            checks.append(
                {"name": "database", "ok": True, "detail": str(self.settings.database_path)}
            )
        except Exception as exc:
            checks.append({"name": "database", "ok": False, "detail": type(exc).__name__})
        docker_path = shutil.which("docker")
        checks.append(
            {
                "name": "external_command:docker",
                "ok": docker_path is not None,
                "detail": docker_path or "not found (optional for local use)",
                "optional": True,
            }
        )
        if docker_path:
            try:
                docker_probe = subprocess.run(  # noqa: S603
                    [docker_path, "version", "--format", "{{.Server.Version}}"],
                    capture_output=True,
                    check=False,
                    text=True,
                    timeout=3,
                )
                docker_detail = (docker_probe.stdout or docker_probe.stderr).strip()
                checks.append(
                    {
                        "name": "docker_engine",
                        "ok": docker_probe.returncode == 0,
                        "detail": self._redact_text(docker_detail[:500])
                        or f"docker exited with status {docker_probe.returncode}",
                        "optional": True,
                    }
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                checks.append(
                    {
                        "name": "docker_engine",
                        "ok": False,
                        "detail": f"Docker Engine probe failed: {type(exc).__name__}",
                        "optional": True,
                    }
                )
        selected_port = port or self.settings.port
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                occupied = probe.connect_ex((self.settings.host, selected_port)) == 0
            checks.append(
                {
                    "name": "port",
                    "ok": not occupied,
                    "detail": f"{self.settings.host}:{selected_port} "
                    + ("is occupied" if occupied else "is available"),
                }
            )
        except OSError as exc:
            checks.append(
                {
                    "name": "port",
                    "ok": False,
                    "detail": f"could not inspect port: {type(exc).__name__}",
                    "optional": True,
                }
            )
        for provider in self.provider_statuses():
            checks.append(
                {
                    "name": f"provider:{provider['id']}",
                    "ok": bool(provider["configured"]),
                    "detail": "configured" if provider["configured"] else "not configured",
                    "optional": provider["id"] != "mock",
                }
            )
        for adapter in self.adapter_statuses():
            checks.append(
                {
                    "name": f"adapter:{adapter['id']}",
                    "ok": bool(adapter["health"]["available"]),
                    "detail": adapter["health"]["message"],
                    "optional": adapter["id"] != "mock-manga",
                }
            )
            if adapter["id"] != "mock-manga":
                checks.append(
                    {
                        "name": f"external_assets:{adapter['id']}",
                        "ok": bool(adapter["health"]["available"]),
                        "detail": (
                            "Models and fonts are supplied by the separately operated upstream; "
                            "LinguaSpindle does not bundle or silently install them"
                        ),
                        "optional": True,
                    }
                )
        required_ok = all(check["ok"] for check in checks if not check.get("optional"))
        return {
            "ok": required_ok,
            "version": __version__,
            "platform": platform.platform(),
            "python": platform.python_version(),
            "checks": checks,
        }

    def validate_archive_member(self, name: str) -> PurePosixPath:
        if (
            not name
            or "\x00" in name
            or "\\" in name
            or any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in name)
        ):
            raise LinguaError(ErrorCode.INVALID_FORMAT, "Archive contains an unsafe path")
        member = PurePosixPath(name)
        if (
            member.is_absolute()
            or any(part in {"", ".", ".."} for part in member.parts)
            or (member.parts and ":" in member.parts[0])
        ):
            raise LinguaError(ErrorCode.INVALID_FORMAT, "Archive contains an unsafe path")
        if len(member.parts) > self.settings.max_archive_path_depth:
            raise LinguaError(
                ErrorCode.ARCHIVE_LIMIT_EXCEEDED,
                "Archive member path exceeds the configured depth limit",
                {
                    "member": name,
                    "depth": len(member.parts),
                    "limit": self.settings.max_archive_path_depth,
                },
            )
        return member
