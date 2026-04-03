from __future__ import annotations

import logging
from pathlib import Path

from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
from cccc.ralph.core import suggest
from cccc.ralph.models import Plan, TaskSpec, Verification, VerificationCovers
from cccc.ralph.validator import validate, validate_with_project


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _task(
    task_id: str,
    *,
    claimed_paths: list[str],
    command: str,
    level: str = "unit",
    covers: list[str] | None = None,
    awareness_paths: list[str] | None = None,
    depends_on: list[str] | None = None,
) -> TaskSpec:
    return TaskSpec(
        id=task_id,
        claimed_paths=claimed_paths,
        awareness_paths=awareness_paths or [],
        depends_on=depends_on or [],
        acceptance_criteria=f"{task_id} complete",
        verification=Verification(
            level=level,
            command=command,
            covers=VerificationCovers(tasks=covers or [task_id]),
        ),
    )


def _issues(report) -> list:
    return [*report.errors, *report.warnings, *report.hints]


def _issues_by_code(report, code: str) -> list:
    return [issue for issue in _issues(report) if issue.code == code]


def test_awareness_paths_with_critical_entrypoint_integration(tmp_path: Path) -> None:
    _write(tmp_path / "README.md", "notes\n")
    _write(tmp_path / "src" / "server.py", "APP = object()\n")
    _write(tmp_path / "tests" / "test_server.py", "from server import APP\n")

    plan = Plan(
        tasks=[
            _task(
                "T1",
                claimed_paths=["README.md"],
                awareness_paths=["src/server.py"],
                command="python -m py_compile src/server.py",
            )
        ],
        critical_entrypoints=["src/server.py"],
    )

    report = validate_with_project(plan, project_root=tmp_path)

    assert _issues_by_code(report, "E_CRITICAL_ENTRYPOINT_UNOWNED") == []
    assert _issues_by_code(report, "W_TEST_COVERAGE_GAP") == []


def test_unclaimed_test_detection_integration(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "foo.py", "VALUE = 1\n")
    _write(tmp_path / "tests" / "test_foo.py", "from foo import VALUE\n")

    plan = Plan(tasks=[_task("T1", claimed_paths=["src/foo.py"], command="python -m py_compile src/foo.py")])

    report = validate_with_project(plan, project_root=tmp_path)
    issues = _issues_by_code(report, "W_UNCLAIMED_TEST_FOR_SOURCE")

    assert len(issues) == 1
    assert issues[0].evidence == {
        "source_path": "src/foo.py",
        "test_path": "tests/test_foo.py",
        "task_id": "T1",
    }


def test_unclaimed_test_silent_when_claimed_integration(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "foo.py", "VALUE = 1\n")
    _write(tmp_path / "tests" / "test_foo.py", "from foo import VALUE\n")

    plan = Plan(
        tasks=[
            _task("T1", claimed_paths=["src/foo.py"], command="python -m py_compile src/foo.py"),
            _task(
                "T2",
                claimed_paths=["tests/test_foo.py"],
                command="pytest tests/test_foo.py -q",
                level="integration",
                covers=["T1", "T2"],
                depends_on=["T1"],
            ),
        ]
    )

    report = validate_with_project(plan, project_root=tmp_path)

    assert _issues_by_code(report, "W_UNCLAIMED_TEST_FOR_SOURCE") == []


def test_suppress_codes_cli_integration() -> None:
    plan = Plan(
        tasks=[
            TaskSpec(
                id="T1",
                acceptance_criteria="suppressed error stays visible",
                verification=Verification(
                    level="unit",
                    command="pytest -q",
                    covers=VerificationCovers(tasks=["T1"]),
                ),
            )
        ]
    )
    plan.suppress_codes = ["E_MISSING_CLAIMED_PATHS"]

    report = validate(plan)
    hints = _issues_by_code(report, "E_MISSING_CLAIMED_PATHS")

    assert report.valid is True
    assert len(hints) == 1
    assert hints[0].severity == "hint"
    assert hints[0].message.startswith("[suppressed] ")
    assert [issue.code for issue in report.errors] == []


def test_pytest_k_downgrade_integration(tmp_path: Path) -> None:
    _write(
        tmp_path / "tests" / "test_demo.py",
        "def test_visible_case():\n"
        "    assert True\n",
    )

    plan = Plan(
        tasks=[
            _task(
                "T1",
                claimed_paths=["tests/test_demo.py"],
                command="pytest tests/test_demo.py -k hidden_case -q",
            )
        ]
    )

    report = validate_with_project(plan, project_root=tmp_path)
    issues = _issues_by_code(report, "W_VERIFICATION_PYTEST_K_NO_MATCH")

    assert len(issues) == 1
    assert issues[0].severity == "hint"
    assert [issue.code for issue in report.warnings if issue.code == "W_VERIFICATION_PYTEST_K_NO_MATCH"] == []


def test_awareness_paths_parallel_scheduling() -> None:
    plan = Plan(
        tasks=[
            _task(
                "T1",
                claimed_paths=["src/a.py"],
                awareness_paths=["src/shared/critical.py"],
                command="pytest tests/test_a.py -q",
            ),
            _task(
                "T2",
                claimed_paths=["src/b.py"],
                awareness_paths=["src/shared/critical.py"],
                command="pytest tests/test_b.py -q",
            ),
        ]
    )

    result = suggest(plan)

    assert set(result.ready) == {"T1", "T2"}
    assert result.blocked == []


def test_suppress_produces_audit_trail(tmp_path: Path) -> None:
    _write(tmp_path / "README.md", "notes\n")

    plan = Plan(
        tasks=[_task("T1", claimed_paths=["README.md"], command="echo ok")],
        suppress_codes=["W_VERIFICATION_TRIVIAL_COMMAND"],
    )

    report = validate_with_project(plan, project_root=tmp_path)
    hints = _issues_by_code(report, "W_VERIFICATION_TRIVIAL_COMMAND")

    assert len(hints) == 1
    assert hints[0].severity == "hint"
    assert hints[0].message.startswith("[suppressed] ")
    assert [issue.code for issue in report.warnings if issue.code == "W_VERIFICATION_TRIVIAL_COMMAND"] == []


def test_combined_awareness_unclaimed_suppress(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "foo.py", "VALUE = 1\n")
    _write(tmp_path / "src" / "server.py", "APP = object()\n")
    _write(tmp_path / "tests" / "test_foo.py", "from foo import VALUE\n")

    plan = Plan(
        tasks=[
            _task(
                "T1",
                claimed_paths=["src/foo.py"],
                awareness_paths=["src/server.py"],
                command="python -m py_compile src/foo.py",
            )
        ],
        critical_entrypoints=["src/server.py"],
        suppress_codes=["W_TEST_COVERAGE_GAP"],
    )

    report = validate_with_project(plan, project_root=tmp_path)
    suppressed_gap = _issues_by_code(report, "W_TEST_COVERAGE_GAP")
    unclaimed = _issues_by_code(report, "W_UNCLAIMED_TEST_FOR_SOURCE")

    assert len(suppressed_gap) == 1
    assert suppressed_gap[0].severity == "hint"
    assert suppressed_gap[0].message.startswith("[suppressed] ")
    assert len(unclaimed) == 1
    assert unclaimed[0].severity == "warning"
    assert _issues_by_code(report, "E_CRITICAL_ENTRYPOINT_UNOWNED") == []


def test_monitor_unauthorized_subagent_integration(
    tmp_path: Path,
    monkeypatch,
    caplog,
) -> None:
    monkeypatch.setenv("CCCC_HOME", str(tmp_path / ".cccc-home"))

    orchestrator = WorkflowOrchestrator(project_root=tmp_path, group_id="wave5-test")
    monkeypatch.setattr(orchestrator.reporter, "on_task_completed", lambda *args, **kwargs: True)
    monkeypatch.setattr(orchestrator.foreman, "release_completed_task", lambda *args, **kwargs: True)
    orchestrator._task_to_agent["T-known"] = "worker-known"

    with caplog.at_level(logging.WARNING, logger="cccc.daemon.foreman.orchestrator"):
        result = orchestrator.on_task_completed(
            "T-rogue",
            "worker-rogue",
            7,
            ["src/a.py"],
            workflow_id="wf-rogue",
        )

    warning_messages = [record.message for record in caplog.records if record.levelno == logging.WARNING]
    assert result is True
    assert any("unauthorized_subagent" in message for message in warning_messages)
