from __future__ import annotations

from cccc.ralph.models import Plan
from cccc.ralph.validation_rules import get_all_rules
from cccc.ralph.validation_rules.contracts import _check_contract_kind_mismatch
from cccc.ralph.validator import validate


TARGET_CODE = "E_CONTRACT_KIND_MISMATCH"


def _plan(tasks: list[dict]) -> Plan:
    return Plan.model_validate({"tasks": tasks})


def _issue_codes(report) -> set[str]:
    return {issue.code for issue in [*report.errors, *report.warnings, *report.hints]}


def _issues_by_code(issues, code: str) -> list:
    return [issue for issue in issues if issue.code == code]


def test_consume_provider_kind_mismatch_is_error() -> None:
    issues = _check_contract_kind_mismatch(_plan([
        {"id": "provider", "provides": [{"name": "users", "kind": "api_endpoint"}]},
        {"id": "consumer", "consumes": [{"name": "users", "kind": "artifact"}]},
    ]))

    mismatch = _issues_by_code(issues, TARGET_CODE)
    assert len(mismatch) == 1
    assert mismatch[0].severity == "error"
    assert mismatch[0].task_ids == ["consumer", "provider"]
    assert mismatch[0].evidence == {
        "contract_name": "users",
        "consumer_kind": "artifact",
        "provider_kind": "api_endpoint",
        "provider_task_ids": ["provider"],
    }


def test_matching_provider_kind_is_silent() -> None:
    issues = _check_contract_kind_mismatch(_plan([
        {"id": "provider", "provides": [{"name": "users", "kind": "artifact"}]},
        {"id": "consumer", "consumes": [{"name": "users", "kind": "artifact"}]},
    ]))

    assert _issues_by_code(issues, TARGET_CODE) == []


def test_missing_provider_is_left_to_consumer_without_provider() -> None:
    report = validate(_plan([
        {"id": "consumer", "consumes": [{"name": "users", "kind": "artifact"}]},
    ]))

    codes = _issue_codes(report)
    assert TARGET_CODE not in codes
    assert "E_CONSUMER_WITHOUT_PROVIDER" in codes


def test_task_without_consumes_is_silent() -> None:
    issues = _check_contract_kind_mismatch(_plan([
        {"id": "provider", "provides": [{"name": "users", "kind": "api_endpoint"}]},
    ]))

    assert _issues_by_code(issues, TARGET_CODE) == []


def test_ambiguous_provider_kinds_are_silent() -> None:
    issues = _check_contract_kind_mismatch(_plan([
        {"id": "provider_a", "provides": [{"name": "users", "kind": "api_endpoint"}]},
        {"id": "provider_b", "provides": [{"name": "users", "kind": "artifact"}]},
        {"id": "consumer", "consumes": [{"name": "users", "kind": "artifact"}]},
    ]))

    assert _issues_by_code(issues, TARGET_CODE) == []


def test_validate_reports_contract_kind_mismatch() -> None:
    report = validate(_plan([
        {"id": "provider", "provides": [{"name": "users", "kind": "api_endpoint"}]},
        {"id": "consumer", "consumes": [{"name": "users", "kind": "artifact"}]},
    ]))

    assert TARGET_CODE in _issue_codes(report)


def test_get_all_rules_lists_contract_kind_rule() -> None:
    assert _check_contract_kind_mismatch in get_all_rules()
