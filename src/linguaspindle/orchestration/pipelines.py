"""Versioned code-defined v0.1.0 Pipeline Presets."""

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
    version: str
    steps: tuple[StepDefinition, ...]

    def public(self) -> dict[str, object]:
        return {
            "key": self.key,
            "display_name": self.display_name,
            "project_kind": self.project_kind,
            "version": self.version,
            "steps": [asdict(step) for step in self.steps],
        }


NOVEL_TXT = PipelinePreset(
    key="novel_txt_v1",
    display_name="TXT novel translation",
    project_kind="novel",
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

MANGA_FULL = PipelinePreset(
    key="manga_full_v1",
    display_name="External manga full pipeline",
    project_kind="manga",
    version="1",
    steps=(
        StepDefinition("prepare_manga", "manga_import", "internal", 0.15),
        StepDefinition("translate_manga", "manga_full_pipeline", "adapter", 0.70),
        StepDefinition("export_manga", "cbz_build", "internal", 0.15),
    ),
)

PIPELINES = {preset.key: preset for preset in (NOVEL_TXT, MANGA_FULL)}


def get_pipeline(key: str) -> PipelinePreset:
    try:
        return PIPELINES[key]
    except KeyError as exc:
        raise LinguaError(ErrorCode.CONFIGURATION, f"Unknown Pipeline Preset: {key}") from exc


def default_pipeline(project_kind: str) -> PipelinePreset:
    for preset in PIPELINES.values():
        if preset.project_kind == project_kind:
            return preset
    raise LinguaError(ErrorCode.CONFIGURATION, f"No Pipeline for project kind: {project_kind}")
