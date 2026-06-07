from __future__ import annotations

from cccc.ralph.models import Plan
from cccc.ralph.validator import validate

TARGET_CODE = "W_AUTH_TYPE_CAST_UNGUARDED"


def _issues_by_code(report, code: str = TARGET_CODE) -> list:
    return [issue for issue in [*report.errors, *report.warnings, *report.hints] if issue.code == code]


def _task(
    task_id: str,
    *,
    acceptance_criteria: str = "auth verification stays covered",
    checks: list[str],
    covers_flows: list[str],
    mock_tests: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "id": task_id,
        "claimed_paths": ["src/auth.py"],
        "acceptance_criteria": acceptance_criteria,
        "verification": {
            "level": "unit",
            "command": checks[0] if checks else "",
            "checks": [
                {"name": f"check-{index}", "command": command}
                for index, command in enumerate(checks, start=1)
            ],
            "mock_tests": mock_tests or [],
            "covers": {"flows": covers_flows},
        },
    }


def _plan(task: dict[str, object], flow: dict[str, object]) -> Plan:
    return Plan.model_validate({"tasks": [task], "critical_flows": [flow]})


def _auth_flow(flow_id: str = "login_flow") -> dict[str, object]:
    return {
        "id": flow_id,
        "surface_type": "auth_token",
        "entrypoints": ["src/auth.py"],
        "required_verification_level": "unit",
    }


def _non_auth_flow() -> dict[str, object]:
    return {
        "id": "checkout_flow",
        "description": "checkout submit",
        "entrypoints": ["src/checkout.py"],
        "required_verification_level": "unit",
    }


def test_auth_task_with_dual_tokens_is_silent() -> None:
    plan = _plan(
        _task(
            "T1",
            checks=["python -m pytest tests/auth/test_login_401_assert.py -q"],
            covers_flows=["login_flow"],
            mock_tests=[{
                "name": "malformed-token",
                "description": "boundary malformed non-integer token raises TypeError",
                "verify_command": "python -m pytest tests/auth/test_login_boundary.py -q",
            }],
        ),
        _auth_flow(),
    )

    assert _issues_by_code(validate(plan)) == []


def test_auth_task_with_only_malformed_tokens_warns() -> None:
    plan = _plan(
        _task(
            "T1",
            acceptance_criteria="boundary malformed invalid type token is exercised",
            checks=["python -m pytest tests/auth/test_login.py -q"],
            covers_flows=["login_flow"],
        ),
        _auth_flow(),
    )

    issues = _issues_by_code(validate(plan))

    assert len(issues) == 1
    assert issues[0].evidence["has_malformed_token"] is True
    assert issues[0].evidence["has_rejection_token"] is False


def test_auth_task_with_only_rejection_tokens_warns() -> None:
    plan = _plan(
        _task(
            "T1",
            checks=["python -m pytest tests/auth/test_login_403_forbidden.py -q"],
            covers_flows=["login_flow"],
        ),
        _auth_flow(),
    )

    issues = _issues_by_code(validate(plan))

    assert len(issues) == 1
    assert issues[0].evidence["has_malformed_token"] is False
    assert issues[0].evidence["has_rejection_token"] is True


def test_non_auth_task_is_skipped() -> None:
    plan = _plan(
        _task(
            "T1",
            checks=["python -m pytest tests/checkout/test_submit_403.py -q"],
            covers_flows=["checkout_flow"],
        ),
        _non_auth_flow(),
    )

    assert _issues_by_code(validate(plan)) == []
