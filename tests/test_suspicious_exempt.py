from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from cccc.daemon.foreman.ralph_service import RalphService


START_SECONDS = 100.0
FAST_DURATION_MS = 5
FAST_DURATION_SECONDS = FAST_DURATION_MS / 1000
FIRST_COUNTER_CALL = 1
TEST_GROUP_ID = "test"


@dataclass(frozen=True)
class CommandCase:
    command: str
    expected_exit_code: int = 0
    returncode: int = 0


@dataclass(frozen=True)
class RunResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


EXEMPT_CASES = (
    CommandCase("grep -q needle file.txt"),
    CommandCase("test -f pyproject.toml"),
    CommandCase("[ -f pyproject.toml ]"),
    CommandCase("true"),
    CommandCase("false", expected_exit_code=1, returncode=1),
)


def _stub_fast_run(monkeypatch: pytest.MonkeyPatch, returncode: int) -> None:
    import cccc.daemon.foreman.ralph_service as mod

    call_count = 0

    def fake_perf_counter() -> float:
        nonlocal call_count
        call_count += 1
        if call_count == FIRST_COUNTER_CALL:
            return START_SECONDS
        return START_SECONDS + FAST_DURATION_SECONDS

    def fake_run(*args: object, **kwargs: object) -> RunResult:
        return RunResult(returncode=returncode)

    monkeypatch.setattr(mod.time, "perf_counter", fake_perf_counter)
    monkeypatch.setattr(mod.subprocess, "run", fake_run)


def _make_service(tmp_path: Path) -> RalphService:
    return RalphService(project_root=tmp_path, group_id=TEST_GROUP_ID)


@pytest.mark.parametrize("case", EXEMPT_CASES, ids=lambda case: case.command)
def test_known_fast_commands_skip_suspicious_duration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: CommandCase,
) -> None:
    _stub_fast_run(monkeypatch, case.returncode)

    result = _make_service(tmp_path)._run_verification_check(
        command=case.command,
        expected_exit_code=case.expected_exit_code,
    )

    assert result.outcome == "passed"
    assert result.details.get("suspicious_duration") is None
    assert not result.message.startswith("[SUSPICIOUS:")


def test_fast_non_exempt_command_is_still_suspicious(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_fast_run(monkeypatch, returncode=0)

    result = _make_service(tmp_path)._run_verification_check(command="pytest tests/")

    assert result.outcome == "passed"
    assert result.details.get("suspicious_duration") is True
    assert result.message.startswith("[SUSPICIOUS:")
