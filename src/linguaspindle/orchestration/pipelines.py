"""Versioned code-defined Pipeline Presets."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from ..errors import ErrorCode, LinguaError


@dataclass(frozen=True, slots=True)
class StepDefinition:
    key: str
    capability: str
    executor_type: str
    weight: float


@dataclass(frozen=True, slots=True)
class PipelinePreset:
    key: str
    display_name: str
    project_kind: str
    source_kinds: tuple[str, ...]
    version: str
    steps: tuple[StepDefinition, ...]

    def public(self) -> dict[str, object]:
        return {
            "key": self.key,
            "display_name": self.display_name,
            "project_kind": self.project_kind,
            "source_kinds": list(self.source_kinds),
            "version": self.version,
            "steps": [asdict(step) for step in self.steps],
        }


NOVEL_TXT = PipelinePreset(
    key="novel_txt_v1",
    display_name="TXT novel translation",
    project_kind="novel",
    source_kinds=("txt",),
    version="1",
    steps=(
        StepDefinition("detect_encoding", "novel_parse", "internal", 0.08),
        StepDefinition("extract_text", "novel_parse", "internal", 0.07),
        StepDefinition("segment_text", "text_segment", "internal", 0.15),
        StepDefinition("translate_text", "text_translate", "provider", 0.50),
        StepDefinition("quality_check", "translation_qa", "internal", 0.10),
        StepDefinition("export_novel", "novel_export", "internal", 0.10),
    ),
)

NOVEL_EPUB = PipelinePreset(
    key="novel_epub_v1",
    display_name="EPUB novel translation",
    project_kind="novel",
    source_kinds=("epub",),
    version="1",
    steps=(
        StepDefinition("inspect_epub", "novel_parse", "internal", 0.10),
        StepDefinition("segment_epub", "text_segment", "internal", 0.20),
        StepDefinition("translate_text", "text_translate", "provider", 0.50),
        StepDefinition("quality_check", "translation_qa", "internal", 0.10),
        StepDefinition("export_epub", "epub_build", "internal", 0.10),
    ),
)

MANGA_FULL = PipelinePreset(
    key="manga_full_v1",
    display_name="External manga full pipeline",
    project_kind="manga",
    source_kinds=("cbz", "image"),
    version="1",
    steps=(
        StepDefinition("prepare_manga", "manga_import", "internal", 0.15),
        StepDefinition("translate_manga", "manga_full_pipeline", "adapter", 0.70),
        StepDefinition("export_manga", "cbz_build", "internal", 0.15),
    ),
)

PIPELINES = {preset.key: preset for preset in (NOVEL_TXT, NOVEL_EPUB, MANGA_FULL)}


def get_pipeline(key: str) -> PipelinePreset:
    try:
        return PIPELINES[key]
    except KeyError as exc:
        raise LinguaError(ErrorCode.CONFIGURATION, f"Unknown Pipeline Preset: {key}") from exc


def default_pipeline(project_kind: str, source_kind: str | None = None) -> PipelinePreset:
    """Choose deterministically; never rely on catalog insertion order."""
    if source_kind is not None:
        for preset in PIPELINES.values():
            if preset.project_kind == project_kind and source_kind in preset.source_kinds:
                return preset
        raise LinguaError(
            ErrorCode.CONFIGURATION,
            f"No Pipeline for project kind/source kind: {project_kind}/{source_kind}",
        )
    if project_kind == "novel":
        return NOVEL_TXT
    if project_kind == "manga":
        return MANGA_FULL
    raise LinguaError(ErrorCode.CONFIGURATION, f"No Pipeline for project kind: {project_kind}")
