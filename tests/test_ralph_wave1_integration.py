"""Wave 1 integration tests for deterministic sorting, error envelopes, and cache invalidation."""

from __future__ import annotations

import importlib
import json
import os
import time
from pathlib import Path
from typing import Any

import pytest
import yaml

from cccc.ralph.filesystem_validator import clear_issue_file_map_cache
from cccc.ralph.plan_io import load_plan

EXIT_OK = 0
EXIT_VALIDATION_FAILURE = 1
EXIT_INTERNAL_ERROR = 2
JSON_FORMAT = "json"
MTIME_BUMP_NS = 1_000_000
MTIME_WAIT_SECONDS = 0.02


def _import_module(name: str):
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


_VALIDATOR_MODULE = _import_module("cccc.ralph.validator")
validate = getattr(_VALIDATOR_MODULE, "validate", None)
validate_with_project = getattr(_VALIDATOR_MODULE, "validate_with_project", None)

_MODELS_MODULE = _import_module("cccc.ralph.models")
Plan = getattr(_MODELS_MODULE, "Plan", None)
ValidationIssue = getattr(_MODELS_MODULE, "ValidationIssue", None)
ValidationReport = getattr(_MODELS_MODULE, "ValidationReport", None)

_CLI_MODULE = _import_module("cccc.ralph.cli")
ralph_main = getattr(_CLI_MODULE, "main", None)

_AGENT_MODULE = _import_module("cccc.ralph.agent")
build_error_envelope = getattr(_AGENT_MODULE, "build_error_envelope", None)
RULE_ERROR_REGISTRY = getattr(_AGENT_MODULE, "RULE_ERROR_REGISTRY", None)


def _require(symbol: Any, dotted_name: str):
    if symbol is None:
        pytest.skip(f"{dotted_name} is not available in this build")
    return symbol


def _write_plan(plan_path: Path, payload: dict[str, Any]) -> Path:
    plan_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return plan_path


def _issue_codes(report: Any) -> set[str]:
    return {issue.code for issue in _all_issues(report)}


def _all_issues(report: Any) -> list[Any]:
    return [*report.errors, *report.warnings, *report.hints]


def _validate_report(plan: Any, *, project_root: Path | None = None):
    if project_root is not None and validate_with_project is not None:
        return validate_with_project(plan, project_root=project_root)
    if validate is not None:
        return validate(plan)
    if validate_with_project is not None and project_root is not None:
        return validate_with_project(plan, project_root=project_root)
    pytest.skip("No usable validator entrypoint is available")


def _run_cli_validate(plan_path: Path, *, project_root: Path) -> int:
    main = _require(ralph_main, "cccc.ralph.cli.main")
    return main(
        [
            "validate",
            str(plan_path),
            "--format",
            JSON_FORMAT,
            "--project-root",
            str(project_root),
        ]
    )


def _expected_error_code(stage: str) -> str:
    if RULE_ERROR_REGISTRY is not None and stage in RULE_ERROR_REGISTRY:
        return RULE_ERROR_REGISTRY[stage]
    if build_error_envelope is not None:
        probe = build_error_envelope(stage=stage, exception=RuntimeError("probe"))
        return probe["internal_error_code"]
    return "E_INTERNAL_LOAD"


def _touch_with_new_mtime(path: Path, content: str) -> None:
    time.sleep(MTIME_WAIT_SECONDS)
    path.write_text(content, encoding="utf-8")
    new_mtime = path.stat().st_mtime_ns + MTIME_BUMP_NS
    os.utime(path, ns=(new_mtime, new_mtime))


def test_wave1_deterministic_sort_keeps_json_stdout_byte_identical(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    _require(Plan, "cccc.ralph.models.Plan")
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "provider.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "src" / "consumer.py").write_text("VALUE = 2\n", encoding="utf-8")
    (tmp_path / "tests" / "test_provider.py").write_text("def test_provider():\n    assert True\n", encoding="utf-8")
    (tmp_path / "tests" / "test_consumer.py").write_text("def test_consumer():\n    assert True\n", encoding="utf-8")
    plan_path = _write_plan(
        tmp_path / "deterministic_plan.yaml",
        {
            "tasks": [
                {
                    "id": "T1",
                    "title": "Provider",
                    "claimed_paths": ["src/provider.py"],
                    "verification": {
                        "level": "unit",
                        "command": "pytest tests/test_provider.py -q",
                        "covers": {"tasks": ["T1"]},
                    },
                    "provides": [{"name": "shared_contract", "from": "T1"}],
                },
                {
                    "id": "T2",
                    "title": "Consumer",
                    "claimed_paths": ["src/consumer.py"],
                    "verification": {
                        "level": "unit",
                        "command": "pytest tests/test_consumer.py -q",
                        "covers": {"tasks": ["T2"]},
                    },
                    "consumes": [{"name": "shared_contract", "from": "T1"}],
                },
            ]
        },
    )

    loaded_plan = load_plan(plan_path)
    report = _validate_report(loaded_plan)
    assert isinstance(loaded_plan, Plan)
    if ValidationReport is not None:
        assert isinstance(report, ValidationReport)
    assert report.valid is False
    assert {"E_NO_CROSS_TASK_VERIFICATION", "W_EMPTY_ACCEPTANCE", "W_INTEGRATION_INTERFACE_MISMATCH"} <= _issue_codes(report)
    assert any(len(issue.task_ids) > 1 for issue in _all_issues(report))
    if ValidationIssue is not None:
        assert any(isinstance(issue, ValidationIssue) for issue in _all_issues(report))

    first_exit = _run_cli_validate(plan_path, project_root=tmp_path)
    first = capsys.readouterr()
    second_exit = _run_cli_validate(plan_path, project_root=tmp_path)
    second = capsys.readouterr()

    assert first_exit == EXIT_VALIDATION_FAILURE
    assert second_exit == EXIT_VALIDATION_FAILURE
    assert "Traceback" not in first.err
    assert "Traceback" not in second.err
    assert first.out.encode("utf-8") == second.out.encode("utf-8")
    payload = json.loads(first.out)
    assert payload["valid"] is False
    assert [error["code"] for error in payload["errors"]] == ["E_NO_CROSS_TASK_VERIFICATION"]


def test_wave1_error_envelope_and_validation_failure_exit_codes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    malformed_path = tmp_path / "malformed.yaml"
    malformed_path.write_text("{{{{invalid yaml: [[[\n", encoding="utf-8")

    internal_exit = _run_cli_validate(malformed_path, project_root=tmp_path)
    malformed_output = capsys.readouterr()
    malformed_error = json.loads(malformed_output.err)["error"]
    assert internal_exit == EXIT_INTERNAL_ERROR
    assert malformed_error["stage"] == "load"
    assert malformed_error["internal_error_code"] == _expected_error_code("load")
    assert "Traceback" not in malformed_output.err

    invalid_plan_path = _write_plan(
        tmp_path / "missing_verification.yaml",
        {
            "tasks": [
                {
                    "id": "T1",
                    "title": "No verification",
                    "claimed_paths": ["src/no_verification.py"],
                    "acceptance_criteria": "demonstrate plan-level failure",
                }
            ]
        },
    )
    invalid_plan = load_plan(invalid_plan_path)
    report = _validate_report(invalid_plan)
    assert isinstance(invalid_plan, Plan)
    assert report.valid is False
    assert "E_MISSING_VERIFICATION" in _issue_codes(report)

    invalid_exit = _run_cli_validate(invalid_plan_path, project_root=tmp_path)
    invalid_output = capsys.readouterr()
    invalid_payload = json.loads(invalid_output.out)
    assert invalid_exit == EXIT_VALIDATION_FAILURE
    assert invalid_payload["valid"] is False
    assert any(issue["code"] == "E_MISSING_VERIFICATION" for issue in invalid_payload["errors"])
    assert "Traceback" not in invalid_output.err


def test_wave1_cache_invalidation_reflects_mutated_fixture(tmp_path: Path) -> None:
    validate_project = _require(validate_with_project, "cccc.ralph.validator.validate_with_project")
    _require(Plan, "cccc.ralph.models.Plan")
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "widget.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_smoke.py").write_text("def test_smoke():\n    assert True\n", encoding="utf-8")
    linked_test = tmp_path / "tests" / "test_widget_direct.py"
    linked_test.write_text("from widget import VALUE\n\ndef test_value():\n    assert VALUE == 1\n", encoding="utf-8")
    plan_path = _write_plan(
        tmp_path / "cache_plan.yaml",
        {
            "tasks": [
                {
                    "id": "T1",
                    "title": "Widget",
                    "claimed_paths": ["src/widget.py"],
                    "acceptance_criteria": "keep widget stable",
                    "verification": {
                        "level": "unit",
                        "command": "pytest tests/test_smoke.py -q",
                        "covers": {"tasks": ["T1"]},
                    },
                }
            ]
        },
    )

    clear_issue_file_map_cache()
    before = validate_project(load_plan(plan_path), project_root=tmp_path)
    if ValidationReport is not None:
        assert isinstance(before, ValidationReport)
    assert {"W_TEST_COVERAGE_GAP", "W_UNCLAIMED_TEST_FOR_SOURCE"} <= _issue_codes(before)

    _touch_with_new_mtime(linked_test, "def test_irrelevant():\n    assert True\n")
    after = validate_project(load_plan(plan_path), project_root=tmp_path)
    assert "W_TEST_COVERAGE_GAP" not in _issue_codes(after)
    assert "W_UNCLAIMED_TEST_FOR_SOURCE" not in _issue_codes(after)
    assert before.model_dump() != after.model_dump()
