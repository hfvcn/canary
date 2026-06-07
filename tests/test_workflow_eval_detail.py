from __future__ import annotations

from pathlib import Path

import pytest

from cccc.contracts.v1.ralph_ipc import TaskRef
from cccc.daemon.foreman.workflow_evaluation import (
    RESULT_INDEPENDENTLY_REVIEWED,
    RESULT_OVERRIDDEN,
    RESULT_PASSED,
    _classify_workflow_result_task,
    _classify_workflow_result_tasks,
    _classify_workflow_result_tasks_detail,
    _format_task_classification_table,
)
from cccc.daemon.foreman.workflow_orchestrator import (
    TASK_STATUS_COMPLETED,
    WorkflowOrchestrator,
)


def test_classify_workflow_result_tasks_detail_matches_breakdown() -> None:
    result_tasks = [
        _tracked_task("T-passed", task_ref=_task_ref("T-passed")),
        _tracked_task("T-override", task_ref=_task_ref("T-override")),
        _tracked_task("T-review", task_ref=_task_ref("T-review", role="verification")),
    ]

    expected = _classify_workflow_result_tasks(
        result_tasks,
        override_task_ids={"T-override"},
        suppress_instances_present=False,
    )
    breakdown, _ = _classify_workflow_result_tasks_detail(
        result_tasks,
        override_task_ids={"T-override"},
        suppress_instances_present=False,
    )

    assert breakdown == expected


def test_classify_workflow_result_tasks_detail_returns_task_map() -> None:
    result_tasks = [
        _tracked_task("T-passed", task_ref=_task_ref("T-passed")),
        _tracked_task("T-override", task_ref=_task_ref("T-override")),
        _tracked_task("T-review", task_ref=_task_ref("T-review", role="verification")),
    ]

    _, task_map = _classify_workflow_result_tasks_detail(
        result_tasks,
        override_task_ids={"T-override"},
        suppress_instances_present=False,
    )

    assert task_map == {
        "T-passed": RESULT_PASSED,
        "T-override": RESULT_OVERRIDDEN,
        "T-review": RESULT_INDEPENDENTLY_REVIEWED,
    }


def test_format_task_classification_table_sorts_rows() -> None:
    table = _format_task_classification_table(
        {
            "T-b": RESULT_PASSED,
            "T-a": RESULT_OVERRIDDEN,
        }
    )

    assert table == [
        "| task_id | classification |",
        "|---------|----------------|",
        f"| T-a | {RESULT_OVERRIDDEN} |",
        f"| T-b | {RESULT_PASSED} |",
    ]


def test_independently_reviewed_tasks_appear_in_task_map() -> None:
    tracked = _tracked_task("T-review", task_ref=_task_ref("T-review", verification_mode="challenge"))

    classification = _classify_workflow_result_task(
        tracked,
        override_task_ids=set(),
        suppress_instances_present=False,
    )
    _, task_map = _classify_workflow_result_tasks_detail(
        [tracked],
        override_task_ids=set(),
        suppress_instances_present=False,
    )

    assert classification == RESULT_INDEPENDENTLY_REVIEWED
    assert task_map["T-review"] == RESULT_INDEPENDENTLY_REVIEWED


def test_write_workflow_evaluation_includes_task_classification_detail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrator = WorkflowOrchestrator(project_root=tmp_path, group_id="g-workflow-eval-detail")
    monkeypatch.setattr(orchestrator, "_collect_actual_test_count", lambda: "17")
    task_ref = _task_ref("T-review", role="verification")

    orchestrator._track_task_ref("wf-workflow-eval-detail", task_ref, status=TASK_STATUS_COMPLETED)
    orchestrator._write_workflow_evaluation(
        workflow_id="wf-workflow-eval-detail",
        completed_count=1,
        failed_count=0,
        total=1,
        summary="summary",
    )

    content = (tmp_path / "WORKFLOW_EVALUATION.md").read_text(encoding="utf-8")

    assert "### 任务分类明细" in content
    assert "| task_id | classification |" in content
    assert f"| T-review | {RESULT_INDEPENDENTLY_REVIEWED} |" in content


def _tracked_task(task_id: str, *, task_ref: TaskRef) -> dict[str, object]:
    return {
        "task_id": task_id,
        "task_ref": task_ref,
    }


def _task_ref(
    task_id: str,
    *,
    role: str = "",
    verification_mode: str = "ralph",
) -> TaskRef:
    return TaskRef(
        id=task_id,
        title=f"Task {task_id}",
        role=role,
        verification_mode=verification_mode,
    )
