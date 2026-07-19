"""Explicit Job and Step state machines."""

from __future__ import annotations

from enum import StrEnum

from ..errors import ErrorCode, LinguaError


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIALLY_SUCCEEDED = "partially_succeeded"


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIALLY_SUCCEEDED = "partially_succeeded"
    SKIPPED = "skipped"


TERMINAL_JOB_STATUSES = {
    JobStatus.CANCELLED,
    JobStatus.SUCCEEDED,
    JobStatus.FAILED,
    JobStatus.PARTIALLY_SUCCEEDED,
}
TERMINAL_STEP_STATUSES = {
    StepStatus.CANCELLED,
    StepStatus.SUCCEEDED,
    StepStatus.FAILED,
    StepStatus.PARTIALLY_SUCCEEDED,
    StepStatus.SKIPPED,
}

JOB_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.QUEUED: {JobStatus.RUNNING, JobStatus.PAUSED, JobStatus.CANCELLED},
    JobStatus.RUNNING: {
        JobStatus.PAUSED,
        JobStatus.CANCELLING,
        JobStatus.SUCCEEDED,
        JobStatus.FAILED,
        JobStatus.PARTIALLY_SUCCEEDED,
    },
    JobStatus.PAUSED: {JobStatus.QUEUED, JobStatus.CANCELLED},
    JobStatus.CANCELLING: {JobStatus.CANCELLED, JobStatus.FAILED},
    JobStatus.CANCELLED: set(),
    JobStatus.SUCCEEDED: set(),
    JobStatus.FAILED: {JobStatus.QUEUED},
    JobStatus.PARTIALLY_SUCCEEDED: {JobStatus.QUEUED},
}

STEP_TRANSITIONS: dict[StepStatus, set[StepStatus]] = {
    StepStatus.PENDING: {StepStatus.RUNNING, StepStatus.CANCELLED, StepStatus.SKIPPED},
    StepStatus.RUNNING: {
        StepStatus.PAUSED,
        StepStatus.CANCELLING,
        StepStatus.CANCELLED,
        StepStatus.SUCCEEDED,
        StepStatus.FAILED,
        StepStatus.PARTIALLY_SUCCEEDED,
    },
    StepStatus.PAUSED: {StepStatus.PENDING, StepStatus.CANCELLED},
    StepStatus.CANCELLING: {StepStatus.CANCELLED, StepStatus.FAILED},
    StepStatus.CANCELLED: {StepStatus.PENDING},
    StepStatus.SUCCEEDED: {StepStatus.PENDING},
    StepStatus.FAILED: {StepStatus.PENDING},
    StepStatus.PARTIALLY_SUCCEEDED: {StepStatus.PENDING},
    StepStatus.SKIPPED: {StepStatus.PENDING},
}


def ensure_job_transition(current: str, target: str) -> None:
    current_status = JobStatus(current)
    target_status = JobStatus(target)
    if target_status not in JOB_TRANSITIONS[current_status]:
        raise LinguaError(
            ErrorCode.INVALID_STATE,
            f"Job cannot transition from {current_status.value} to {target_status.value}",
        )


def ensure_step_transition(current: str, target: str) -> None:
    current_status = StepStatus(current)
    target_status = StepStatus(target)
    if target_status not in STEP_TRANSITIONS[current_status]:
        raise LinguaError(
            ErrorCode.INVALID_STATE,
            f"Step cannot transition from {current_status.value} to {target_status.value}",
        )
