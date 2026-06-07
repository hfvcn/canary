from __future__ import annotations

from pathlib import Path

from cccc.ralph.models import Plan
from cccc.ralph.validation_rules import W_GUARD_AFTER_SIDE_EFFECT
from cccc.ralph.validator import validate_with_project


REAL_ORCHESTRATOR_PATH = "src/cccc/daemon/foreman/workflow_orchestrator.py"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _write(tmp_path: Path, rel_path: str, content: str) -> None:
    file_path = tmp_path / rel_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")


def _plan(
    *,
    claimed_paths: list[str],
    plan_scope: list[str] | None = None,
) -> Plan:
    return Plan.model_validate({
        "plan_scope": ["src"] if plan_scope is None else plan_scope,
        "tasks": [{
            "id": "T1",
            "role": "integration",
            "claimed_paths": claimed_paths,
            "goal_behavior": "validate guard ordering coverage",
            "acceptance_criteria": "guard ordering validation is wired",
            "verification": {
                "level": "integration",
                "command": "pytest tests/test_placeholder.py -q",
                "checks": [{
                    "name": "behavior",
                    "command": "pytest tests/test_placeholder.py -q",
                }],
                "covers": {"tasks": ["T1"]},
            },
        }],
    })


def _report_for_module(
    tmp_path: Path,
    *,
    rel_path: str,
    content: str,
    plan_scope: list[str] | None = None,
    claimed_paths: list[str] | None = None,
):
    _write(tmp_path, "tests/test_placeholder.py", "def test_placeholder() -> None:\n    assert True\n")
    _write(tmp_path, rel_path, content)
    return validate_with_project(
        _plan(
            claimed_paths=claimed_paths or [rel_path],
            plan_scope=plan_scope,
        ),
        project_root=tmp_path,
    )


def _issues(report) -> list:
    return [*report.errors, *report.warnings, *report.hints]


def _issue_codes(report) -> set[str]:
    return {issue.code for issue in _issues(report)}


def _issues_by_code(report, code: str) -> list:
    return [issue for issue in _issues(report) if issue.code == code]


def test_emit_before_guard_warns(tmp_path: Path) -> None:
    report = _report_for_module(
        tmp_path,
        rel_path="src/service.py",
        content=(
            "def complete_workflow() -> None:\n"
            "    engine.emit_workflow_terminal('wf-1')\n"
            "    if workflow_evaluation_empty_sections('project'):\n"
            "        return\n"
        ),
    )

    issues = _issues_by_code(report, W_GUARD_AFTER_SIDE_EFFECT)

    assert W_GUARD_AFTER_SIDE_EFFECT in _issue_codes(report)
    assert len(issues) == 1
    assert issues[0].evidence["side_effect_call"] == "emit_workflow_terminal"
    assert issues[0].evidence["guard_call"] == "workflow_evaluation_empty_sections"
    assert issues[0].evidence["guard_lineno"] > issues[0].evidence["side_effect_lineno"]


def test_guard_before_emit_is_not_reported(tmp_path: Path) -> None:
    report = _report_for_module(
        tmp_path,
        rel_path="src/service.py",
        content=(
            "def complete_workflow() -> None:\n"
            "    if workflow_evaluation_empty_sections('project'):\n"
            "        return\n"
            "    engine.emit_workflow_terminal('wf-1')\n"
        ),
    )

    assert W_GUARD_AFTER_SIDE_EFFECT not in _issue_codes(report)


def test_claimed_src_file_is_scanned_even_when_plan_scope_is_empty(tmp_path: Path) -> None:
    report = _report_for_module(
        tmp_path,
        rel_path="src/claimed_only.py",
        content=(
            "def complete_workflow() -> None:\n"
            "    engine.emit_workflow_terminal('wf-1')\n"
            "    if workflow_evaluation_empty_sections('project'):\n"
            "        return\n"
        ),
        plan_scope=[],
        claimed_paths=["src/claimed_only.py"],
    )

    assert W_GUARD_AFTER_SIDE_EFFECT in _issue_codes(report)


def test_emit_without_mapped_guard_is_not_reported(tmp_path: Path) -> None:
    report = _report_for_module(
        tmp_path,
        rel_path="src/service.py",
        content=(
            "def complete_workflow() -> None:\n"
            "    engine.emit_workflow_terminal('wf-1')\n"
        ),
    )

    assert W_GUARD_AFTER_SIDE_EFFECT not in _issue_codes(report)


def test_real_complete_workflow_order_is_not_reported() -> None:
    report = validate_with_project(
        _plan(
            claimed_paths=[REAL_ORCHESTRATOR_PATH],
            plan_scope=[REAL_ORCHESTRATOR_PATH],
        ),
        project_root=REPO_ROOT,
    )

    assert W_GUARD_AFTER_SIDE_EFFECT not in _issue_codes(report)
