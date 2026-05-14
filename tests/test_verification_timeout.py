"""Regression tests for configurable verification check timeouts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cccc.contracts.v1.ralph_ipc import (
    TaskRef,
    VerificationCheck,
    VerificationCheckSpec,
    VerificationSpec,
)
from cccc.daemon.foreman.ralph_service import (
    VERIFICATION_COMMAND_TIMEOUT_SECONDS,
    RalphService,
)
from cccc.ralph import core
from cccc.ralph.models import CheckSpec, TaskSpec, Verification


class _CompletedProcess:
    returncode = 0
    stdout = ""
    stderr = ""


def test_verification_check_specs_accept_timeout() -> None:
    ipc_spec = VerificationCheckSpec(name="unit", command="pytest", timeout=5)
    domain_spec = CheckSpec(name="unit", command="pytest", timeout=7)
    task = TaskSpec(
        id="T-model",
        verification=Verification(
            level="unit",
            checks=[CheckSpec(name="unit", command="pytest", timeout=19)],
        ),
    )

    assert ipc_spec.timeout == 5
    assert domain_spec.timeout == 7
    assert VerificationCheckSpec(name="unit", command="pytest").timeout is None
    assert CheckSpec(name="unit", command="pytest").timeout is None
    assert task.to_task_ref().verification.checks[0].timeout == 19


def test_core_run_check_uses_custom_and_default_timeout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    timeouts: list[int] = []

    def fake_run(command: str, **kwargs: Any) -> _CompletedProcess:
        del command
        timeouts.append(kwargs["timeout"])
        return _CompletedProcess()

    monkeypatch.setattr(core.subprocess, "run", fake_run)

    core._run_check(name="custom", command="true", project_root=tmp_path, timeout=9)
    core._run_check(name="default", command="true", project_root=tmp_path)

    assert timeouts == [9, core._VERIFY_TIMEOUT]


def test_core_verification_pre_check_passes_spec_timeout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[dict[str, Any]] = []
    task = TaskSpec(
        id="T-timeout",
        verification=Verification(
            level="unit",
            checks=[CheckSpec(name="unit", command="pytest", timeout=11)],
        ),
    )

    def fake_run_check(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"name": kwargs["name"], "outcome": "passed", "duration_ms": 1}

    monkeypatch.setattr(core, "_run_check", fake_run_check)

    result = core._run_verification_pre_check(task, tmp_path)

    assert result["status"] == "passed"
    assert calls[0]["timeout"] == 11


def test_daemon_run_verification_check_uses_custom_and_default_timeout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    timeouts: list[int] = []
    service = RalphService(project_root=tmp_path, group_id="timeout-test")

    def fake_run(command: list[str], **kwargs: Any) -> _CompletedProcess:
        del command
        timeouts.append(kwargs["timeout"])
        return _CompletedProcess()

    monkeypatch.setattr("cccc.daemon.foreman.ralph_service.subprocess.run", fake_run)

    service._run_verification_check(name="custom", command="true", timeout=13)
    service._run_verification_check(name="default", command="true")

    assert timeouts == [13, VERIFICATION_COMMAND_TIMEOUT_SECONDS]


def test_daemon_verification_pre_check_passes_spec_timeout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[dict[str, Any]] = []
    service = RalphService(project_root=tmp_path, group_id="timeout-test")
    task_ref = TaskRef(
        id="T-timeout",
        verification=VerificationSpec(
            checks=[
                VerificationCheckSpec(name="unit", command="pytest", timeout=17),
            ],
        ),
    )

    def fake_run_check(**kwargs: Any) -> VerificationCheck:
        calls.append(kwargs)
        return VerificationCheck(name=kwargs["name"], outcome="passed")

    monkeypatch.setattr(service, "_run_verification_check", fake_run_check)

    result = service._run_verification_pre_check(task_ref)

    assert result["status"] == "passed"
    assert calls[0]["timeout"] == 17
