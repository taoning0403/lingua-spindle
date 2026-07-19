"""SQLAlchemy persistence models.

The schema is instance-scoped by design. There are deliberately no identity or ownership models.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20), index=True)
    source_language: Mapped[str] = mapped_column(String(40))
    target_language: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    sources: Mapped[list[Source]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    jobs: Mapped[list[Job]] = relationship(back_populates="project", cascade="all, delete-orphan")
    artifacts: Mapped[list[Artifact]] = relationship(
        back_populates="project", cascade="all, delete-orphan", foreign_keys="Artifact.project_id"
    )


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    step_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("step_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(80), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(120))
    size: Mapped[int] = mapped_column(Integer)
    checksum: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship(back_populates="artifacts", foreign_keys=[project_id])


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(40))
    original_name: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(120))
    size: Mapped[int] = mapped_column(Integer)
    checksum: Mapped[str] = mapped_column(String(64))
    artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship(back_populates="sources")
    artifact: Mapped[Artifact] = relationship(foreign_keys=[artifact_id])


class TranslationProfile(Base):
    __tablename__ = "translation_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    source_language: Mapped[str] = mapped_column(String(40))
    target_language: Mapped[str] = mapped_column(String(40))
    provider_id: Mapped[str] = mapped_column(String(80), default="mock")
    model: Mapped[str] = mapped_column(String(160), default="mock-v1")
    style: Mapped[str] = mapped_column(Text, default="Preserve tone and paragraph structure.")
    context_strategy: Mapped[str] = mapped_column(String(80), default="independent-segments")
    prompt_template: Mapped[str] = mapped_column(
        Text,
        default=(
            "Translate from {source_language} to {target_language}. "
            "Preserve dialogue, paragraph structure, names, and punctuation.\n\n{text}"
        ),
    )
    prompt_version: Mapped[str] = mapped_column(String(40), default="v1")
    batch_size: Mapped[int] = mapped_column(Integer, default=8)
    model_parameters_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ProviderConfig(Base):
    __tablename__ = "provider_configs"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    base_url: Mapped[str] = mapped_column(String(500), default="")
    model: Mapped[str] = mapped_column(String(160), default="")
    timeout_seconds: Mapped[float] = mapped_column(Float, default=60.0)
    concurrency_limit: Mapped[int] = mapped_column(Integer, default=2)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    translation_profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("translation_profiles.id", ondelete="SET NULL"), nullable=True
    )
    pipeline_key: Mapped[str] = mapped_column(String(80))
    pipeline_version: Mapped[str] = mapped_column(String(40), default="1")
    provider_id: Mapped[str] = mapped_column(String(80), default="mock")
    adapter_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(40), index=True, default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    control_request: Mapped[str | None] = mapped_column(String(40), nullable=True)
    profile_snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    runner_token: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_details_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    project: Mapped[Project] = relationship(back_populates="jobs")
    profile: Mapped[TranslationProfile | None] = relationship(foreign_keys=[translation_profile_id])
    steps: Mapped[list[StepRun]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="StepRun.step_order"
    )


class StepRun(Base):
    __tablename__ = "step_runs"
    __table_args__ = (UniqueConstraint("job_id", "step_key", name="uq_step_job_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    step_key: Mapped[str] = mapped_column(String(80))
    step_order: Mapped[int] = mapped_column(Integer)
    capability: Mapped[str] = mapped_column(String(80))
    executor_type: Mapped[str] = mapped_column(String(40))
    executor_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(40), index=True, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    input_artifact_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    output_artifact_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    config_snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_details_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    job: Mapped[Job] = relationship(back_populates="steps")
    logs: Mapped[list[StepLog]] = relationship(
        back_populates="step", cascade="all, delete-orphan", order_by="StepLog.id"
    )


class StepLog(Base):
    __tablename__ = "step_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    step_run_id: Mapped[str] = mapped_column(
        ForeignKey("step_runs.id", ondelete="CASCADE"), index=True
    )
    level: Mapped[str] = mapped_column(String(20), default="INFO")
    message: Mapped[str] = mapped_column(Text)
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    step: Mapped[StepRun] = relationship(back_populates="logs")


class TranslationSegment(Base):
    __tablename__ = "translation_segments"
    __table_args__ = (UniqueConstraint("job_id", "sequence", name="uq_segment_job_sequence"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    source_text: Mapped[str] = mapped_column(Text)
    translated_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    profile_snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    prompt_version: Mapped[str] = mapped_column(String(40), default="v1")
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class QaFinding(Base):
    __tablename__ = "qa_findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    segment_id: Mapped[str | None] = mapped_column(
        ForeignKey("translation_segments.id", ondelete="CASCADE"), nullable=True, index=True
    )
    category: Mapped[str] = mapped_column(String(80))
    severity: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
