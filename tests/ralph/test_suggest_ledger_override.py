from __future__ import annotations

import json
from pathlib import Path

from cccc.ralph import core
from cccc.ralph.core import suggest
from cccc.ralph.models import Plan, TaskSpec


WORKFLOW_ID = "wf-ledger-override"
TASK_ID = "T1"
DOWNSTREAM_ID = "T2"


def _plan() -> Plan:
    return Plan(
        tasks=[
            TaskSpec.model_validate(
                {"id": TASK_ID, "title": "First", "claimed_paths": ["src/first.py"]}
            ),
            TaskSpec.model_validate(
                {
                    "id": DOWNSTREAM_ID,
                    "title": "Second",
                    "depends_on": [TASK_ID],
                    "claimed_paths": ["src/second.py"],
                }
            ),
        ]
    )


def _event(kind: str, task_id: str = TASK_ID) -> dict[str, object]:
    return {
        "kind": kind,
        "data": {"workflow_id": WORKFLOW_ID, "task_id": task_id},
    }


def _ledger(tmp_path: Path, events: list[dict[str, object]]) -> Path:
    ledger_path = tmp_path / "ledger.jsonl"
    ledger_path.write_text(
        "".join(f"{json.dumps(event)}\n" for event in events),
        encoding="utf-8",
    )
    return ledger_path


def _state(plan: Plan, ledger_path: Path):
    return core._plan_state_from_ledger(
        plan=plan,
        ledger_path=ledger_path,
        workflow_id=WORKFLOW_ID,
    )


def _blocked_reasons(result, task_id: str) -> list[str]:
    for blocked in result.blocked:
        if blocked.task_id == task_id:
            return blocked.reasons
    return []


def test_failed_then_verification_passed_clears_failed_and_unlocks_downstream(
    tmp_path: Path,
) -> None:
    plan = _plan()
    ledger_path = _ledger(
        tmp_path,
        [
            _event("workflow.task_failed"),
            _event("workflow.verification_passed"),
        ],
    )

    state = _state(plan, ledger_path)
    result = suggest(plan, ledger_path=ledger_path, workflow_id=WORKFLOW_ID)

    assert TASK_ID not in state.failed_task_ids
    assert TASK_ID in state.completed_task_ids
    assert result.ready == [DOWNSTREAM_ID]


def test_failed_without_later_clear_stays_failed_and_blocks_downstream(
    tmp_path: Path,
) -> None:
    plan = _plan()
    ledger_path = _ledger(tmp_path, [_event("workflow.task_failed")])

    state = _state(plan, ledger_path)
    result = suggest(plan, ledger_path=ledger_path, workflow_id=WORKFLOW_ID)

    assert state.failed_task_ids == [TASK_ID]
    assert result.ready == []
    assert f"failed_dep:{TASK_ID}" in _blocked_reasons(result, DOWNSTREAM_ID)


def test_failed_then_reported_complete_stays_failed_until_verified(
    tmp_path: Path,
) -> None:
    plan = _plan()
    ledger_path = _ledger(
        tmp_path,
        [
            _event("workflow.task_failed"),
            _event("workflow.task_reported_completed"),
        ],
    )

    state = _state(plan, ledger_path)
    result = suggest(plan, ledger_path=ledger_path, workflow_id=WORKFLOW_ID)

    assert state.failed_task_ids == [TASK_ID]
    assert f"failed_dep:{TASK_ID}" in _blocked_reasons(result, DOWNSTREAM_ID)


def test_multiple_failures_then_final_verification_passed_clears_failed(
    tmp_path: Path,
) -> None:
    plan = _plan()
    ledger_path = _ledger(
        tmp_path,
        [
            _event("workflow.task_failed"),
            _event("workflow.task_reported_completed"),
            _event("workflow.task_failed"),
            _event("workflow.verification_passed"),
        ],
    )

    state = _state(plan, ledger_path)
    result = suggest(plan, ledger_path=ledger_path, workflow_id=WORKFLOW_ID)

    assert state.failed_task_ids == []
    assert state.completed_task_ids == [TASK_ID]
    assert result.ready == [DOWNSTREAM_ID]


def test_reported_complete_without_prior_failure_does_not_create_failed_state(
    tmp_path: Path,
) -> None:
    plan = _plan()
    ledger_path = _ledger(tmp_path, [_event("workflow.task_reported_completed")])

    state = _state(plan, ledger_path)
    result = suggest(plan, ledger_path=ledger_path, workflow_id=WORKFLOW_ID)

    assert state.failed_task_ids == []
    assert state.completed_task_ids == []
    assert result.ready == []
    assert f"failed_dep:{TASK_ID}" not in _blocked_reasons(result, DOWNSTREAM_ID)
