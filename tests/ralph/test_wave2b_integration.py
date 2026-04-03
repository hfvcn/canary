"""Wave 2B integration tests — verify new validator rules interact correctly."""

from __future__ import annotations

from pathlib import Path

from cccc.ralph.models import Plan
from cccc.ralph.validator import validate_with_project


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_wave2b_validate_with_project_combines_structural_and_fs_rules(tmp_path):
    _write(tmp_path / "src" / "cccc" / "demo.py", "VALUE = 1\n")
    _write(tmp_path / "src" / "cccc" / "feature.py", "VALUE = 2\n")
    _write(tmp_path / "src" / "cccc" / "adapter.py", "VALUE = 3\n")
    _write(tmp_path / "src" / "cccc" / "runner.py", "VALUE = 4\n")

    _write(tmp_path / "tests" / "test_demo.py", "from cccc.demo import VALUE\n")
    _write(tmp_path / "tests" / "conftest.py", "from cccc.feature import VALUE\n")
    _write(
        tmp_path / "tests" / "test_dynamic.py",
        "import importlib\n"
        "MODULE = importlib.import_module('cccc.adapter')\n",
    )
    _write(tmp_path / "tests" / "test_flow.py", "def test_flow():\n    assert True\n")

    plan = Plan.model_validate({
        "tasks": [
            {
                "id": "T1",
                "claimed_paths": ["src/cccc/demo.py"],
                "goal_behavior": "startup remains reachable",
                "acceptance_criteria": "startup remains reachable",
                "verification": {
                    "level": "unit",
                    "command": "python -m py_compile src/cccc/demo.py",
                    "covers": {"tasks": ["T1"]},
                },
            },
            {
                "id": "T2",
                "claimed_paths": ["src/cccc/feature.py"],
                "depends_on": ["T1"],
                "acceptance_criteria": "feature wiring stays valid",
                "verification": {
                    "level": "unit",
                    "command": "python -m py_compile src/cccc/feature.py",
                    "covers": {"tasks": ["T2"]},
                },
            },
            {
                "id": "T3",
                "claimed_paths": ["src/cccc/adapter.py"],
                "depends_on": ["T2"],
                "acceptance_criteria": "adapter wiring stays valid",
                "verification": {
                    "level": "unit",
                    "command": "python -m py_compile src/cccc/adapter.py",
                    "covers": {"tasks": ["T3"]},
                },
            },
            {
                "id": "T4",
                "claimed_paths": ["src/cccc/runner.py"],
                "depends_on": ["T3"],
                "acceptance_criteria": "runner wiring stays valid",
                "verification": {
                    "level": "unit",
                    "command": "python -m py_compile src/cccc/runner.py",
                    "covers": {"tasks": ["T4"]},
                },
            },
            {
                "id": "T5",
                "claimed_paths": ["tests/test_flow.py"],
                "depends_on": ["T4"],
                "acceptance_criteria": "full flow remains green",
                "verification": {
                    "level": "integration",
                    "command": "pytest tests/test_flow.py -q",
                    "covers": {"tasks": ["T1", "T4", "T5"]},
                },
            },
        ],
    })

    report = validate_with_project(plan, project_root=tmp_path)

    warning_codes = [issue.code for issue in report.warnings]
    hint_codes = [issue.code for issue in report.hints]

    assert "W_TEST_COVERAGE_GAP" in warning_codes
    assert "W_CONFTEST_COVERAGE_GAP" in warning_codes
    # W_COVERS_CLAIM_UNVERIFIABLE skipped for integration/e2e level tasks
    assert "W_NO_EARLY_INTEGRATION_CHECKPOINT" in warning_codes
    assert "W_DYNAMIC_TEST_IMPORT_OPAQUE" in hint_codes
    assert "W_VERIFICATION_BEHAVIOR_MISMATCH" in hint_codes
    assert "W_VERIFICATION_BEHAVIOR_MISMATCH" not in warning_codes
