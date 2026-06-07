from __future__ import annotations

from cccc.ralph.models import Plan
from cccc.ralph.validation_rules.contracts import _check_consumer_from_provides


def _plan(tasks: list[dict]) -> Plan:
    return Plan.model_validate({"tasks": tasks})


def _issues_by_code(issues, code: str) -> list:
    return [issue for issue in issues if issue.code == code]


def test_consume_from_existing_non_provider_is_an_error() -> None:
    issues = _check_consumer_from_provides(_plan([
        {"id": "producer", "provides": [{"name": "artifact-a"}]},
        {"id": "consumer", "consumes": [{"name": "artifact-b", "from": "producer"}]},
    ]))

    failure = _issues_by_code(issues, "E_CONSUMER_FROM_NOT_PROVIDER")
    assert len(failure) == 1
    assert failure[0].evidence == {
        "contract_name": "artifact-b",
        "from_task": "producer",
        "from_task_provides": ["artifact-a"],
    }


def test_consume_from_real_provider_is_silent() -> None:
    issues = _check_consumer_from_provides(_plan([
        {"id": "producer", "provides": [{"name": "artifact-a"}]},
        {"id": "consumer", "consumes": [{"name": "artifact-a", "from": "producer"}]},
    ]))

    assert _issues_by_code(issues, "E_CONSUMER_FROM_NOT_PROVIDER") == []


def test_consume_without_from_task_is_ignored() -> None:
    issues = _check_consumer_from_provides(_plan([
        {"id": "producer", "provides": [{"name": "artifact-a"}]},
        {"id": "consumer", "consumes": [{"name": "artifact-a"}]},
    ]))

    assert _issues_by_code(issues, "E_CONSUMER_FROM_NOT_PROVIDER") == []


def test_unknown_from_task_is_ignored_by_this_rule() -> None:
    issues = _check_consumer_from_provides(_plan([
        {"id": "consumer", "consumes": [{"name": "artifact-a", "from": "ghost"}]},
    ]))

    assert _issues_by_code(issues, "E_CONSUMER_FROM_NOT_PROVIDER") == []
