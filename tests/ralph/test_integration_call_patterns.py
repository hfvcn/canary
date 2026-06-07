from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from cccc.ralph.validation_rules.coverage import (
    W_INTEGRATION_IMPORT_ONLY_NO_CALL,
    _check_integration_call_evidence,
)


def _plan(*tasks: SimpleNamespace, plan_scope: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(tasks=list(tasks), plan_scope=plan_scope or [])


def _task(
    task_id: str,
    *,
    role: str = "integration",
    title: str = "",
    goal_behavior: str = "",
    claimed_paths: list[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=task_id,
        role=role,
        title=title,
        goal_behavior=goal_behavior,
        claimed_paths=claimed_paths or [],
    )


def _write(tmp_path: Path, rel_path: str, content: str) -> None:
    file_path = tmp_path / rel_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")


def _issue_codes(issues) -> set[str]:
    return {issue.code for issue in issues}


def test_import_plus_function_call_is_strong_evidence(tmp_path: Path) -> None:
    _write(tmp_path, "src/integration_mod.py", "def install() -> None:\n    pass\n")
    _write(tmp_path, "src/main.py", "from integration_mod import install\ninstall()\n")
    plan = _plan(
        _task("T1", claimed_paths=["src/integration_mod.py"]),
        plan_scope=["src"],
    )

    issues = _check_integration_call_evidence(plan, project_root=tmp_path)
    codes = _issue_codes(issues)

    assert W_INTEGRATION_IMPORT_ONLY_NO_CALL not in codes
    assert "W_INTEGRATION_NO_PRODUCTION_CALL_EVIDENCE" not in codes


def test_import_only_triggers_import_only_advisory(tmp_path: Path) -> None:
    _write(tmp_path, "src/integration_mod.py", "def install() -> None:\n    pass\n")
    _write(tmp_path, "src/main.py", "import integration_mod\n")
    plan = _plan(
        _task("T1", claimed_paths=["src/integration_mod.py"]),
        plan_scope=["src"],
    )

    issues = _check_integration_call_evidence(plan, project_root=tmp_path)
    codes = _issue_codes(issues)

    assert W_INTEGRATION_IMPORT_ONLY_NO_CALL in codes
    assert "W_INTEGRATION_NO_PRODUCTION_CALL_EVIDENCE" not in codes


def test_registration_call_remains_strong_evidence(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/integration_mod.py",
        "handler = object()\nregister_handler(handler)\n",
    )
    plan = _plan(
        _task("T1", claimed_paths=["src/integration_mod.py"]),
        plan_scope=["src"],
    )

    issues = _check_integration_call_evidence(plan, project_root=tmp_path)
    codes = _issue_codes(issues)

    assert W_INTEGRATION_IMPORT_ONLY_NO_CALL not in codes
    assert "W_INTEGRATION_NO_PRODUCTION_CALL_EVIDENCE" not in codes


def test_no_import_no_call_keeps_existing_warning(tmp_path: Path) -> None:
    _write(tmp_path, "src/integration_mod.py", "def install() -> None:\n    pass\n")
    _write(tmp_path, "src/main.py", "VALUE = 1\n")
    plan = _plan(
        _task("T1", claimed_paths=["src/integration_mod.py"]),
        plan_scope=["src"],
    )

    issues = _check_integration_call_evidence(plan, project_root=tmp_path)
    codes = _issue_codes(issues)

    assert W_INTEGRATION_IMPORT_ONLY_NO_CALL not in codes
    assert "W_INTEGRATION_NO_PRODUCTION_CALL_EVIDENCE" in codes
