from __future__ import annotations

from pathlib import Path

from cccc.ralph.models import Plan
from cccc.ralph.validation_rules import __all__ as validation_rules_all
from cccc.ralph.validation_rules import (
    W_VERIFICATION_NO_MAIN_PATH_COMMAND,
    _check_verification_main_path_command,
    get_all_rules,
)
from cccc.ralph.validation_rules.coverage import _is_main_path_command
from cccc.ralph.validator import validate_with_project


def _write(tmp_path: Path, rel_path: str, content: str) -> None:
    file_path = tmp_path / rel_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")


def _default_content(rel_path: str) -> str:
    if rel_path.endswith(".py"):
        return "VALUE = 1\n"
    if rel_path.endswith(".log"):
        return "execution_engine: af\n"
    if rel_path.endswith(".yaml"):
        return "tasks: []\n"
    return "\n"


def _seed_project(tmp_path: Path, extra_paths: list[str] | None = None) -> None:
    base_paths = [
        "src/runtime.py",
        "src/critical_entry.py",
        "tests/test_x.py",
        "tests/x.py",
        "tests/ralph/test_x.py",
        "daemon.log",
        "plan.yaml",
    ]
    for rel_path in [*base_paths, *(extra_paths or [])]:
        _write(tmp_path, rel_path, _default_content(rel_path))


def _check(command: str, *, required: bool = True) -> dict:
    return {
        "name": "check",
        "required": required,
        "command": command,
    }


def _task(
    *,
    task_id: str = "T1",
    role: str = "leaf",
    level: str = "unit",
    claimed_paths: list[str] | None = None,
    top_command: str = "",
    checks: list[dict] | None = None,
    cover_flow_ids: list[str] | None = None,
) -> dict:
    return {
        "id": task_id,
        "role": role,
        "claimed_paths": claimed_paths or ["src/runtime.py"],
        "goal_behavior": "validate runtime behavior evidence",
        "acceptance_criteria": "runtime behavior evidence is validated",
        "verification": {
            "level": level,
            "command": top_command,
            "checks": checks or [],
            "covers": {"flows": cover_flow_ids or []},
        },
    }


def _plan(task: dict, *, critical_flows: list[dict] | None = None) -> Plan:
    return Plan.model_validate({
        "plan_scope": ["src", "tests"],
        "tasks": [task],
        "critical_flows": critical_flows or [],
    })


def _report(tmp_path: Path, task: dict, *, critical_flows: list[dict] | None = None):
    extra_paths = list(task["claimed_paths"])
    for flow in critical_flows or []:
        extra_paths.extend(flow.get("entrypoints", []))
    _seed_project(tmp_path, extra_paths)
    return validate_with_project(
        _plan(task, critical_flows=critical_flows),
        project_root=tmp_path,
    )


def _issues(report) -> list:
    return [*report.errors, *report.warnings, *report.hints]


def _issue_codes(report) -> set[str]:
    return {issue.code for issue in _issues(report)}


def _issues_by_code(report, code: str) -> list:
    return [issue for issue in _issues(report) if issue.code == code]


def test_integration_pytest_only_warns(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        _task(
            role="integration",
            level="integration",
            checks=[_check("python -m pytest tests/test_x.py")],
        ),
    )
    issues = _issues_by_code(report, W_VERIFICATION_NO_MAIN_PATH_COMMAND)

    assert W_VERIFICATION_NO_MAIN_PATH_COMMAND in _issue_codes(report)
    assert len(issues) == 1
    assert issues[0].evidence["task_id"] == "T1"


def test_e2e_pytest_only_warns(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        _task(
            role="leaf",
            level="e2e",
            checks=[_check("python -m pytest tests/test_x.py")],
        ),
    )

    assert W_VERIFICATION_NO_MAIN_PATH_COMMAND in _issue_codes(report)


def test_critical_flow_pytest_only_warns(tmp_path: Path) -> None:
    critical_flows = [{"id": "daemon_flow", "entrypoints": ["src/runtime.py"]}]
    report = _report(
        tmp_path,
        _task(
            level="integration",
            checks=[_check("python -m pytest tests/test_x.py")],
            cover_flow_ids=["daemon_flow"],
        ),
        critical_flows=critical_flows,
    )
    issues = _issues_by_code(report, W_VERIFICATION_NO_MAIN_PATH_COMMAND)

    assert W_VERIFICATION_NO_MAIN_PATH_COMMAND in _issue_codes(report)
    assert issues[0].evidence["covered_critical_flows"] == ["daemon_flow"]


def test_claimed_critical_entrypoint_triggers_warn(tmp_path: Path) -> None:
    critical_flows = [{"id": "entry_flow", "entrypoints": ["src/critical_entry.py"]}]
    report = _report(
        tmp_path,
        _task(
            role="leaf",
            level="integration",
            claimed_paths=["src/critical_entry.py"],
            checks=[_check("python -m pytest tests/test_x.py")],
        ),
        critical_flows=critical_flows,
    )
    issues = _issues_by_code(report, W_VERIFICATION_NO_MAIN_PATH_COMMAND)

    assert W_VERIFICATION_NO_MAIN_PATH_COMMAND in _issue_codes(report)
    assert issues[0].evidence["covered_critical_flows"] == ["entry_flow"]


def test_cccc_cli_check_is_accepted(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        _task(
            role="integration",
            level="integration",
            checks=[_check("cccc model suggest backend")],
        ),
    )

    assert W_VERIFICATION_NO_MAIN_PATH_COMMAND not in _issue_codes(report)


def test_ralph_cli_check_is_accepted(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        _task(
            role="integration",
            level="integration",
            checks=[_check("ralph validate plan.yaml --no-agent")],
        ),
    )

    assert W_VERIFICATION_NO_MAIN_PATH_COMMAND not in _issue_codes(report)


def test_log_grep_check_is_accepted(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        _task(
            role="integration",
            level="integration",
            checks=[_check('grep "execution_engine: af" daemon.log')],
        ),
    )

    assert W_VERIFICATION_NO_MAIN_PATH_COMMAND not in _issue_codes(report)


def test_wrapper_commands_are_accepted(tmp_path: Path) -> None:
    commands = [
        "env A=B ralph validate plan.yaml",
        "timeout 30 ralph validate plan.yaml",
        "uv run ralph validate plan.yaml",
        "poetry run cccc model suggest backend",
        "env FOO=1 timeout 5 ralph validate plan.yaml",
    ]

    for command in commands:
        report = _report(
            tmp_path,
            _task(
                role="integration",
                level="integration",
                checks=[_check(command)],
            ),
        )
        assert W_VERIFICATION_NO_MAIN_PATH_COMMAND not in _issue_codes(report)


def test_wrapped_main_path_commands_are_accepted(tmp_path: Path) -> None:
    commands = [
        "bash -lc 'ralph flow next'",
        "sh -c 'cccc model suggest backend'",
    ]

    for command in commands:
        report = _report(
            tmp_path,
            _task(
                role="integration",
                level="integration",
                checks=[_check(command)],
            ),
        )
        assert W_VERIFICATION_NO_MAIN_PATH_COMMAND not in _issue_codes(report)


def test_wrapped_log_assertion_is_accepted(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        _task(
            role="integration",
            level="integration",
            checks=[_check("bash -lc 'grep foo /tmp/run.log'")],
        ),
    )

    assert W_VERIFICATION_NO_MAIN_PATH_COMMAND not in _issue_codes(report)


def test_pytest_path_with_ralph_substring_still_warns(tmp_path: Path) -> None:
    commands = [
        "python -m pytest tests/ralph/test_x.py",
        "bash -lc 'python -m pytest tests/ralph/test_x.py'",
    ]

    for command in commands:
        report = _report(
            tmp_path,
            _task(
                role="integration",
                level="integration",
                checks=[_check(command)],
            ),
        )
        assert W_VERIFICATION_NO_MAIN_PATH_COMMAND in _issue_codes(report)


def test_top_level_command_is_ignored_when_checks_exist(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        _task(
            role="integration",
            level="integration",
            top_command="ralph validate plan.yaml",
            checks=[_check("python -m pytest tests/x.py")],
        ),
    )

    assert W_VERIFICATION_NO_MAIN_PATH_COMMAND in _issue_codes(report)


def test_only_required_checks_count(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        _task(
            role="integration",
            level="integration",
            checks=[
                _check("cccc model suggest backend", required=False),
                _check("python -m pytest tests/x.py"),
            ],
        ),
    )

    assert W_VERIFICATION_NO_MAIN_PATH_COMMAND in _issue_codes(report)


def test_non_runtime_leaf_task_does_not_warn(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        _task(
            role="leaf",
            level="integration",
            checks=[_check("python -m pytest tests/test_x.py")],
        ),
    )

    assert W_VERIFICATION_NO_MAIN_PATH_COMMAND not in _issue_codes(report)


def test_direct_main_path_detection_handles_subshell_and_wrapped_log_assertions() -> None:
    assert _is_main_path_command("( ralph validate plan.yaml --no-agent )")
    assert _is_main_path_command("bash -lc 'grep foo /tmp/run.log'")


def test_direct_main_path_detection_safe_degrades_complex_shell() -> None:
    commands = [
        "bash -lc 'if true; then ralph x; fi'",
        "bash -lc 'ralph flow next $(whoami)'",
        "bash -lc 'cat <<EOF\nralph flow next\nEOF'",
        "bash -lc 'ralph flow next",
    ]

    for command in commands:
        assert _is_main_path_command(command) is False


def test_rule_is_registered_and_exported() -> None:
    assert _check_verification_main_path_command in get_all_rules()
    assert "_check_verification_main_path_command" in validation_rules_all
    assert "W_VERIFICATION_NO_MAIN_PATH_COMMAND" in validation_rules_all
