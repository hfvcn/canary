from __future__ import annotations

import json
from pathlib import Path

import pytest

from cccc.contracts.v1.ralph_ipc import TaskRef
from cccc.daemon.foreman.workflow_orchestrator import (
    RESULT_ASSUMPTION_BASED,
    RESULT_INDEPENDENTLY_REVIEWED,
    RESULT_OVERRIDDEN,
    RESULT_PASSED,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_COMPLETED_BY_OVERRIDE,
    WorkflowOrchestrator,
)


WORKFLOW_ID = "wf-result-classification"
RESULT_ORDER = (
    RESULT_PASSED,
    RESULT_OVERRIDDEN,
    RESULT_ASSUMPTION_BASED,
    RESULT_INDEPENDENTLY_REVIEWED,
)


@pytest.fixture
def orchestrator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> WorkflowOrchestrator:
    instance = WorkflowOrchestrator(project_root=tmp_path, group_id="g-result-classification")
    monkeypatch.setattr(instance, "_collect_actual_test_count", lambda: "17")
    return instance


def test_pure_passed_results_keep_test_stats_reliable(
    orchestrator: WorkflowOrchestrator,
    tmp_path: Path,
) -> None:
    _track_result(orchestrator, _task("T-passed"), status=TASK_STATUS_COMPLETED)

    content = _write_evaluation(orchestrator, tmp_path)

    assert _summary_breakdown({RESULT_PASSED: 1}) in content
    assert "- test_stats_reliable: true" in content


def test_foreman_override_result_is_unreliable(
    orchestrator: WorkflowOrchestrator,
    tmp_path: Path,
) -> None:
    task = _task("T-overridden")
    orchestrator.engine.register_task(task, WORKFLOW_ID)
    orchestrator.engine.foreman_override_task(
        task.id,
        "accepted by foreman",
        {"evidence": "manual verification"},
    )
    _track_result(orchestrator, task, status=TASK_STATUS_COMPLETED_BY_OVERRIDE)

    content = _write_evaluation(orchestrator, tmp_path)

    assert _summary_breakdown({RESULT_OVERRIDDEN: 1}) in content
    assert "- test_stats_reliable: false" in content


def test_suppress_instances_make_result_assumption_based(
    orchestrator: WorkflowOrchestrator,
    tmp_path: Path,
) -> None:
    plan_path = _write_plan_with_suppress_instances(tmp_path)
    orchestrator.engine.set_workflow_meta(WORKFLOW_ID, plan_path=str(plan_path))
    _track_result(orchestrator, _task("T-assumption"), status=TASK_STATUS_COMPLETED)

    content = _write_evaluation(orchestrator, tmp_path)

    assert _summary_breakdown({RESULT_ASSUMPTION_BASED: 1}) in content
    assert "- test_stats_reliable: false" in content


def test_independent_reviewer_result_remains_reliable(
    orchestrator: WorkflowOrchestrator,
    tmp_path: Path,
) -> None:
    task = _task("T-reviewer", role="verification")
    _track_result(orchestrator, task, status=TASK_STATUS_COMPLETED)

    content = _write_evaluation(orchestrator, tmp_path)

    assert _summary_breakdown({RESULT_INDEPENDENTLY_REVIEWED: 1}) in content
    assert "- test_stats_reliable: true" in content


def _task(task_id: str, *, role: str = "", verification_mode: str = "ralph") -> TaskRef:
    return TaskRef(
        id=task_id,
        title=f"Task {task_id}",
        role=role,
        verification_mode=verification_mode,
    )


def _track_result(
    orchestrator: WorkflowOrchestrator,
    task: TaskRef,
    *,
    status: str,
) -> None:
    orchestrator._track_task_ref(WORKFLOW_ID, task, status=status)


def _write_evaluation(
    orchestrator: WorkflowOrchestrator,
    project_root: Path,
) -> str:
    orchestrator._write_workflow_evaluation(
        workflow_id=WORKFLOW_ID,
        completed_count=1,
        failed_count=0,
        total=1,
        summary="summary",
    )
    return (project_root / "WORKFLOW_EVALUATION.md").read_text(encoding="utf-8")


def _summary_breakdown(overrides: dict[str, int]) -> str:
    counts = {classification: 0 for classification in RESULT_ORDER}
    counts.update(overrides)
    rendered = ", ".join(
        f"{classification}={counts[classification]}"
        for classification in RESULT_ORDER
    )
    return f"- result_breakdown: {rendered}"


def _write_plan_with_suppress_instances(project_root: Path) -> Path:
    plan_path = project_root / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "tasks": [{"id": "T-assumption", "title": "Assumption task"}],
                "suppress_instances": [{"code": "W_TEST_SUPPRESSED"}],
            }
        ),
        encoding="utf-8",
    )
    return plan_path
