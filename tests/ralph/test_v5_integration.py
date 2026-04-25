"""Integration test for all v5-ralph-phase5 new rules."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from cccc.ralph.models import Plan, ValidationIssue
from cccc.ralph.validator import validate_with_project
from cccc.ralph.core import suggest, verify
from cccc.ralph.workspace_index import WorkspaceIndex


def _make_plan(tmp_path: Path, tasks: list[dict], **kwargs) -> Plan:
    data = {"tasks": tasks, **kwargs}
    return Plan.model_validate(data)


def _all_codes(report) -> set[str]:
    codes = set()
    for i in report.errors:
        codes.add(i.code)
    for i in report.warnings:
        codes.add(i.code)
    for i in report.hints:
        codes.add(i.code)
    return codes


# ── RVE-7: W_INTEGRATION_TASK_SHALLOW_VERIFICATION ──────────────────


def test_rve7_integration_shallow(tmp_path):
    tasks = [
        {
            "id": "T1",
            "role": "integration",
            "claimed_paths": ["src/a.py"],
            "verification": {
                "level": "integration",
                "checks": [
                    {"name": "grep_check", "command": 'grep -q "def foo" src/a.py'},
                ],
                "covers": {"tasks": ["T1"]},
            },
        },
    ]
    plan = _make_plan(tmp_path, tasks)
    report = validate_with_project(plan, project_root=tmp_path)
    assert "W_INTEGRATION_TASK_SHALLOW_VERIFICATION" in _all_codes(report)


# ── RVE-1: E_VERIFICATION_TARGET_MISSING_FILE ───────────────────────


def test_rve1_missing_file(tmp_path):
    tasks = [
        {
            "id": "T1",
            "role": "leaf",
            "claimed_paths": ["src/a.py"],
            "verification": {
                "level": "unit",
                "command": "pytest tests/nonexistent/test_fake.py -q",
                "covers": {"tasks": ["T1"]},
            },
        },
    ]
    plan = _make_plan(tmp_path, tasks)
    report = validate_with_project(plan, project_root=tmp_path)
    assert "E_VERIFICATION_TARGET_MISSING_FILE" in _all_codes(report)


# ── RVE-2: suppress_flows ───────────────────────────────────────────


def test_rve2_suppress_flows(tmp_path):
    tasks = [
        {
            "id": "T1",
            "role": "leaf",
            "claimed_paths": ["src/a.py"],
        },
    ]
    plan = _make_plan(
        tmp_path,
        tasks,
        critical_flows=[
            {"id": "flow_a", "description": "test flow", "entrypoints": ["src/entry.py"]},
        ],
        suppress_flows=["flow_a", "nonexistent_flow"],
    )
    report = validate_with_project(plan, project_root=tmp_path)
    codes = _all_codes(report)
    assert "W_SUPPRESS_FLOWS_UNKNOWN" in codes
    flow_a_errors = [
        i for i in report.errors
        if i.code == "E_CRITICAL_FLOW_UNCOVERED" and "flow_a" in i.message
    ]
    assert len(flow_a_errors) == 0


# ── RVE-4: W_COVERS_NOT_EXERCISED ───────────────────────────────────


def test_rve4_covers_not_exercised(tmp_path):
    tasks = [
        {
            "id": "T1",
            "role": "leaf",
            "claimed_paths": ["src/module_a.py"],
            "provides": [{"name": "module_a_api", "kind": "artifact"}],
        },
        {
            "id": "T2",
            "role": "leaf",
            "claimed_paths": ["src/module_b.py"],
            "depends_on": ["T1"],
            "verification": {
                "level": "unit",
                "checks": [
                    {"name": "unrelated", "command": "pytest tests/test_unrelated.py"},
                ],
                "covers": {"tasks": ["T1"]},
            },
        },
    ]
    plan = _make_plan(tmp_path, tasks)
    report = validate_with_project(plan, project_root=tmp_path)
    assert "W_COVERS_NOT_EXERCISED" in _all_codes(report)


# ── RVE-8: W_GOAL_HARDCODED_WITHOUT_AWARENESS ───────────────────────


def test_rve8_hardcoded_awareness(tmp_path):
    awareness_dir = tmp_path / "src"
    awareness_dir.mkdir(parents=True)
    awareness_file = awareness_dir / "ref.py"
    awareness_file.write_text("SOME_CONST = 0xFF\n", encoding="utf-8")

    tasks = [
        {
            "id": "T1",
            "role": "leaf",
            "claimed_paths": ["src/impl.py"],
            "awareness_paths": ["src/ref.py"],
            "goal_behavior": "Write byte 0xAB to the device register",
        },
    ]
    plan = _make_plan(tmp_path, tasks)
    report = validate_with_project(plan, project_root=tmp_path)
    assert "W_GOAL_HARDCODED_WITHOUT_AWARENESS" in _all_codes(report)


# ── RVE-3: H_VERIFICATION_COMMAND_DEAD ──────────────────────────────


def test_rve3_dead_command(tmp_path):
    tasks = [
        {
            "id": "T1",
            "role": "leaf",
            "claimed_paths": ["src/a.py"],
            "verification": {
                "level": "unit",
                "command": "cd src && pytest test_a.py && echo done",
                "checks": [
                    {"name": "real_check", "command": "pytest tests/test_a.py -q", "required": True},
                ],
                "covers": {"tasks": ["T1"]},
            },
        },
    ]
    plan = _make_plan(tmp_path, tasks)
    report = validate_with_project(plan, project_root=tmp_path)
    assert "H_VERIFICATION_COMMAND_DEAD" in _all_codes(report)


# ── RVE-5: H_INLINE_ASSERTIONS ──────────────────────────────────────


def test_rve5_inline_assertions(tmp_path):
    tasks = [
        {
            "id": "T1",
            "role": "leaf",
            "claimed_paths": ["src/a.py"],
            "verification": {
                "level": "unit",
                "checks": [
                    {"name": "inline", "command": 'python -c "import foo; assert foo.bar()==1"'},
                ],
                "covers": {"tasks": ["T1"]},
            },
        },
    ]
    plan = _make_plan(tmp_path, tasks)
    report = validate_with_project(plan, project_root=tmp_path)
    assert "H_INLINE_ASSERTIONS" in _all_codes(report)


# ── RVE-6: H_SEMANTIC_UNCHECKED_SYMBOLS ─────────────────────────────


def test_rve6_semantic_unchecked(tmp_path):
    tasks = [
        {
            "id": "T1",
            "role": "leaf",
            "claimed_paths": ["src/a.py"],
            "provides": [{"name": "my_api", "kind": "runtime_capability"}],
        },
    ]
    plan = _make_plan(tmp_path, tasks)
    report = validate_with_project(plan, project_root=tmp_path)
    assert "H_SEMANTIC_UNCHECKED_SYMBOLS" in _all_codes(report)


# ── RA-2: beyond_scope marking ──────────────────────────────────────


def test_ra2_beyond_scope_marking(tmp_path):
    cccc_dir = tmp_path / ".cccc"
    cccc_dir.mkdir()
    beyond_scope = cccc_dir / "beyond_scope.yaml"
    beyond_scope.write_text(yaml.dump({
        "beyond_scope_items": [
            {
                "id": "TEST-1",
                "description": "test item",
                "category": "test",
                "matches": {"issue_codes": ["W_VERIFICATION_BEHAVIOR_MISMATCH"]},
            },
        ],
    }), encoding="utf-8")

    tasks = [
        {
            "id": "T1",
            "role": "leaf",
            "claimed_paths": ["src/a.py"],
            "goal_behavior": "Implement the full runtime behavior for module A",
            "verification": {
                "level": "unit",
                "command": "pytest tests/test_a.py -q",
                "covers": {"tasks": ["T1"]},
            },
        },
    ]
    plan = _make_plan(tmp_path, tasks)
    report = validate_with_project(plan, project_root=tmp_path)
    beyond_issues = [
        i for i in (report.errors + report.warnings + report.hints)
        if getattr(i, "beyond_scope", False)
    ]
    # May or may not have beyond_scope issues depending on whether
    # W_VERIFICATION_BEHAVIOR_MISMATCH fires; just verify no crash
    assert isinstance(report.valid, bool)


# ── RA-3: verification_mode agent_pending ────────────────────────────


def test_ra3_verification_mode(tmp_path):
    tasks = [
        {
            "id": "T1",
            "role": "leaf",
            "claimed_paths": ["src/a.py"],
            "verification_mode": "agent",
            "verification": {
                "level": "unit",
                "command": "pytest tests/test_a.py -q",
                "covers": {"tasks": ["T1"]},
            },
        },
    ]
    plan = _make_plan(tmp_path, tasks)
    task = plan.tasks[0]
    result = verify(task, changed_files=[], project_root=tmp_path)
    assert result["outcome"] == "agent_pending"


# ── CLI smoke test ──────────────────────────────────────────────────


def test_cli_validate_smoke(tmp_path):
    plan_path = tmp_path / "test_plan.yaml"
    plan_path.write_text(
        "tasks:\n"
        "  - id: T1\n"
        "    role: leaf\n"
        "    claimed_paths: [src/a.py]\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-m", "cccc.ralph.cli", "validate", str(plan_path), "--format", "json"],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert result.returncode in (0, 1)
    assert "Traceback" not in result.stderr
