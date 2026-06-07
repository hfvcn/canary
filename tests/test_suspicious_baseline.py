from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from cccc.daemon.foreman.ralph_service import RalphService


START_SECONDS = 100.0
TEST_GROUP_ID = "test"


@dataclass(frozen=True)
class SuspiciousCase:
    command: str
    duration_ms: int
    expect_suspicious: bool


@dataclass(frozen=True)
class RunResult:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


SUSPICIOUS_BASELINE_CASES = (
    SuspiciousCase("python -m compileall src/app.py", 32, False),
    SuspiciousCase("grep -r pattern .", 15, False),
    SuspiciousCase("pytest tests/ -v", 40, True),
    SuspiciousCase("unknown-command --check", 10, True),
)


def _stub_check_duration(monkeypatch: pytest.MonkeyPatch, duration_ms: int) -> None:
    import cccc.daemon.foreman.ralph_service as mod

    counter = 0
    duration_seconds = duration_ms / 1000

    def fake_perf_counter() -> float:
        nonlocal counter
        counter += 1
        if counter == 1:
            return START_SECONDS
        return START_SECONDS + duration_seconds

    def fake_run(*args: object, **kwargs: object) -> RunResult:
        return RunResult()

    monkeypatch.setattr(mod.time, "perf_counter", fake_perf_counter)
    monkeypatch.setattr(mod.subprocess, "run", fake_run)


def _make_service(tmp_path: Path) -> RalphService:
    return RalphService(project_root=tmp_path, group_id=TEST_GROUP_ID)


@pytest.mark.parametrize(
    "case",
    SUSPICIOUS_BASELINE_CASES,
    ids=lambda case: f"{case.duration_ms}ms:{case.command}",
)
def test_suspicious_duration_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: SuspiciousCase,
) -> None:
    _stub_check_duration(monkeypatch, case.duration_ms)

    result = _make_service(tmp_path)._run_verification_check(command=case.command)

    assert result.outcome == "passed"
    assert (result.details.get("suspicious_duration") is True) is case.expect_suspicious
    assert result.message.startswith("[SUSPICIOUS:") is case.expect_suspicious
