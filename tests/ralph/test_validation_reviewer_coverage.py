from __future__ import annotations

import pytest

from cccc.ralph.models import CheckSpec, CriticalFlow, Plan, TaskSpec, Verification, VerificationCovers
from cccc.ralph.validator import validate


def _issues_by_code(report, code: str) -> list:
    return [issue for issue in [*report.errors, *report.warnings, *report.hints] if issue.code == code]


def _task(
    task_id: str,
    *,
    flow_id: str | None = None,
    role: str = "leaf",
    verification_mode: str = "ralph",
    title: str = "",
    goal_behavior: str = "",
) -> TaskSpec:
    check = CheckSpec(name="unit-check", command=f"python -m pytest tests/{task_id.lower()}_test.py -q")
    return TaskSpec(
        id=task_id,
        title=title,
        role=role,
        claimed_paths=[f"src/{task_id.lower()}.py"],
        goal_behavior=goal_behavior,
        acceptance_criteria="critical flow review coverage is verified",
        verification_mode=verification_mode,
        verification=Verification(
            level="unit",
            command=check.command,
            checks=[check],
            covers=VerificationCovers(tasks=[task_id], flows=[flow_id] if flow_id else []),
        ),
    )


def _flow(flow_id: str) -> CriticalFlow:
    return CriticalFlow(
        id=flow_id,
        entrypoints=[f"src/critical/{flow_id}.py"],
        required_verification_level="unit",
    )


def test_leaf_executor_only_flow_warns() -> None:
    plan = Plan(tasks=[_task("T1", flow_id="login_flow")], critical_flows=[_flow("login_flow")])

    report = validate(plan)
    issues = _issues_by_code(report, "W_CRITICAL_FLOW_NO_INDEPENDENT_REVIEW")

    assert len(issues) == 1
    assert issues[0].task_ids == ["T1"]
    assert issues[0].evidence == {"flow_id": "login_flow"}


@pytest.mark.parametrize("verification_mode", ["challenge", "agent"])
def test_agent_or_challenge_mode_satisfies_independent_review(verification_mode: str) -> None:
    plan = Plan(
        tasks=[_task("T1", flow_id="login_flow", verification_mode=verification_mode)],
        critical_flows=[_flow("login_flow")],
    )

    report = validate(plan)

    assert _issues_by_code(report, "W_CRITICAL_FLOW_NO_INDEPENDENT_REVIEW") == []


@pytest.mark.parametrize("role", ["integration", "verification"])
def test_integration_or_verification_role_satisfies_independent_review(role: str) -> None:
    plan = Plan(tasks=[_task("T1", flow_id="login_flow", role=role)], critical_flows=[_flow("login_flow")])

    report = validate(plan)

    assert _issues_by_code(report, "W_CRITICAL_FLOW_NO_INDEPENDENT_REVIEW") == []


def test_reviewer_on_one_flow_does_not_silence_another_flow() -> None:
    plan = Plan(
        tasks=[
            _task(
                "T1",
                flow_id="payments_flow",
                title="security-reviewer for payments",
                goal_behavior="审查 payment authorization path",
            ),
            _task("T2", flow_id="admin_flow"),
        ],
        critical_flows=[_flow("payments_flow"), _flow("admin_flow")],
    )

    report = validate(plan)
    issues = _issues_by_code(report, "W_CRITICAL_FLOW_NO_INDEPENDENT_REVIEW")

    assert len(issues) == 1
    assert issues[0].task_ids == ["T2"]
    assert issues[0].evidence == {"flow_id": "admin_flow"}


def test_no_critical_flows_has_no_independent_review_issue() -> None:
    plan = Plan(tasks=[_task("T1")])

    report = validate(plan)

    assert _issues_by_code(report, "W_CRITICAL_FLOW_NO_INDEPENDENT_REVIEW") == []
