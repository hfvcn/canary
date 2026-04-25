from __future__ import annotations

from pathlib import Path

from cccc.ralph.models import Plan
from cccc.ralph.validator import validate_with_project


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _plan(command: str) -> Plan:
    return Plan.model_validate({
        "tasks": [{
            "id": "T1",
            "claimed_paths": ["calc.py"],
            "verification": {
                "level": "unit",
                "checks": [{
                    "name": "inline-check",
                    "command": command,
                }],
                "covers": {"tasks": ["T1"]},
            },
        }],
    })


def _issues_by_code(report, code: str) -> list:
    return [issue for issue in [*report.errors, *report.warnings, *report.hints] if issue.code == code]


def test_python_c_assert_flagged(tmp_path: Path) -> None:
    _write(tmp_path / "calc.py", "def add(a, b):\n    return a + b\n")

    plan = _plan('python -c "import calc; assert calc.add(2,3)==5"')
    report = validate_with_project(plan, project_root=tmp_path)

    assert _issues_by_code(report, "H_INLINE_ASSERTIONS")


def test_python_c_import_only_ok(tmp_path: Path) -> None:
    _write(tmp_path / "calc.py", "VALUE = 1\n")

    plan = _plan('python -c "import calc"')
    report = validate_with_project(plan, project_root=tmp_path)

    assert _issues_by_code(report, "H_INLINE_ASSERTIONS") == []
