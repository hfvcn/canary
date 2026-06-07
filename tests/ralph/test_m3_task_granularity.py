from __future__ import annotations

from cccc.ralph.models import Plan
from cccc.ralph.validation_rules.task_granularity import (
    W_TASK_GRANULARITY_COMPRESSION,
    _check_task_granularity,
)


_FOUR_SEGMENT_GOAL = """
A. Update the Ralph validation path.
B. Expand daemon orchestration handling.
C. Adjust contracts surface and schema.
D. Align verification expectations.
""".strip()


def _task(
    task_id: str,
    *,
    role: str = "leaf",
    addresses: list[str] | None = None,
    claimed_paths: list[str] | None = None,
    goal_behavior: str = _FOUR_SEGMENT_GOAL,
) -> dict[str, object]:
    return {
        "id": task_id,
        "role": role,
        "addresses": addresses or [],
        "claimed_paths": claimed_paths or [],
        "goal_behavior": goal_behavior,
        "acceptance_criteria": "granularity warning behaves correctly",
    }


def _plan(*tasks: dict[str, object]) -> Plan:
    return Plan.model_validate({"tasks": list(tasks)})


def test_over_compressed_task_emits_warning_with_expected_evidence() -> None:
    plan = _plan(_task(
        "T-compressed",
        addresses=["DG-33", "FL-73", "RV-22", "RA-11"],
        claimed_paths=[
            "src/cccc/ralph/core.py",
            "src/cccc/daemon/foreman/agent_pool.py",
            "src/cccc/contracts/v1/ralph_ipc.py",
        ],
    ))

    issues = _check_task_granularity(plan)

    assert len(issues) == 1
    issue = issues[0]
    assert issue.code == W_TASK_GRANULARITY_COMPRESSION
    assert issue.task_ids == ["T-compressed"]
    assert issue.evidence == {
        "n_addresses": 4,
        "n_components": 3,
        "n_segments": 4,
    }


def test_reasonable_task_with_few_addresses_or_components_is_not_flagged() -> None:
    plan = _plan(_task(
        "T-reasonable",
        addresses=["DG-33", "FL-73"],
        claimed_paths=[
            "src/cccc/ralph/core.py",
            "src/cccc/ralph/models.py",
        ],
        goal_behavior="A. Tighten one validator path.\nB. Update its local tests.",
    ))

    assert _check_task_granularity(plan) == []


def test_integration_role_is_exempt_even_if_spanning_many_components() -> None:
    plan = _plan(_task(
        "T-integration",
        role="integration",
        addresses=["DG-33", "FL-73", "RV-22", "RA-11"],
        claimed_paths=[
            "src/cccc/ralph/core.py",
            "src/cccc/daemon/foreman/agent_pool.py",
            "src/cccc/contracts/v1/ralph_ipc.py",
        ],
    ))

    assert _check_task_granularity(plan) == []


def test_cohesive_contracts_task_negative_fixture_is_not_flagged() -> None:
    plan = _plan(_task(
        "T-contracts",
        addresses=["DG-33", "FL-73"],
        claimed_paths=[
            "src/cccc/contracts/v1/ralph_ipc.py",
            "src/cccc/contracts/v1/plan_schema.py",
        ],
    ))

    assert _check_task_granularity(plan) == []


def test_tests_and_fixture_paths_do_not_count_as_components() -> None:
    plan = _plan(_task(
        "T-sanity",
        addresses=["DG-33", "FL-73", "RV-22", "RA-11"],
        claimed_paths=[
            "src/cccc/ralph/core.py",
            "src/cccc/contracts/v1/ralph_ipc.py",
            "tests/ralph/test_parallelism.py",
            "tests/fixtures/compressed_plan.yaml",
            "src/cccc/daemon/fixtures/shared_plan.yaml",
        ],
    ))

    assert _check_task_granularity(plan) == []
