from __future__ import annotations

from pathlib import Path

import pytest

from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationSpec
from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator


WORKFLOW_ID = "wf-randomization"


@pytest.fixture
def orchestrator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> WorkflowOrchestrator:
    instance = WorkflowOrchestrator(project_root=tmp_path, group_id="g-randomization")
    monkeypatch.setattr(instance, "_collect_actual_test_count", lambda: "17")
    return instance


def test_randomized_check_with_pytest_randomly_flag_verifies_randomization(
    orchestrator: WorkflowOrchestrator,
    tmp_path: Path,
) -> None:
    _track_check(
        orchestrator,
        name="permission-matrix-randomized",
        command="python -m pytest -p randomly tests/test_permissions.py -q",
    )

    content = _write_evaluation(orchestrator, tmp_path)

    assert "- randomization_verified: true" in content
    assert "- test_stats_reliable: true" in content


def test_randomized_check_without_randomization_flag_is_unverified(
    orchestrator: WorkflowOrchestrator,
    tmp_path: Path,
) -> None:
    _track_check(
        orchestrator,
        name="permission-matrix-randomized",
        command="python -m pytest tests/test_permissions.py -q",
    )

    content = _write_evaluation(orchestrator, tmp_path)

    assert "- randomization_verified: false" in content


def test_unverified_randomization_makes_test_stats_unreliable(
    orchestrator: WorkflowOrchestrator,
    tmp_path: Path,
) -> None:
    _track_check(
        orchestrator,
        name="permission-matrix-randomized",
        command="python -m pytest tests/test_permissions.py -q",
    )

    content = _write_evaluation(orchestrator, tmp_path)

    assert "- test_count_actual: 17" in content
    assert "- test_stats_reliable: false" in content


def test_non_randomized_check_does_not_affect_test_stats_reliability(
    orchestrator: WorkflowOrchestrator,
    tmp_path: Path,
) -> None:
    _track_check(
        orchestrator,
        name="unit-tests",
        command="python -m pytest tests/test_permissions.py -q",
    )

    content = _write_evaluation(orchestrator, tmp_path)

    assert "randomization_verified" not in content
    assert "- test_stats_reliable: true" in content


def _track_check(
    orchestrator: WorkflowOrchestrator,
    *,
    name: str,
    command: str,
) -> None:
    task = TaskRef(
        id="T-randomization",
        title="Randomization verification",
        verification=VerificationSpec(
            level="unit",
            checks=[
                {
                    "name": name,
                    "command": command,
                    "required": True,
                }
            ],
        ),
    )
    orchestrator._track_task_ref(WORKFLOW_ID, task)


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
