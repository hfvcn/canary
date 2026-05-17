"""Tests for AD-2 Aegis discipline infrastructure."""

from __future__ import annotations

import pytest

from cccc.contracts.v1.ralph_ipc import TaskRef
from cccc.ralph.aegis import effective_intent
from cccc.ralph.models import Plan, TaskSpec
from cccc.ralph.validation_rules.discipline import collect_discipline_issues


@pytest.mark.parametrize(
    ("title", "goal_behavior", "expected_intent"),
    [
        ("Fix login bug", "", "fix"),
        ("Debug failed verification", "", "fix"),
        ("", "Add websocket feature", "feature"),
        ("Implement the assignment route", "", "feature"),
        ("Refactor legacy service", "", "refactor"),
        ("", "Migrate old queue and replace adapter", "refactor"),
        ("", "Add regression test coverage", "feature"),
        ("Document release notes", "", "general"),
    ],
)
def test_effective_intent_infers_task_spec_intent(
    title: str,
    goal_behavior: str,
    expected_intent: str,
) -> None:
    task = TaskSpec.model_validate(
        {"id": "T1", "title": title, "goal_behavior": goal_behavior}
    )

    assert effective_intent(task) == expected_intent


def test_effective_intent_prefers_task_spec_aegis_intent() -> None:
    task = TaskSpec.model_validate(
        {
            "id": "T1",
            "title": "Implement new retry feature",
            "aegis": {"intent": "fix"},
        }
    )

    assert effective_intent(task) == "fix"


def test_effective_intent_reads_task_ref_aegis_dict() -> None:
    task = TaskRef(
        id="T1",
        title="Add feature",
        aegis={"intent": "refactor"},
    )

    assert effective_intent(task) == "refactor"


def test_effective_intent_infers_task_ref_goal_behavior() -> None:
    task = TaskRef(
        id="T1",
        title="",
        goal_behavior="Write focused test coverage",
    )

    assert effective_intent(task) == "test"


def test_collect_discipline_issues_runs_registered_rules() -> None:
    plan = Plan.model_validate(
        {
            "tasks": [
                {
                    "id": "T1",
                    "title": "TBD validator behavior",
                    "goal_behavior": "Refresh concrete rule wiring.",
                }
            ],
            "semantic_mode": "off",
        }
    )

    assert [
        issue.code for issue in collect_discipline_issues(plan)
    ] == ["E_AEGIS_PLACEHOLDER_CONTENT"]
