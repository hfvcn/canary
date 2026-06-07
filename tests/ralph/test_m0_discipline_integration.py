from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path

import pytest
import yaml

import cccc.ralph.flow_engine as flow_engine_module
from cccc.ralph.deferral_ledger import DEFAULT_LEDGER_PATH, clear_deferral
from cccc.ralph.flow_engine import CheckResult, FlowState, _check_gap_record, _check_plan
from cccc.ralph.flow_improvement_check import _check_improvement_register
from cccc.ralph.models import Plan
from cccc.ralph.validator import validate


TRACKER_SHORT = Path("todo/issues-ralph.md")
TRACKER_FULL = Path("todo/issues-ralph-full.md")
LEDGER_PATH = DEFAULT_LEDGER_PATH
ARCHIVE_VERSION = "v60"
REVIEW_MESSAGE = "- refresh token misuse\n- contract drift\n"
W_BEHAVIOR_MISMATCH = "W_VERIFICATION_BEHAVIOR_MISMATCH"
OPEN_IDS = ("FL-40", "FL-7", "AF-07", "RV-51")
FOUR_FIELD_BUNDLE = {"issue_id", "original_symptom", "verification_commands", "observed_behavior"}
_BUNDLE_FIELDS = (
    "issue_id", "original_symptom", "claimed_fix", "changed_paths", "active_entrypoint",
    "active_path_trace", "runtime_conditions", "verification_commands", "expected_behavior",
    "observed_behavior", "fallback_behavior", "evidence_locations", "regression_test",
    "archive_decision",
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    _write(repo / "plan.yaml", "version: 1\n")
    _write_trackers(repo, _baseline_tracker(), _baseline_tracker())
    _write_review_output(repo / ".ralph-flow" / "step-3-review" / "review.json")
    _git(repo, "add", "plan.yaml", str(TRACKER_SHORT), str(TRACKER_FULL), ".ralph-flow/step-3-review/review.json")
    _git(repo, "commit", "-m", "init repo")
    return repo


def test_m0_discipline_integration(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_mt1()
    _assert_mt2(repo)
    _assert_mt4(repo)
    _assert_mt3(repo)
    _assert_mt5(repo, monkeypatch)


def _assert_mt1() -> None:
    good = validate(_behavior_plan(level="integration", suppress=False))
    bad = validate(_behavior_plan(level="unit", suppress=True))

    assert _issue_codes(good, W_BEHAVIOR_MISMATCH) == []
    assert _issue_codes(bad, W_BEHAVIOR_MISMATCH, "hints") == []
    assert _issue_codes(bad, W_BEHAVIOR_MISMATCH, "errors") + _issue_codes(bad, W_BEHAVIOR_MISMATCH, "warnings")


def _assert_mt2(repo: Path) -> None:
    _write_trackers(
        repo,
        _completed_short("FL-7"),
        _completed_full("FL-7", _bundle_text("FL-7", drop_fields={"fallback_behavior"})),
    )
    failed = _check_improvement_register(_state(repo, flow_type="e2e", step=6, version=ARCHIVE_VERSION))
    _write_trackers(repo, _completed_short("FL-7"), _completed_full("FL-7", _bundle_text("FL-7")))
    passed = _check_improvement_register(_state(repo, flow_type="e2e", step=6, version=ARCHIVE_VERSION))

    assert not failed.passed
    assert "fallback_behavior" in _failed_message(failed, "archive evidence bundle")
    assert passed.passed


def _assert_mt4(repo: Path) -> None:
    _write_trackers(
        repo,
        _completed_short("AF-07"),
        _completed_full("AF-07", _bundle_text("AF-07", include_fields=FOUR_FIELD_BUNDLE)),
    )
    failed = _check_improvement_register(_state(repo, flow_type="e2e", step=6, version=ARCHIVE_VERSION))
    _write_trackers(repo, _completed_short("AF-07"), _completed_full("AF-07", _bundle_text("AF-07")))
    passed = _check_improvement_register(_state(repo, flow_type="e2e", step=6, version=ARCHIVE_VERSION))

    message = _failed_message(failed, "archive evidence bundle")
    assert not failed.passed
    assert "quarantine" in message
    assert "af_engine" in message
    assert passed.passed


def _assert_mt3(repo: Path) -> None:
    _write_trackers(repo, _gap_tracker(dirty=True), _baseline_tracker())
    failed = _check_gap_record(_state(repo, flow_type="solve", step=4, version="v61"))
    _write_trackers(repo, _gap_tracker(), _baseline_tracker())
    passed = _check_gap_record(_state(repo, flow_type="solve", step=4, version="v62"))

    assert not failed.passed
    _failed_message(failed, "short tracker strikethrough")
    _failed_message(failed, "short tracker completed summaries")
    assert passed.passed


def _assert_mt5(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _commit_trackers(repo, _baseline_tracker(), _baseline_tracker(), "reset trackers")
    _write_trackers(repo, _gap_tracker(deferred=True), _baseline_tracker())
    first = _check_gap_record(_state(repo, flow_type="solve", step=4, version="v1"))
    _git(repo, "add", str(TRACKER_SHORT))
    _git(repo, "commit", "-m", "round1")
    _write_trackers(repo, _gap_tracker(deferred=True, second_gap=True), _baseline_tracker())
    second = _check_gap_record(_state(repo, flow_type="solve", step=4, version="v2"))
    escalated = _ledger_entry(repo, "RV-51")
    monkeypatch.setattr(flow_engine_module, "_run_process_check", _passing_validate_check)
    blocked = _check_plan(_state(repo, flow_type="solve", step=2))
    _write(repo / TRACKER_FULL, _completed_full("RV-51", _bundle_text("RV-51")))
    evidence_cleared = _check_plan(_state(repo, flow_type="solve", step=2))
    _write(repo / TRACKER_FULL, _baseline_tracker())
    clear_deferral(repo / LEDGER_PATH, "RV-51", "v3")
    cleared = _check_plan(_state(repo, flow_type="solve", step=2))

    assert first.passed
    assert second.passed
    assert escalated["status"] == "escalated"
    assert escalated["streak_count"] == 2
    assert not blocked.passed
    assert "RV-51" in _failed_message(blocked, "deferral P0 blocker")
    assert evidence_cleared.passed
    assert cleared.passed


def _behavior_plan(*, level: str, suppress: bool) -> Plan:
    check = {
        "name": "integration" if level == "integration" else "compile",
        "command": "pytest tests/test_app.py -q" if level == "integration" else "python -m py_compile src/app.py",
    }
    return Plan.model_validate({
        "suppress_codes": [W_BEHAVIOR_MISMATCH] if suppress else [],
        "tasks": [{
            "id": "T1",
            "claimed_paths": ["src/app.py"],
            "goal_behavior": "startup remains reachable",
            "acceptance_criteria": "startup remains reachable",
            "verification": {"level": level, "command": check["command"], "checks": [check], "covers": {"tasks": ["T1"]}},
        }],
    })


def _baseline_tracker() -> str:
    return f"> 日期：2026-06-06\n---\n{_open_sections()}"


def _completed_short(issue_id: str) -> str:
    return f"> 日期：2026-06-06\n> 已完成（{ARCHIVE_VERSION} 代码修复）：{issue_id}\n---\n{_open_sections(issue_id)}"


def _completed_full(issue_id: str, bundle: str) -> str:
    return f"> 日期：2026-06-06\n> 已完成（{ARCHIVE_VERSION} 代码修复）：{issue_id}\n---\n{_open_sections(issue_id)}{bundle}"


def _gap_tracker(*, dirty: bool = False, deferred: bool = False, second_gap: bool = False) -> str:
    body = ["#### FL-40\nopen issue\n"]
    if dirty:
        body.extend(["- ~~FL-19~~ 已归档\n", f"> 已完成（{ARCHIVE_VERSION} 代码修复）：FL-18\n"])
    body.append(_gap_entry("FL-21"))
    if second_gap:
        body.append(_gap_entry("FL-22"))
    if deferred:
        body.extend([
            "## 已知局限（不修复，仅记录）\n",
            "| ID | 描述 |\n",
            "|----|------|\n",
            "| RV-51 | 本轮不在本次范围，等待行为证据 |\n",
        ])
    header = "> 日期：2026-06-06\n> 已完成（v59 代码修复）：FL-19\n"
    return f"{header}---\n{''.join(body)}"


def _gap_entry(issue_id: str) -> str:
    return (
        f"#### {issue_id}\n"
        f"issue_id: {issue_id}\n"
        "detection_type: validate\n"
        "description: refresh token misuse needs validate rule coverage in tracker checks.\n"
    )


def _bundle_text(
    issue_id: str,
    *,
    include_fields: set[str] | None = None,
    drop_fields: set[str] | None = None,
) -> str:
    values = {
        "issue_id": issue_id,
        "original_symptom": "production symptom previously reproduced on the main path",
        "claimed_fix": "main path now resolves the symptom before dispatch",
        "changed_paths": "src/widget.py, tests/test_widget.py",
        "active_entrypoint": "widget.main",
        "active_path_trace": "widget.main -> widget.bootstrap -> widget.run",
        "runtime_conditions": "FEATURE_WIDGET=1",
        "verification_commands": "python -m pytest tests/test_widget.py -v",
        "expected_behavior": "main path completes without the prior symptom",
        "observed_behavior": "E2E 行为确认：主路径调用确认，behavior confirmed and observed in runtime",
        "fallback_behavior": "the path fails loudly if bootstrap regresses",
        "evidence_locations": "tests/test_widget.py::test_widget_bootstrap",
        "regression_test": "python -m pytest tests/test_widget.py",
        "archive_decision": "behavior-verified",
    }
    selected = include_fields or set(_BUNDLE_FIELDS)
    omitted = drop_fields or set()
    lines = [f"**{issue_id} evidence bundle**\n"]
    for field in _BUNDLE_FIELDS:
        if field in omitted or field not in selected:
            continue
        lines.append(f"- {field}: {values[field]}\n")
    return "".join(lines)


def _open_sections(*removed_ids: str) -> str:
    removed = set(removed_ids)
    return "".join(f"#### {issue_id}\nopen issue\n" for issue_id in OPEN_IDS if issue_id not in removed)


def _write_trackers(repo: Path, short_content: str, full_content: str) -> None:
    _write(repo / TRACKER_SHORT, short_content)
    _write(repo / TRACKER_FULL, full_content)


def _commit_trackers(repo: Path, short_content: str, full_content: str, message: str) -> None:
    _write_trackers(repo, short_content, full_content)
    _git(repo, "add", str(TRACKER_SHORT), str(TRACKER_FULL))
    result = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=repo, capture_output=True, text=True)
    assert result.returncode in (0, 1), result.stderr
    if result.returncode == 1:
        _git(repo, "commit", "-m", message)


def _issue_codes(report, code: str, bucket: str | None = None) -> list[str]:
    buckets = (bucket,) if bucket else ("errors", "warnings", "hints")
    return [issue.code for name in buckets for issue in getattr(report, name) if issue.code == code]


def _failed_message(result: CheckResult, check: str) -> str:
    detail = next(detail for detail in result.details if detail["check"] == check and not detail["passed"])
    return str(detail["message"])


def _ledger_entry(repo: Path, issue_id: str) -> dict[str, object]:
    ledger = yaml.safe_load((repo / LEDGER_PATH).read_text(encoding="utf-8")) or {}
    return ledger[issue_id]


def _state(repo: Path, *, flow_type: str, step: int, version: str = "") -> FlowState:
    params = {"cccc_root": str(repo), "tracker": str(TRACKER_SHORT)}
    if version:
        params["version"] = version
    return FlowState(
        flow_type=flow_type,
        workspace=str(repo),
        started_at="2026-06-06T00:00:00Z",
        current_step=step,
        params=params,
        steps_completed=[],
        steps_failed={},
        version=version or None,
    )


def _passing_validate_check(*_args, **_kwargs) -> CheckResult:
    return CheckResult(True, [{"check": "ralph validate", "passed": True, "message": "ok"}])


def _write_review_output(path: Path) -> None:
    _write(path, json.dumps({"SESSION_ID": str(uuid.uuid4()), "success": True, "agent_messages": REVIEW_MESSAGE, "_sig": "review-sig"}))


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _git(repo: Path, *args: str) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
