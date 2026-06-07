from __future__ import annotations

import os
from pathlib import Path

from cccc.ralph import validation_rules
from cccc.ralph.models import Plan
from cccc.ralph.validation_rules import (
    W_SEMANTIC_DEFAULT_PARTIAL_UPDATE,
    _check_semantic_default_consistency,
    get_all_rules,
)
from cccc.ralph.validation_rules.semantic_defaults import (
    SEMANTIC_DEFAULT_GROUPS,
    SemanticDefaultGroup,
    SKIP_REASON_NO_CONTEXT,
    W_SEMANTIC_DEFAULT_VALUE_DRIFT,
    _audit_semantic_default_group,
    _extract_runtime_default_values,
)
from cccc.ralph.validator import validate_with_project


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXECUTOR_RUNTIME_DEFINITIONS = [
    "src/cccc/daemon/foreman/agent_pool.py",
    "src/cccc/daemon/foreman/assignment_actor_registration.py",
    "src/cccc/daemon/ops/agent_ops.py",
    "src/cccc/kernel/actors.py",
    "src/cccc/daemon/actors/actor_add_ops.py",
]
AGENT_OPS_DEFINITION = "src/cccc/daemon/ops/agent_ops.py"


def _write_files(root: Path, rel_paths: list[str]) -> None:
    for rel_path in rel_paths:
        path = root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("DEFAULT_RUNTIME = 'codex'\n", encoding="utf-8")


def _task(task_id: str, claimed_paths: list[str]) -> dict[str, object]:
    return {
        "id": task_id,
        "title": f"task {task_id}",
        "claimed_paths": claimed_paths,
        "goal_behavior": "keep semantic defaults synchronized",
        "acceptance_criteria": "semantic default heuristic behaves correctly",
    }


def _plan(tasks: list[dict[str, object]]) -> Plan:
    return Plan.model_validate({"tasks": tasks})


def _issues(report) -> list:
    return [*report.errors, *report.warnings, *report.hints]


def _issues_by_code(report, code: str) -> list:
    return [issue for issue in _issues(report) if issue.code == code]


def _write_source(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _single_definition_group(definition: str) -> SemanticDefaultGroup:
    return {
        "name": "executor_runtime",
        "canonical": "codex",
        "definitions": [definition],
    }


def test_runtime_default_extractor_ignores_docstrings_and_assignments() -> None:
    values = _extract_runtime_default_values(
        '''
def build(runtime="claude"):
    """docstring mentions claude but is not a default context"""
    note = "claude"
    current = runtime or "claude"
    payload = {}
    return current, payload.get("runtime", "claude"), note
''',
    )

    assert values.count("claude") == 3
    assert len(values) == 3


def test_value_drift_reports_non_canonical_fixture_without_validator(tmp_path: Path) -> None:
    _write_source(
        tmp_path / AGENT_OPS_DEFINITION,
        '''
def load(runtime="claude"):
    payload = {}
    return runtime, payload.get("runtime", "claude")
''',
    )

    audit = _audit_semantic_default_group(
        _single_definition_group(AGENT_OPS_DEFINITION),
        project_root=tmp_path,
    )
    issues = audit["issues"]

    assert len(issues) == 1
    assert issues[0].code == W_SEMANTIC_DEFAULT_VALUE_DRIFT
    assert issues[0].evidence["file"] == AGENT_OPS_DEFINITION
    assert issues[0].evidence["found_values"] == ["claude"]


def test_all_canonical_fixture_has_no_value_drift(tmp_path: Path) -> None:
    _write_source(
        tmp_path / AGENT_OPS_DEFINITION,
        '''
def load(runtime="codex"):
    payload = {}
    current = runtime or "codex"
    return current, payload.pop("model_runtime", "codex")
''',
    )

    audit = _audit_semantic_default_group(
        _single_definition_group(AGENT_OPS_DEFINITION),
        project_root=tmp_path,
    )

    assert audit["issues"] == []
    assert audit["skipped"] == []


def test_no_runtime_default_context_is_skipped_without_warning(tmp_path: Path) -> None:
    _write_source(
        tmp_path / AGENT_OPS_DEFINITION,
        '''
"""claude only appears in documentation"""

DEFAULT_RUNTIME = "claude"

def load(value="claude"):
    return value
''',
    )

    audit = _audit_semantic_default_group(
        _single_definition_group(AGENT_OPS_DEFINITION),
        project_root=tmp_path,
    )

    assert audit["issues"] == []
    assert len(audit["skipped"]) == 1
    assert audit["skipped"][0]["file"] == AGENT_OPS_DEFINITION
    assert audit["skipped"][0]["reason"] == SKIP_REASON_NO_CONTEXT


def test_value_drift_stays_dormant_without_project_root() -> None:
    issues = _check_semantic_default_consistency(
        _plan([_task("T1", [AGENT_OPS_DEFINITION])]),
        project_root=None,
    )

    assert [issue.code for issue in issues] == [W_SEMANTIC_DEFAULT_PARTIAL_UPDATE]


def test_partial_update_warns_via_validate_with_project(tmp_path: Path) -> None:
    touched = EXECUTOR_RUNTIME_DEFINITIONS[0]
    _write_files(tmp_path, [touched])

    report = validate_with_project(
        _plan([_task("T1", [touched])]),
        project_root=tmp_path,
    )
    issues = _issues_by_code(report, W_SEMANTIC_DEFAULT_PARTIAL_UPDATE)

    assert len(issues) == 1
    issue = issues[0]
    assert issue.task_ids == ["T1"]
    assert issue.evidence["group"] == "executor_runtime"
    assert issue.evidence["canonical"] == "codex"
    assert issue.evidence["touched"] == [touched]
    assert set(issue.evidence["missing"]) == set(EXECUTOR_RUNTIME_DEFINITIONS[1:])


def test_touching_all_definition_files_does_not_warn(tmp_path: Path) -> None:
    _write_files(tmp_path, EXECUTOR_RUNTIME_DEFINITIONS)

    report = validate_with_project(
        _plan([
            _task("T1", ["src/cccc/daemon/foreman"]),
            _task("T2", EXECUTOR_RUNTIME_DEFINITIONS[2:]),
        ]),
        project_root=tmp_path,
    )

    assert _issues_by_code(report, W_SEMANTIC_DEFAULT_PARTIAL_UPDATE) == []


def test_unrelated_paths_do_not_warn(tmp_path: Path) -> None:
    _write_files(tmp_path, ["src/unrelated.py"])

    report = validate_with_project(
        _plan([_task("T1", ["src/unrelated.py"])]),
        project_root=tmp_path,
    )

    assert _issues_by_code(report, W_SEMANTIC_DEFAULT_PARTIAL_UPDATE) == []


def test_real_repo_definition_files_have_no_agent_ops_value_drift() -> None:
    audit = _audit_semantic_default_group(
        SEMANTIC_DEFAULT_GROUPS[0],
        project_root=PROJECT_ROOT,
    )

    assert audit["skipped"] == []
    assert audit["issues"] == []


def test_registry_points_to_real_verified_definition_files() -> None:
    group = SEMANTIC_DEFAULT_GROUPS[0]

    assert group["name"] == "executor_runtime"
    assert group["canonical"] == "codex"
    assert group["definitions"] == EXECUTOR_RUNTIME_DEFINITIONS
    for rel_path in group["definitions"]:
        assert os.path.exists(PROJECT_ROOT / rel_path)


def test_rule_is_registered_and_exported() -> None:
    assert _check_semantic_default_consistency in get_all_rules()
    assert "_check_semantic_default_consistency" in validation_rules.__all__
    assert "W_SEMANTIC_DEFAULT_PARTIAL_UPDATE" in validation_rules.__all__
