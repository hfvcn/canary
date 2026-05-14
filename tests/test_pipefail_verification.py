from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from cccc.daemon.foreman.ralph_service import RalphService


def _make_service(tmp_path: Path) -> RalphService:
    service = RalphService.__new__(RalphService)
    service.project_root = tmp_path
    return service


def test_pipe_failure_detected(tmp_path: Path) -> None:
    check = _make_service(tmp_path)._run_verification_check(command="false | true")

    assert check.outcome == "failed"
    assert check.details["returncode"] == 1


def test_pipe_success(tmp_path: Path) -> None:
    check = _make_service(tmp_path)._run_verification_check(command="true | true")

    assert check.outcome == "passed"
    assert check.details["returncode"] == 0


def test_already_has_pipefail_no_double_inject(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []
    real_run = subprocess.run

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return real_run(command, **kwargs)

    monkeypatch.setattr("cccc.daemon.foreman.ralph_service.subprocess.run", fake_run)

    check = _make_service(tmp_path)._run_verification_check(
        command="set -o pipefail; false | true"
    )

    assert check.outcome == "failed"
    assert commands == [["bash", "-c", "set -o pipefail; false | true"]]


def test_set_e_without_pipefail_still_injects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []
    real_run = subprocess.run

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return real_run(command, **kwargs)

    monkeypatch.setattr("cccc.daemon.foreman.ralph_service.subprocess.run", fake_run)

    check = _make_service(tmp_path)._run_verification_check(
        command="set -e; false | true"
    )

    assert check.outcome == "failed"
    assert commands == [["bash", "-c", "set -o pipefail; set -e; false | true"]]


def test_non_pipe_command_unaffected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        del kwargs
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "1\n", "")

    monkeypatch.setattr("cccc.daemon.foreman.ralph_service.subprocess.run", fake_run)

    check = _make_service(tmp_path)._run_verification_check(
        command='python -c "print(1)"'
    )

    assert check.outcome == "passed"
    assert commands == [["python", "-c", "print(1)"]]
