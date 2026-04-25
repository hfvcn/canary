from __future__ import annotations

import io
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import yaml

from cccc.ralph.agent import RULE_DOCS
from cccc.ralph.cli import main as ralph_main
from cccc.ralph.plan_io import load_plan
from cccc.ralph.validator import validate_with_project


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _plan_payload() -> dict:
    return {
        "schema_version": "1.0.0",
        "tasks": [{
            "id": "T1",
            "claimed_paths": ["src/feature.py", "src/registry.py"],
            "acceptance_criteria": "feature validated",
            "verification": {
                "level": "unit",
                "command": "pytest tests/test_feature.py -q",
                "covers": {
                    "tasks": ["T1"],
                    "flows": ["ghost-flow"],
                },
            },
        }],
        "critical_flows": [
            {"id": "dup-flow", "entrypoints": ["src/feature.py"]},
            {"id": "dup-flow", "entrypoints": ["src/feature.py"]},
            {"id": "no-entry"},
        ],
        "forbidden_flows": [
            {"id": "deny", "description": "forbid"},
            {"id": "deny", "description": "forbid"},
        ],
        "registration_invariants": [
            {"name": "inv-dup", "registry_file": "src/registry.py"},
            {"name": "inv-dup", "registry_file": "src/registry.py"},
            {"name": "inv-unused", "registry_file": "src/unclaimed.py"},
        ],
        "suppress_codes": ["W_NOT_EMITTED"],
        "state": {"completed_task_ids": ["T-missing"]},
    }


def _capture(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
        rc = ralph_main(argv)
    return rc, stdout.getvalue(), stderr.getvalue()


def test_wave6_fixture_emits_each_new_rule_once_and_banner(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "feature.py", "VALUE = 1\n")
    _write(tmp_path / "src" / "registry.py", "REGISTRY = []\n")
    _write(tmp_path / "tests" / "test_feature.py", "def test_feature():\n    assert True\n")
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(yaml.safe_dump(_plan_payload(), sort_keys=False), encoding="utf-8")

    report = validate_with_project(load_plan(plan_path), project_root=tmp_path)
    counts = Counter(issue.code for issue in [*report.errors, *report.warnings, *report.hints])

    for code in [
        "E_COVERS_UNKNOWN_FLOW",
        "W_STATE_UNKNOWN_TASK_REF",
        "E_DUPLICATE_FLOW_ID",
        "E_DUPLICATE_FORBIDDEN_FLOW_ID",
        "E_DUPLICATE_INVARIANT_NAME",
        "W_CRITICAL_FLOW_NO_ENTRYPOINTS",
        "H_SUPPRESS_UNUSED",
        "W_PLAN_SCOPE_UNUSED",
        "W_COVERS_PATHS_UNVERIFIED",
    ]:
        assert counts[code] == 1, f"{code} expected exactly once, got {counts[code]}"

    rc, stdout, stderr = _capture(
        ["validate", str(plan_path), "--format", "text", "--project-root", str(tmp_path)]
    )

    assert rc == 1
    assert stderr.startswith("Resolved project root:")
    first_line = next(line for line in stdout.splitlines() if line.strip())
    assert first_line.startswith("Validation:")


def test_wave6_explain_has_docs_for_every_new_rule_code() -> None:
    for code in [
        "E_COVERS_UNKNOWN_FLOW",
        "W_STATE_UNKNOWN_TASK_REF",
        "E_DUPLICATE_FLOW_ID",
        "E_DUPLICATE_FORBIDDEN_FLOW_ID",
        "E_DUPLICATE_INVARIANT_NAME",
        "W_CRITICAL_FLOW_NO_ENTRYPOINTS",
        "H_SUPPRESS_UNUSED",
        "W_PLAN_SCOPE_UNUSED",
        "W_COVERS_PATHS_UNVERIFIED",
    ]:
        assert code in RULE_DOCS
        rc, stdout, stderr = _capture(["explain", "--code", code])
        assert rc == 0
        assert stderr == ""
        assert f"--- {code} ---" in stdout
        assert "Description:" in stdout
