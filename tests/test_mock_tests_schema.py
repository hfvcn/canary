from __future__ import annotations

from pathlib import Path

import yaml

from cccc.ralph.models import Plan, TaskSpec, ValidationIssue, Verification
from cccc.ralph.plan_io import load_plan
from cccc.ralph.validator import validate


def _plan_with_task(task: TaskSpec) -> Plan:
    return Plan(tasks=[task])


def _issue_codes(plan: Plan) -> set[str]:
    report = validate(plan)
    issues = [*report.errors, *report.warnings, *report.hints]
    return {issue.code for issue in issues}


def _issues_by_code(plan: Plan, code: str) -> list[ValidationIssue]:
    report = validate(plan)
    issues = [*report.errors, *report.warnings, *report.hints]
    return [issue for issue in issues if issue.code == code]


def test_load_plan_parses_verification_mock_tests(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.yaml"
    payload = {
        "schema_version": "1.0.0",
        "tasks": [
            {
                "id": "T-agent",
                "verification_mode": "agent",
                "verification": {
                    "level": "unit",
                    "mock_tests": [
                        {
                            "name": "accepts-valid-payload",
                            "input": {"value": "ok"},
                            "expected_output": {"status": "accepted"},
                            "setup_command": "python -m compileall src",
                            "verify_command": "python -m pytest tests/test_mock_tests_schema.py -q",
                            "description": "valid payload should pass",
                        }
                    ],
                },
            }
        ],
    }
    plan_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    plan = load_plan(plan_path)
    mock_tests = plan.tasks[0].verification.mock_tests

    assert mock_tests is not None
    assert mock_tests[0].name == "accepts-valid-payload"
    assert mock_tests[0].input == {"value": "ok"}
    assert mock_tests[0].expected_output == {"status": "accepted"}
    assert mock_tests[0].verify_command.endswith("tests/test_mock_tests_schema.py -q")
    dumped = plan.model_dump()
    assert dumped["tasks"][0]["verification"]["mock_tests"][0]["name"] == "accepts-valid-payload"


def test_task_ref_projection_preserves_mock_tests() -> None:
    task = TaskSpec(
        id="T-agent",
        verification_mode="agent",
        verification=Verification(
            level="unit",
            mock_tests=[
                {
                    "name": "case-1",
                    "input": {"path": "src/app.py"},
                    "expected_output": {"ok": True},
                    "verify_command": "python -m pytest tests/test_mock_tests_schema.py -q",
                }
            ],
        ),
    )

    ref = task.to_task_ref()

    assert ref.verification is not None
    assert ref.verification.mock_tests is not None
    assert ref.verification.mock_tests[0].name == "case-1"
    assert ref.verification.mock_tests[0].expected_output == {"ok": True}


def test_mock_tests_missing_name_and_verify_command_emit_errors() -> None:
    plan = _plan_with_task(
        TaskSpec(
            id="T-agent",
            verification_mode="agent",
            verification=Verification(
                level="unit",
                mock_tests=[{"name": " ", "verify_command": "  "}],
            ),
        )
    )

    issues = _issues_by_code(plan, "E_MOCK_TEST_MISSING_NAME")
    command_issues = _issues_by_code(plan, "E_MOCK_TEST_MISSING_VERIFY_COMMAND")

    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert issues[0].task_ids == ["T-agent"]
    assert len(command_issues) == 1
    assert command_issues[0].severity == "error"
    assert command_issues[0].task_ids == ["T-agent"]


def test_mock_tests_on_ralph_mode_emit_hint() -> None:
    plan = _plan_with_task(
        TaskSpec(
            id="T-ralph",
            verification_mode="ralph",
            verification=Verification(
                level="unit",
                mock_tests=[
                    {
                        "name": "case-1",
                        "verify_command": "python -m pytest tests/test_mock_tests_schema.py -q",
                    }
                ],
            ),
        )
    )

    issues = _issues_by_code(plan, "H_MOCK_TESTS_ON_RALPH_MODE")

    assert len(issues) == 1
    assert issues[0].severity == "hint"
    assert issues[0].task_ids == ["T-ralph"]


def test_existing_verification_without_mock_tests_is_unchanged() -> None:
    plan = _plan_with_task(
        TaskSpec(
            id="T-existing",
            verification=Verification(level="unit", command="python -m pytest tests -q"),
        )
    )

    codes = _issue_codes(plan)

    assert "E_MOCK_TEST_MISSING_NAME" not in codes
    assert "E_MOCK_TEST_MISSING_VERIFY_COMMAND" not in codes
    assert "H_MOCK_TESTS_ON_RALPH_MODE" not in codes
