from __future__ import annotations

from cccc.ralph.models import Plan
from cccc.ralph.validator import validate


TARGET_CODE = "E_CONSUME_PROVIDER_UNRESOLVED"


def _all_codes(report) -> set[str]:
    return {issue.code for issue in [*report.errors, *report.warnings, *report.hints]}


def _errors_by_code(report, code: str) -> list:
    return [issue for issue in report.errors if issue.code == code]


def _plan(tasks: list[dict]) -> Plan:
    return Plan.model_validate({"tasks": tasks})


def test_ambiguous_implicit_provider_emits_issue() -> None:
    report = validate(_plan([
        {"id": "P1", "provides": [{"name": "artifact"}]},
        {"id": "P2", "provides": [{"name": "artifact"}]},
        {"id": "C", "consumes": [{"name": "artifact"}]},
    ]))
    issues = _errors_by_code(report, TARGET_CODE)

    assert len(issues) == 1
    assert issues[0].task_ids == ["C"]
    assert issues[0].evidence == {
        "contract_name": "artifact",
        "candidate_provider_task_ids": ["P1", "P2"],
    }


def test_single_provider_is_silent() -> None:
    report = validate(_plan([
        {"id": "P1", "provides": [{"name": "artifact"}]},
        {"id": "C", "consumes": [{"name": "artifact"}]},
    ]))

    assert TARGET_CODE not in _all_codes(report)


def test_depends_on_unique_provider_resolves_ambiguity() -> None:
    report = validate(_plan([
        {"id": "P1", "provides": [{"name": "artifact"}]},
        {"id": "P2", "provides": [{"name": "artifact"}]},
        {"id": "C", "depends_on": ["P1"], "consumes": [{"name": "artifact"}]},
    ]))

    assert TARGET_CODE not in _all_codes(report)


def test_duplicate_provides_from_same_task_are_deduped() -> None:
    report = validate(_plan([
        {
            "id": "P1",
            "provides": [{"name": "artifact"}, {"name": "artifact"}],
        },
        {"id": "C", "consumes": [{"name": "artifact"}]},
    ]))

    assert TARGET_CODE not in _all_codes(report)


def test_explicit_from_task_is_skipped() -> None:
    report = validate(_plan([
        {"id": "P1", "provides": [{"name": "artifact"}]},
        {"id": "P2", "provides": [{"name": "artifact"}]},
        {"id": "C", "consumes": [{"name": "artifact", "from": "P1"}]},
    ]))

    assert TARGET_CODE not in _all_codes(report)


def test_missing_provider_is_left_to_contracts_rule() -> None:
    report = validate(_plan([
        {"id": "C", "consumes": [{"name": "artifact"}]},
    ]))

    assert TARGET_CODE not in _all_codes(report)
    assert "E_CONSUMER_WITHOUT_PROVIDER" in _all_codes(report)
