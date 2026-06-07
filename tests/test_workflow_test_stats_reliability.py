from __future__ import annotations

from pathlib import Path

import pytest

from cccc.daemon.foreman.workflow_orchestrator import (
    TEST_COUNT_COLLECTION_FAILED,
    TEST_COUNT_UNRELIABLE_TEXT,
    WorkflowOrchestrator,
)


@pytest.fixture
def orchestrator(tmp_path: Path) -> WorkflowOrchestrator:
    return WorkflowOrchestrator(project_root=tmp_path, group_id="g-test-stats")


def test_unreliable_collection_degrades_only_test_count(
    orchestrator: WorkflowOrchestrator,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        orchestrator,
        "_collect_actual_test_count",
        lambda: TEST_COUNT_COLLECTION_FAILED,
    )

    orchestrator._write_workflow_evaluation(
        workflow_id="wf-stats-failed",
        completed_count=2,
        failed_count=0,
        total=2,
        summary="summary",
    )

    content = (tmp_path / "WORKFLOW_EVALUATION.md").read_text(encoding="utf-8")

    assert "- Completed: 2" in content
    assert "- Failed: 0" in content
    assert "- test_count_actual: N/A (collection failed)" in content
    assert TEST_COUNT_UNRELIABLE_TEXT in content
    assert "- test_stats_reliable: false" in content
    assert "0 failed" not in content


def test_reliable_collection_keeps_numeric_test_count(
    orchestrator: WorkflowOrchestrator,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(orchestrator, "_collect_actual_test_count", lambda: "17")

    orchestrator._write_workflow_evaluation(
        workflow_id="wf-stats-ok",
        completed_count=1,
        failed_count=0,
        total=1,
        summary="summary",
    )

    content = (tmp_path / "WORKFLOW_EVALUATION.md").read_text(encoding="utf-8")

    assert "- test_count_actual: 17" in content
    assert "- test_stats_reliable: true" in content
    assert "| test_count_actual | 17 |" in content


def test_test_stats_reliable_helper_marks_collection_failure_unreliable(
    orchestrator: WorkflowOrchestrator,
) -> None:
    assert orchestrator._test_stats_reliable("17")
    assert not orchestrator._test_stats_reliable(TEST_COUNT_COLLECTION_FAILED)
