from __future__ import annotations

from cccc.ralph.core import suggest
from cccc.ralph.models import Plan, PlanState, TaskSpec


def _plan(tasks: list[dict], **state_kw) -> Plan:
    return Plan(
        tasks=[TaskSpec.model_validate(task) for task in tasks],
        state=PlanState(**state_kw),
    )


def test_task_descriptions_populated() -> None:
    tasks = [
        {
            "id": f"T{index}",
            "title": f"Task {index}",
            "claimed_paths": [f"src/t{index}.py"],
            "goal_behavior": f"Deliver behavior {index}",
        }
        for index in range(1, 6)
    ]

    result = suggest(_plan(tasks))

    assert result.task_descriptions == {
        f"T{index}": f"Deliver behavior {index}"
        for index in range(1, 6)
    }


def test_batch_sequence_with_descriptions() -> None:
    tasks = [
        {
            "id": "T1",
            "claimed_paths": ["src/t1.py"],
            "goal_behavior": "Deliver first behavior",
        },
        {
            "id": "T2",
            "claimed_paths": ["src/t2.py"],
            "depends_on": ["T1"],
            "goal_behavior": "Deliver second behavior",
        },
        {
            "id": "T3",
            "claimed_paths": ["src/t3.py"],
            "depends_on": ["T2"],
            "goal_behavior": "Deliver third behavior",
        },
    ]

    first = suggest(_plan(tasks))
    second = suggest(_plan(tasks, completed_task_ids=["T1"]))
    third = suggest(_plan(tasks, completed_task_ids=["T1", "T2"]))

    assert first.batch_sequence == 0
    assert first.task_descriptions == {"T1": "Deliver first behavior"}
    assert second.batch_sequence == 1
    assert second.task_descriptions == {"T2": "Deliver second behavior"}
    assert third.batch_sequence == 2
    assert third.task_descriptions == {"T3": "Deliver third behavior"}


def test_descriptions_only_for_ready() -> None:
    tasks = [
        {
            "id": "T1",
            "claimed_paths": ["src/t1.py"],
            "goal_behavior": "Ready behavior",
        },
        {
            "id": "T2",
            "claimed_paths": ["src/t2.py"],
            "depends_on": ["T1"],
            "goal_behavior": "Blocked behavior",
        },
    ]

    result = suggest(_plan(tasks))

    assert result.ready == ["T1"]
    assert result.task_descriptions == {"T1": "Ready behavior"}
    assert "T2" not in result.task_descriptions
