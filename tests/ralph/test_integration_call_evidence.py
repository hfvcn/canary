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


def test_production_callable_usage_counts_as_call_evidence(tmp_path: Path) -> None:
    _write(tmp_path, "src/integration_mod.py", "router = object()\n")
    _write(tmp_path, "src/main.py", "from integration_mod import router\ninclude_router(router)\n")
    plan = _plan(
        _task("T1", claimed_paths=["src/integration_mod.py"]),
        plan_scope=["src"],
    )

    issues = _check_integration_call_evidence(plan, project_root=tmp_path)

    assert W_INTEGRATION_IMPORT_ONLY_NO_CALL not in _issue_codes(issues)
    assert "W_INTEGRATION_NO_PRODUCTION_CALL_EVIDENCE" not in _issue_codes(issues)


def test_test_only_import_triggers_warning(tmp_path: Path) -> None:
    _write(tmp_path, "src/integration_mod.py", "def install() -> None:\n    pass\n")
    _write(tmp_path, "src/main.py", "VALUE = 1\n")
    _write(tmp_path, "tests/test_main.py", "import integration_mod\n")
    plan = _plan(
        _task("T1", claimed_paths=["src/integration_mod.py"]),
        plan_scope=["src", "tests"],
    )

    issues = _check_integration_call_evidence(plan, project_root=tmp_path)

    assert "W_INTEGRATION_NO_PRODUCTION_CALL_EVIDENCE" in _issue_codes(issues)


def test_registration_pattern_counts_as_call_evidence(tmp_path: Path) -> None:
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

    assert "W_INTEGRATION_NO_PRODUCTION_CALL_EVIDENCE" not in _issue_codes(issues)


def test_non_integration_task_is_skipped(tmp_path: Path) -> None:
    _write(tmp_path, "src/integration_mod.py", "VALUE = 1\n")
    _write(tmp_path, "src/main.py", "VALUE = 2\n")
    plan = _plan(
        _task("T1", role="leaf", claimed_paths=["src/integration_mod.py"]),
        plan_scope=["src"],
    )

    issues = _check_integration_call_evidence(plan, project_root=tmp_path)

    assert issues == []


def test_none_project_root_skips_check() -> None:
    plan = _plan(
        _task("T1", claimed_paths=["src/integration_mod.py"]),
        plan_scope=["src"],
    )

    issues = _check_integration_call_evidence(plan, project_root=None)

    assert issues == []
