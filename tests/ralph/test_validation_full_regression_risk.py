from __future__ import annotations

from cccc.ralph.models import Plan
from cccc.ralph.validation_rules.coverage import _check_full_regression_override_risk


def _task(task_id: str, *, command: str = "", checks: list[str] | None = None, mock_tests: list[dict] | None = None, goal_behavior: str = "") -> dict:
    check_commands = checks or []
    return {
        "id": task_id,
        "goal_behavior": goal_behavior,
        "verification": {
            "level": "unit",
            "command": command,
            "checks": [
                {"name": f"check-{index}", "command": check}
                for index, check in enumerate(check_commands, start=1)
            ],
            "mock_tests": mock_tests,
        },
    }


def _issues_by_code(issues, code: str) -> list:
    return [issue for issue in issues if issue.code == code]


def test_full_pytest_gate_plus_override_signal_warns() -> None:
    issues = _check_full_regression_override_risk(Plan.model_validate({
        "tasks": [
            _task("gate", command="python -m pytest -q"),
            _task("override", checks=["python -m pytest tests/unit/test_api.py -q --deselect tests/unit/test_skip.py"]),
        ],
    }))

    warning = _issues_by_code(issues, "W_FULL_REGRESSION_OVERRIDE_RISK")
    assert len(warning) == 1
    assert warning[0].task_ids == ["gate"]


def test_full_pytest_gate_without_override_signal_is_silent() -> None:
    issues = _check_full_regression_override_risk(Plan.model_validate({
        "tasks": [_task("gate", command="python -m pytest -q")],
    }))

    assert _issues_by_code(issues, "W_FULL_REGRESSION_OVERRIDE_RISK") == []


def test_prose_only_override_words_do_not_trigger_rule() -> None:
    issues = _check_full_regression_override_risk(Plan.model_validate({
        "tasks": [
            _task("gate", command="python -m pytest -q"),
            _task("notes", checks=["python -m pytest tests/unit/test_notes.py -q"], goal_behavior="override retry strategy here"),
        ],
    }))

    assert _issues_by_code(issues, "W_FULL_REGRESSION_OVERRIDE_RISK") == []


def test_override_signal_without_full_gate_is_silent() -> None:
    issues = _check_full_regression_override_risk(Plan.model_validate({
        "tasks": [
            _task("gate", checks=["python -m pytest tests/unit/test_api.py -q"]),
            _task("override", mock_tests=[{"name": "planned-failure", "verify_command": "python -c 'import pytest; pytest.skip()'"}]),
        ],
    }))

    assert _issues_by_code(issues, "W_FULL_REGRESSION_OVERRIDE_RISK") == []


def test_pytest_k_filter_is_not_treated_as_full_gate() -> None:
    issues = _check_full_regression_override_risk(Plan.model_validate({
        "tasks": [
            _task("gate", command="python -m pytest -q -k login"),
            _task("override", checks=["python -m pytest tests/unit/test_api.py -q --deselect tests/unit/test_skip.py"]),
        ],
    }))

    assert _issues_by_code(issues, "W_FULL_REGRESSION_OVERRIDE_RISK") == []
