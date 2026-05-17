"""Tests for AD-2 Aegis intent helper behavior."""

from __future__ import annotations

import pytest

from cccc.contracts.v1.ralph_ipc import TaskRef
from cccc.ralph.aegis import effective_intent, has_patch_shape_risk
from cccc.ralph.models import TaskSpec


@pytest.mark.parametrize(
    ("title", "goal_behavior", "expected_intent"),
    [
        ("Fix login bug", "", "fix"),
        ("", "Add websocket feature", "feature"),
        ("Refactor legacy service", "", "refactor"),
        ("", "补充测试覆盖", "test"),
        ("Document release notes", "", "general"),
    ],
)
def test_effective_intent_infers_from_task_spec_text(
    title: str,
    goal_behavior: str,
    expected_intent: str,
):
    task = TaskSpec.model_validate(
        {
            "id": "T1",
            "title": title,
            "goal_behavior": goal_behavior,
        }
    )

    assert effective_intent(task) == expected_intent


def test_effective_intent_prefers_task_spec_aegis_intent():
    task = TaskSpec.model_validate(
        {
            "id": "T1",
            "title": "Add new retry feature",
            "aegis": {"intent": "fix"},
        }
    )

    assert effective_intent(task) == "fix"


def test_effective_intent_reads_task_ref_aegis_dict():
    task = TaskRef(
        id="T1",
        title="Add feature",
        aegis={"intent": "refactor"},
    )

    assert effective_intent(task) == "refactor"


def test_effective_intent_infers_from_task_ref_without_aegis():
    task = TaskRef(
        id="T1",
        title="新增任务入口",
        goal_behavior="",
    )

    assert effective_intent(task) == "feature"


@pytest.mark.parametrize(
    ("title", "goal_behavior"),
    [
        ("Add fallback path", ""),
        ("", "Introduce compat adapter for legacy callers"),
        ("兼容旧入口", ""),
        ("", "降级处理失败路径"),
    ],
)
def test_has_patch_shape_risk_detects_risky_task_text(
    title: str,
    goal_behavior: str,
):
    task = TaskSpec.model_validate(
        {
            "id": "T1",
            "title": title,
            "goal_behavior": goal_behavior,
        }
    )

    assert has_patch_shape_risk(task) is True


def test_has_patch_shape_risk_returns_false_for_plain_task():
    task = TaskRef(
        id="T1",
        title="Implement direct validator call",
        goal_behavior="Add the primary integration path",
    )

    assert has_patch_shape_risk(task) is False
