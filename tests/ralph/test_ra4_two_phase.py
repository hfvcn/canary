from __future__ import annotations

from cccc.ralph.core import suggest
from cccc.ralph.models import Plan, PlanState, TaskSpec


def _make_plan(*, completed_task_ids: list[str]) -> Plan:
    return Plan(
        tasks=[
            TaskSpec.model_validate({"id": "T1", "claimed_paths": ["src/t1.py"]}),
            TaskSpec.model_validate(
                {"id": "T2", "claimed_paths": ["src/t2.py"], "depends_on": ["T1"]}
            ),
        ],
        state=PlanState(completed_task_ids=completed_task_ids),
    )


def test_suggest_has_batch_id() -> None:
    result = suggest(_make_plan(completed_task_ids=[]))

    assert "batch_sequence" in result.model_dump()
    assert result.batch_sequence == 0
    assert result.batch_boundary is True


def test_batch_id_increments() -> None:
    initial = suggest(_make_plan(completed_task_ids=[]))
    after_completion = suggest(_make_plan(completed_task_ids=["T1"]))

    assert after_completion.batch_sequence > initial.batch_sequence
