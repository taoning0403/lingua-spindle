from __future__ import annotations

import pytest

from linguaspindle.errors import ErrorCode, LinguaError
from linguaspindle.orchestration.state import (
    JobStatus,
    StepStatus,
    ensure_job_transition,
    ensure_step_transition,
)


def test_job_state_machine_accepts_documented_controls() -> None:
    ensure_job_transition(JobStatus.QUEUED, JobStatus.RUNNING)
    ensure_job_transition(JobStatus.RUNNING, JobStatus.PAUSED)
    ensure_job_transition(JobStatus.PAUSED, JobStatus.QUEUED)
    ensure_job_transition(JobStatus.RUNNING, JobStatus.CANCELLING)
    ensure_job_transition(JobStatus.CANCELLING, JobStatus.CANCELLED)


def test_terminal_success_cannot_restart() -> None:
    with pytest.raises(LinguaError) as caught:
        ensure_job_transition(JobStatus.SUCCEEDED, JobStatus.RUNNING)
    assert caught.value.code == ErrorCode.INVALID_STATE


def test_step_retry_transition_is_explicit() -> None:
    ensure_step_transition(StepStatus.FAILED, StepStatus.PENDING)
    ensure_step_transition(StepStatus.PARTIALLY_SUCCEEDED, StepStatus.PENDING)
