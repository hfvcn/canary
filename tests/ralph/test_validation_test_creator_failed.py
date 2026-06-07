from __future__ import annotations

from cccc.ralph.models import Plan
from cccc.ralph.validation_rules.coverage import (
    _check_critical_coverage,
    _check_forbidden_flows,
    _pending_test_creator_ids,
)


def _issues_by_code(issues, code: str) -> list:
    return [issue for issue in issues if issue.code == code]


def _plan(*, tasks: list[dict], critical_flows: list[dict] | None = None, forbidden_flows: list[dict] | None = None, state: dict | None = None) -> Plan:
    return Plan.model_validate({
        "tasks": tasks,
        "critical_flows": critical_flows or [],
        "forbidden_flows": forbidden_flows or [],
        "state": state or {},
    })


def test_failed_critical_flow_creator_is_an_error() -> None:
    issues = _check_critical_coverage(_plan(
        tasks=[{"id": "create-tests"}],
        critical_flows=[{"id": "login_flow", "test_created_by": ["create-tests"]}],
        state={"failed_task_ids": ["create-tests"]},
    ))

    failure = _issues_by_code(issues, "E_FLOW_TEST_CREATOR_FAILED")
    assert len(failure) == 1
    assert failure[0].evidence == {
        "flow_id": "login_flow",
        "namespace": "critical",
        "failed_task_ids": ["create-tests"],
    }


def test_failed_forbidden_flow_creator_is_an_error() -> None:
    issues = _check_forbidden_flows(_plan(
        tasks=[{"id": "create-tests"}],
        forbidden_flows=[{"id": "bypass_flow", "test_created_by": ["create-tests"]}],
        state={"failed_task_ids": ["create-tests"]},
    ))

    failure = _issues_by_code(issues, "E_FLOW_TEST_CREATOR_FAILED")
    assert len(failure) == 1
    assert failure[0].evidence["namespace"] == "forbidden"


def test_pending_creator_emits_original_hint_and_visibility_warning() -> None:
    issues = _check_critical_coverage(_plan(
        tasks=[{"id": "create-tests"}],
        critical_flows=[{"id": "login_flow", "test_created_by": ["create-tests"]}],
    ))

    uncovered = _issues_by_code(issues, "E_CRITICAL_FLOW_UNCOVERED")
    deferred = _issues_by_code(issues, "W_FLOW_COVERAGE_DEFERRED")
    assert len(uncovered) == 1
    assert uncovered[0].severity == "hint"
    assert len(deferred) == 1
    assert deferred[0].severity == "warning"
    assert deferred[0].evidence["pending_task_ids"] == ["create-tests"]


def test_completed_creator_keeps_existing_error_behavior() -> None:
    issues = _check_critical_coverage(_plan(
        tasks=[{"id": "create-tests"}],
        critical_flows=[{"id": "login_flow", "test_created_by": ["create-tests"]}],
        state={"completed_task_ids": ["create-tests"]},
    ))

    assert len(_issues_by_code(issues, "E_CRITICAL_FLOW_UNCOVERED")) == 1
    assert _issues_by_code(issues, "W_FLOW_COVERAGE_DEFERRED") == []


def test_covered_flow_emits_no_uncovered_or_creator_failure_issue() -> None:
    issues = _check_critical_coverage(_plan(
        tasks=[{
            "id": "verify-flow",
            "claimed_paths": ["src/auth.py"],
            "verification": {
                "level": "unit",
                "command": "pytest tests/test_auth.py -q",
                "checks": [{"name": "auth", "command": "pytest tests/test_auth.py -q"}],
                "covers": {"flows": ["login_flow"]},
            },
        }],
        critical_flows=[{"id": "login_flow", "entrypoints": ["src/auth.py"]}],
    ))

    assert _issues_by_code(issues, "E_CRITICAL_FLOW_UNCOVERED") == []
    assert _issues_by_code(issues, "E_FLOW_TEST_CREATOR_FAILED") == []


def test_pending_creator_helper_excludes_completed_and_failed_tasks() -> None:
    pending = _pending_test_creator_ids(["done", "failed", "pending"], ["done"], ["failed"])

    assert pending == ["pending"]
