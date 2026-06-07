from __future__ import annotations

from cccc.ralph.models import Plan, TaskSpec, ValidationIssue, Verification
from cccc.ralph.validator import validate
from cccc.ralph.validation_rules.coverage import _check_status_code_drift


def _task(
    task_id: str = "T1",
    *,
    goal: str = "",
    acceptance: str = "",
) -> TaskSpec:
    return TaskSpec(
        id=task_id,
        claimed_paths=["src/app.py"],
        goal_behavior=goal,
        acceptance_criteria=acceptance,
        verification=Verification.model_validate({
            "level": "unit",
            "command": "python -m pytest tests/test_status_code_drift.py -q",
        }),
    )


def _issues_by_code(issues: list[ValidationIssue], code: str) -> list[ValidationIssue]:
    return [issue for issue in issues if issue.code == code]


def test_goal_status_code_missing_from_acceptance_warns() -> None:
    plan = Plan(
        tasks=[
            _task(
                goal="删除资源时返回 410",
                acceptance="resource lookup must return 404",
            )
        ]
    )

    issues = _check_status_code_drift(plan)

    warning = _issues_by_code(issues, "W_STATUS_CODE_DRIFT")
    assert len(warning) == 1
    assert warning[0].task_ids == ["T1"]
    assert warning[0].evidence == {
        "goal_codes": ["410"],
        "acceptance_codes": ["404"],
        "drifted": ["410"],
    }


def test_matching_status_codes_emit_no_warning() -> None:
    plan = Plan(tasks=[_task(goal="请求缺失时返回 404", acceptance="handler must return 404")])

    issues = _check_status_code_drift(plan)

    assert _issues_by_code(issues, "W_STATUS_CODE_DRIFT") == []


def test_goal_without_status_codes_is_skipped() -> None:
    plan = Plan(tasks=[_task(goal="删除不存在资源时给出明确错误", acceptance="status 404")])

    issues = _check_status_code_drift(plan)

    assert issues == []


def test_acceptance_without_status_codes_is_skipped() -> None:
    plan = Plan(tasks=[_task(goal="删除不存在资源时返回 404", acceptance="删除不存在资源时提示未找到")])

    issues = _check_status_code_drift(plan)

    assert issues == []


def test_acceptance_superset_of_goal_status_codes_emits_no_warning() -> None:
    plan = Plan(
        tasks=[
            _task(
                goal="成功返回 200，缺失时返回 404",
                acceptance="status 200, status 404, status 410",
            )
        ]
    )

    issues = _check_status_code_drift(plan)

    assert _issues_by_code(issues, "W_STATUS_CODE_DRIFT") == []


def test_validate_surfaces_status_code_drift_warning() -> None:
    plan = Plan(
        tasks=[
            _task(
                goal="删除资源时返回 410",
                acceptance="resource lookup must return 404",
            )
        ]
    )

    warning = _issues_by_code(validate(plan).warnings, "W_STATUS_CODE_DRIFT")

    assert len(warning) == 1
    assert warning[0].task_ids == ["T1"]
