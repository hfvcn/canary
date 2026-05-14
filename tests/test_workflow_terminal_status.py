"""Tests for workflow terminal status summarization."""

from __future__ import annotations

from cccc.daemon.foreman.progress_report import ProgressReporter
from cccc.ports.im.templates.progress_card import ProgressStatus, TaskInfo


def _reporter_with_tasks(statuses: tuple[ProgressStatus, ...]) -> ProgressReporter:
    reporter = ProgressReporter(chat_id="oc_test_chat")
    reporter.init_workflow("wf-terminal")
    state = reporter.get_state()
    assert state is not None
    state.tasks = {
        f"T{index}": TaskInfo(
            id=f"T{index}",
            title=f"Task {index}",
            status=status,
        )
        for index, status in enumerate(statuses, start=1)
    }
    return reporter


def test_all_completed() -> None:
    reporter = _reporter_with_tasks((
        ProgressStatus.COMPLETED,
        ProgressStatus.COMPLETED,
    ))

    summary = reporter.summarize_progress()

    assert summary["status"] == "completed"


def test_some_failed_no_running_pending() -> None:
    reporter = _reporter_with_tasks((
        ProgressStatus.COMPLETED,
        ProgressStatus.FAILED,
        ProgressStatus.FAILED,
    ))

    summary = reporter.summarize_progress()

    assert summary["status"] == "failed"


def test_has_running() -> None:
    reporter = _reporter_with_tasks((
        ProgressStatus.COMPLETED,
        ProgressStatus.RUNNING,
        ProgressStatus.FAILED,
    ))

    summary = reporter.summarize_progress()

    assert summary["status"] == "running"


def test_has_pending() -> None:
    reporter = _reporter_with_tasks((
        ProgressStatus.COMPLETED,
        ProgressStatus.PENDING,
        ProgressStatus.FAILED,
    ))

    summary = reporter.summarize_progress()

    assert summary["status"] == "running"


def test_no_state() -> None:
    reporter = ProgressReporter(chat_id="oc_test_chat")

    summary = reporter.summarize_progress()

    assert summary["status"] == "idle"


def test_mixed_some_completed_some_running() -> None:
    reporter = _reporter_with_tasks((
        ProgressStatus.COMPLETED,
        ProgressStatus.RUNNING,
    ))

    summary = reporter.summarize_progress()

    assert summary["status"] == "running"
