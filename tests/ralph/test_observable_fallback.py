from __future__ import annotations

from pathlib import Path

from cccc.ralph.models import Plan
from cccc.ralph.validation_rules import W_SILENT_FALLBACK
from cccc.ralph.validator import validate_with_project


REAL_WORKFLOW_EVALUATION_IO_PATH = "src/cccc/daemon/foreman/workflow_evaluation_io.py"
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
            "goal_behavior": "validate observable fallback coverage",
            "acceptance_criteria": "observable fallback validation is wired",
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
    extra_files: list[tuple[str, str]] | None = None,
):
    _write(tmp_path, "tests/test_placeholder.py", "def test_placeholder() -> None:\n    assert True\n")
    _write(tmp_path, rel_path, content)
    for extra_rel, extra_content in extra_files or []:
        _write(tmp_path, extra_rel, extra_content)
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


def test_return_without_signal_warns(tmp_path: Path) -> None:
    report = _report_for_module(
        tmp_path,
        rel_path="src/service.py",
        content=(
            "def read_flag() -> bool:\n"
            "    try:\n"
            "        run_step()\n"
            "    except Exception:\n"
            "        return False\n"
            "    return True\n"
        ),
    )

    issues = _issues_by_code(report, W_SILENT_FALLBACK)

    assert W_SILENT_FALLBACK in _issue_codes(report)
    assert len(issues) == 1


def test_continue_and_pass_warn(tmp_path: Path) -> None:
    report = _report_for_module(
        tmp_path,
        rel_path="src/worker.py",
        content=(
            "def iterate(items: list[str]) -> None:\n"
            "    for item in items:\n"
            "        try:\n"
            "            int(item)\n"
            "        except Exception:\n"
            "            continue\n"
            "\n"
            "def swallow() -> None:\n"
            "    try:\n"
            "        run_step()\n"
            "    except Exception:\n"
            "        pass\n"
        ),
    )

    issues = _issues_by_code(report, W_SILENT_FALLBACK)

    assert W_SILENT_FALLBACK in _issue_codes(report)
    assert len(issues) == 2


def test_logger_warning_makes_fallback_observable(tmp_path: Path) -> None:
    report = _report_for_module(
        tmp_path,
        rel_path="src/logger_case.py",
        content=(
            "def read_flag() -> bool:\n"
            "    try:\n"
            "        run_step()\n"
            "    except Exception:\n"
            "        logger.warning('fallback')\n"
            "        return False\n"
            "    return True\n"
        ),
    )

    assert W_SILENT_FALLBACK not in _issue_codes(report)


def test_append_or_publish_event_makes_fallback_observable(tmp_path: Path) -> None:
    report = _report_for_module(
        tmp_path,
        rel_path="src/events.py",
        content=(
            "def append_case() -> bool:\n"
            "    try:\n"
            "        run_step()\n"
            "    except Exception:\n"
            "        append_event('fallback')\n"
            "        return False\n"
            "    return True\n"
            "\n"
            "def publish_case() -> bool:\n"
            "    try:\n"
            "        run_step()\n"
            "    except Exception:\n"
            "        publish_event('fallback')\n"
            "        return False\n"
            "    return True\n"
        ),
    )

    assert W_SILENT_FALLBACK not in _issue_codes(report)


def test_private_log_helper_does_not_count_as_signal(tmp_path: Path) -> None:
    report = _report_for_module(
        tmp_path,
        rel_path="src/private_log.py",
        content=(
            "class Runner:\n"
            "    def execute(self) -> bool:\n"
            "        try:\n"
            "            run_step()\n"
            "        except Exception:\n"
            "            self._log('fallback')\n"
            "            return False\n"
            "        return True\n"
        ),
    )

    issues = _issues_by_code(report, W_SILENT_FALLBACK)

    assert W_SILENT_FALLBACK in _issue_codes(report)
    assert len(issues) == 1


def test_claimed_src_file_is_scanned_even_when_plan_scope_is_empty(tmp_path: Path) -> None:
    report = _report_for_module(
        tmp_path,
        rel_path="src/claimed_only.py",
        content=(
            "def read_flag() -> bool:\n"
            "    try:\n"
            "        run_step()\n"
            "    except Exception:\n"
            "        return False\n"
            "    return True\n"
        ),
        plan_scope=[],
        claimed_paths=["src/claimed_only.py"],
    )

    assert W_SILENT_FALLBACK in _issue_codes(report)


def test_plan_scope_opt_in_skips_unscoped_file(tmp_path: Path) -> None:
    report = _report_for_module(
        tmp_path,
        rel_path="app/out_of_scope.py",
        content=(
            "def read_flag() -> bool:\n"
            "    try:\n"
            "        run_step()\n"
            "    except Exception:\n"
            "        return False\n"
            "    return True\n"
        ),
        plan_scope=["src"],
        extra_files=[("src/main.py", "VALUE = 1\n")],
    )

    assert W_SILENT_FALLBACK not in _issue_codes(report)


def test_live_workflow_evaluation_io_has_observable_fallbacks() -> None:
    report = validate_with_project(
        _plan(
            claimed_paths=[REAL_WORKFLOW_EVALUATION_IO_PATH],
            plan_scope=[REAL_WORKFLOW_EVALUATION_IO_PATH],
        ),
        project_root=REPO_ROOT,
    )

    assert W_SILENT_FALLBACK not in _issue_codes(report)
