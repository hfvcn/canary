from __future__ import annotations

import json
from pathlib import Path

import pytest

from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationSpec
from cccc.daemon.foreman.workflow_evaluation import (
    RESULT_INDEPENDENTLY_REVIEWED,
    RESULT_PASSED,
    _workflow_evaluation_result_breakdown_detail,
    _workflow_evaluation_test_stats,
    _workflow_evaluation_verification_checks,
)


WORKFLOW_ID = "wf-rv62-fl63"
COMPLETED_STATUSES = {"completed"}


class _EngineStub:
    def get_workflow_meta(self, workflow_id: str) -> None:
        assert workflow_id == WORKFLOW_ID
        return None


def test_rv62_same_worker_execution_is_not_independent(tmp_path: Path) -> None:
    workflow = _active_workflow(
        _tracked_task(_main_task(), agent_id="worker-main"),
        _tracked_task(
            _review_task(
                task_id="T-review",
                covers_tasks=["T-main"],
            ),
            agent_id="worker-main",
        ),
    )

    _, task_map = _workflow_evaluation_result_breakdown_detail(
        active_workflows=workflow,
        ledger_path=_write_ledger(tmp_path),
        engine=_EngineStub(),
        workflow_id=WORKFLOW_ID,
        completed_count=2,
        completed_statuses=COMPLETED_STATUSES,
    )

    assert task_map["T-review"] == RESULT_PASSED


def test_rv62_different_actor_completion_is_independent(tmp_path: Path) -> None:
    workflow = _active_workflow(
        _tracked_task(_main_task(), agent_id="worker-main"),
        _tracked_task(
            _review_task(
                task_id="T-review",
                depends_on=["T-main"],
            ),
        ),
    )
    ledger_path = _write_ledger(
        tmp_path,
        {
            "kind": "workflow.verification_warning",
            "data": {
                "workflow_id": WORKFLOW_ID,
                "task_id": "T-review",
                "warning_type": "completer_mismatch",
                "evidence": {
                    "assigned_agent": "review-assigned",
                    "completing_agent": "reviewer-b",
                },
            },
        },
    )

    _, task_map = _workflow_evaluation_result_breakdown_detail(
        active_workflows=workflow,
        ledger_path=ledger_path,
        engine=_EngineStub(),
        workflow_id=WORKFLOW_ID,
        completed_count=2,
        completed_statuses=COMPLETED_STATUSES,
    )

    assert task_map["T-review"] == RESULT_INDEPENDENTLY_REVIEWED


def test_rv62_missing_executor_evidence_is_not_independent(tmp_path: Path) -> None:
    workflow = _active_workflow(
        _tracked_task(_main_task(), agent_id="worker-main"),
        _tracked_task(
            _review_task(
                task_id="T-review",
                covers_tasks=["T-main"],
            ),
        ),
    )

    _, task_map = _workflow_evaluation_result_breakdown_detail(
        active_workflows=workflow,
        ledger_path=_write_ledger(tmp_path),
        engine=_EngineStub(),
        workflow_id=WORKFLOW_ID,
        completed_count=2,
        completed_statuses=COMPLETED_STATUSES,
    )

    assert task_map["T-review"] == RESULT_PASSED


def test_fl63_top_level_command_marker_is_treated_as_enabled(tmp_path: Path) -> None:
    _write_randomly_declaration(tmp_path)
    workflow = _active_workflow(
        _tracked_task(
            _task(
                "T-random-top-level",
                verification=VerificationSpec(
                    command="python -m pytest -p randomly tests/test_flow.py -q",
                ),
            ),
        ),
    )

    _, reliable, randomization, _ = _workflow_evaluation_test_stats(
        "17",
        verification_checks=_workflow_evaluation_verification_checks(workflow[WORKFLOW_ID]),
        project_root=tmp_path,
    )

    assert randomization is True
    assert reliable is True


@pytest.mark.parametrize(
    ("verification_checks", "test_output"),
    [
        (
            [
                {
                    "name": "unit-check",
                    "command": "python -m pytest --randomly-seed=123 tests/test_flow.py -q",
                }
            ],
            None,
        ),
        (
            [
                {
                    "name": "unit-check",
                    "command": "python -m pytest tests/test_flow.py -q",
                }
            ],
            "Using --randomly-seed=456\n2 passed",
        ),
    ],
)
def test_fl63_checks_command_or_output_markers_keep_stats_reliable(
    tmp_path: Path,
    verification_checks: list[dict[str, str]],
    test_output: str | None,
) -> None:
    _write_randomly_declaration(tmp_path)

    _, reliable, randomization, _ = _workflow_evaluation_test_stats(
        "17",
        verification_checks=verification_checks,
        test_output=test_output,
        project_root=tmp_path,
    )

    assert randomization is True
    assert reliable is True


def test_fl63_declared_only_without_enable_evidence_is_unreliable(tmp_path: Path) -> None:
    _write_randomly_declaration(tmp_path)

    _, reliable, randomization, _ = _workflow_evaluation_test_stats(
        "17",
        verification_checks=[
            {
                "name": "unit-check",
                "command": "python -m pytest tests/test_flow.py -q",
            }
        ],
        project_root=tmp_path,
    )

    assert randomization is None
    assert reliable is False


def _active_workflow(*tracked_tasks: dict[str, object]) -> dict[str, dict[str, object]]:
    return {
        WORKFLOW_ID: {
            "tasks": {
                str(task["task_id"]): task
                for task in tracked_tasks
            }
        }
    }


def _tracked_task(task_ref: TaskRef, *, agent_id: str = "") -> dict[str, object]:
    return {
        "task_id": task_ref.id,
        "status": "completed",
        "task_ref": task_ref,
        "agent_id": agent_id,
    }


def _main_task() -> TaskRef:
    return _task("T-main")


def _review_task(
    *,
    task_id: str,
    covers_tasks: list[str] | None = None,
    depends_on: list[str] | None = None,
) -> TaskRef:
    verification = VerificationSpec(covers_tasks=covers_tasks or [])
    return _task(
        task_id,
        role="verification",
        depends_on=depends_on or [],
        verification=verification,
    )


def _task(
    task_id: str,
    *,
    role: str = "",
    depends_on: list[str] | None = None,
    verification: VerificationSpec | None = None,
) -> TaskRef:
    return TaskRef(
        id=task_id,
        title=f"Task {task_id}",
        role=role,
        depends_on=depends_on or [],
        verification=verification,
    )


def _write_ledger(tmp_path: Path, *events: dict[str, object]) -> Path:
    ledger_path = tmp_path / "ledger.jsonl"
    content = "\n".join(json.dumps(event) for event in events)
    ledger_path.write_text(f"{content}\n" if content else "", encoding="utf-8")
    return ledger_path


def _write_randomly_declaration(project_root: Path) -> None:
    (project_root / "requirements-dev.txt").write_text(
        "pytest\npytest-randomly\n",
        encoding="utf-8",
    )
