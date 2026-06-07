from __future__ import annotations

from cccc.ralph.models import Plan
from cccc.ralph.validation_rules.structural import _check_module_dep_cycle


def _plan(modules: list[dict] | None) -> Plan:
    task = {"id": "T1"}
    if modules is not None:
        task["modules"] = modules
    return Plan.model_validate({"tasks": [task]})


def _issues_by_code(issues, code: str) -> list:
    return [issue for issue in issues if issue.code == code]


def test_module_self_loop_is_reported() -> None:
    issues = _check_module_dep_cycle(_plan([
        {"id": "A", "internal_depends_on": ["A"]},
    ]))

    failure = _issues_by_code(issues, "E_MODULE_DEP_CYCLE")
    assert len(failure) == 1
    assert failure[0].evidence["kind"] == "self-loop"


def test_two_module_cycle_is_reported() -> None:
    issues = _check_module_dep_cycle(_plan([
        {"id": "A", "internal_depends_on": ["B"]},
        {"id": "B", "internal_depends_on": ["A"]},
    ]))

    failure = _issues_by_code(issues, "E_MODULE_DEP_CYCLE")
    assert len(failure) == 1
    assert failure[0].evidence["cycle"] == ["A", "B", "A"]


def test_three_module_cycle_is_reported() -> None:
    issues = _check_module_dep_cycle(_plan([
        {"id": "A", "internal_depends_on": ["B"]},
        {"id": "B", "internal_depends_on": ["C"]},
        {"id": "C", "internal_depends_on": ["A"]},
    ]))

    failure = _issues_by_code(issues, "E_MODULE_DEP_CYCLE")
    assert len(failure) == 1
    assert failure[0].evidence["kind"] == "cycle"


def test_dag_module_graph_is_silent() -> None:
    issues = _check_module_dep_cycle(_plan([
        {"id": "A", "internal_depends_on": ["B"]},
        {"id": "B", "internal_depends_on": []},
        {"id": "C", "internal_depends_on": ["B"]},
    ]))

    assert _issues_by_code(issues, "E_MODULE_DEP_CYCLE") == []


def test_missing_modules_do_not_emit_cycle_issue() -> None:
    assert _issues_by_code(_check_module_dep_cycle(_plan(None)), "E_MODULE_DEP_CYCLE") == []


def test_unknown_module_dependency_is_ignored_by_cycle_rule() -> None:
    issues = _check_module_dep_cycle(_plan([
        {"id": "A", "internal_depends_on": ["ghost"]},
    ]))

    assert _issues_by_code(issues, "E_MODULE_DEP_CYCLE") == []
