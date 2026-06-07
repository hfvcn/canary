from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path

import pytest
import yaml

import cccc.ralph.flow_engine as flow_engine_module
from cccc.ralph.deferral_ledger import (
    STATUS_CLEARED,
    STATUS_DEFERRED,
    STATUS_ESCALATED,
    begin_round,
    clear_deferral,
    escalated_blockers,
    record_deferral,
)
from cccc.ralph.flow_engine import CheckResult, FlowState
from cccc.ralph.flow_improvement_check import _check_archive_evidence_bundle


TRACKER_SHORT = Path("todo/issues-ralph.md")
TRACKER_FULL = Path("todo/issues-ralph-full.md")
LEDGER_PATH = Path("todo/deferral-ledger.yaml")
REVIEW_MESSAGE = "- refresh token misuse\n- contract drift\n"
_BUNDLE_FIELD_ORDER = (
    "issue_id",
    "original_symptom",
    "claimed_fix",
    "changed_paths",
    "active_entrypoint",
    "active_path_trace",
    "runtime_conditions",
    "verification_commands",
    "expected_behavior",
    "observed_behavior",
    "fallback_behavior",
    "evidence_locations",
    "regression_test",
    "archive_decision",
)


def test_begin_round_escalates_after_two_consecutive_versions(tmp_path: Path) -> None:
    ledger = tmp_path / LEDGER_PATH

    begin_round(ledger, "v1", {"RV-51"})
    begin_round(ledger, "v2", {"RV-51"})

    entry = _ledger_entry(ledger, "RV-51")
    assert entry["streak_count"] == 2
    assert entry["last_deferred_version"] == "v2"
    assert entry["status"] == STATUS_ESCALATED


def test_record_deferral_same_version_is_idempotent(tmp_path: Path) -> None:
    ledger = tmp_path / LEDGER_PATH

    record_deferral(ledger, "RV-51", "v1")
    entry = record_deferral(ledger, "RV-51", "v1")

    assert entry["streak_count"] == 1
    assert entry["last_deferred_version"] == "v1"
    assert entry["status"] == STATUS_DEFERRED


def test_begin_round_resets_streak_after_skipped_round(tmp_path: Path) -> None:
    ledger = tmp_path / LEDGER_PATH

    begin_round(ledger, "v1", {"RV-51"})
    begin_round(ledger, "v2", set())
    begin_round(ledger, "v3", {"RV-51"})

    entry = _ledger_entry(ledger, "RV-51")
    assert entry["streak_count"] == 1
    assert entry["last_deferred_version"] == "v3"
    assert entry["status"] == STATUS_DEFERRED


def test_clear_deferral_restarts_streak_from_one(tmp_path: Path) -> None:
    ledger = tmp_path / LEDGER_PATH

    begin_round(ledger, "v1", {"RV-51"})
    begin_round(ledger, "v2", {"RV-51"})
    cleared = clear_deferral(ledger, "RV-51", "v3")
    entry = record_deferral(ledger, "RV-51", "v4")

    assert cleared["status"] == STATUS_CLEARED
    assert cleared["cleared_version"] == "v3"
    assert entry["streak_count"] == 1
    assert entry["status"] == STATUS_DEFERRED
    assert entry["cleared_version"] == "v3"


def test_escalated_blockers_follow_archive_evidence_bundle_rule(tmp_path: Path) -> None:
    ledger = tmp_path / LEDGER_PATH
    full_tracker = tmp_path / TRACKER_FULL
    begin_round(ledger, "v1", {"RV-51"})
    begin_round(ledger, "v2", {"RV-51"})
    full_tracker.parent.mkdir(parents=True, exist_ok=True)
    full_tracker.write_text("#### FL-40\nopen issue\n", encoding="utf-8")

    blockers_before = escalated_blockers(ledger, _bundle_evidence_fn(full_tracker))
    full_tracker.write_text(_bundle_text("RV-51"), encoding="utf-8")
    blockers_after = escalated_blockers(ledger, _bundle_evidence_fn(full_tracker))

    assert blockers_before == ["RV-51"]
    assert blockers_after == []


def test_clear_deferral_removes_issue_from_blockers(tmp_path: Path) -> None:
    ledger = tmp_path / LEDGER_PATH
    full_tracker = tmp_path / TRACKER_FULL
    begin_round(ledger, "v1", {"RV-51"})
    begin_round(ledger, "v2", {"RV-51"})
    clear_deferral(ledger, "RV-51", "v3")

    blockers = escalated_blockers(ledger, _bundle_evidence_fn(full_tracker))

    assert blockers == []


def test_check_plan_blocks_only_on_unresolved_escalated_deferrals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "plan.yaml").write_text("version: 1\n", encoding="utf-8")
    _write(repo / TRACKER_SHORT, "#### RV-51\nopen issue\n")
    monkeypatch.setattr(flow_engine_module, "_run_process_check", _passing_validate_check)
    state = _plan_state(repo)

    no_ledger = flow_engine_module._check_plan(state)
    begin_round(repo / LEDGER_PATH, "v1", {"RV-51"})
    begin_round(repo / LEDGER_PATH, "v2", {"RV-51"})
    blocked = flow_engine_module._check_plan(state)
    clear_deferral(repo / LEDGER_PATH, "RV-51", "v3")
    cleared = flow_engine_module._check_plan(state)

    assert no_ledger.passed
    assert _has_failed_check(blocked, "deferral P0 blocker")
    assert not blocked.passed
    assert cleared.passed


def test_gap_record_round_trip_escalates_and_blocks_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    _write_review_output(repo / ".ralph-flow" / "step-3-review" / "review.json")
    _write(repo / TRACKER_SHORT, _round_one_tracker_text())

    first = flow_engine_module._check_gap_record(_gap_state(repo, "v1"))
    first_entry = _ledger_entry(repo / LEDGER_PATH, "RV-51")
    _git(repo, "add", str(TRACKER_SHORT))
    _git(repo, "commit", "-m", "round1")
    _write(repo / TRACKER_SHORT, _round_two_tracker_text())

    second = flow_engine_module._check_gap_record(_gap_state(repo, "v2"))
    second_entry = _ledger_entry(repo / LEDGER_PATH, "RV-51")
    (repo / "plan.yaml").write_text("version: 1\n", encoding="utf-8")
    monkeypatch.setattr(flow_engine_module, "_run_process_check", _passing_validate_check)
    blocked = flow_engine_module._check_plan(_plan_state(repo))

    assert first.passed
    assert first_entry["streak_count"] == 1
    assert second.passed
    assert second_entry["streak_count"] == 2
    assert second_entry["status"] == STATUS_ESCALATED
    assert not blocked.passed
    assert _has_failed_check(blocked, "deferral P0 blocker")


def _ledger_entry(ledger_path: Path, issue_id: str) -> dict:
    ledger = yaml.safe_load(ledger_path.read_text(encoding="utf-8")) or {}
    return ledger[issue_id]


def _bundle_evidence_fn(full_tracker_path: Path):
    def has_bundle(issue_id: str) -> bool:
        current_full = full_tracker_path.read_text(encoding="utf-8") if full_tracker_path.is_file() else ""
        details = _check_archive_evidence_bundle(current_full, {issue_id})
        return bool(details) and all(detail["passed"] for detail in details)

    return has_bundle


def _bundle_text(issue_id: str) -> str:
    fields = {
        "issue_id": issue_id,
        "original_symptom": "widget crashes on startup",
        "claimed_fix": "startup path now guards missing config",
        "changed_paths": "src/widget.py, tests/test_widget.py",
        "active_entrypoint": "widget.main",
        "active_path_trace": "widget.main -> widget.bootstrap -> widget.run",
        "runtime_conditions": "FEATURE_WIDGET=1",
        "verification_commands": "pytest tests/test_widget.py -v",
        "expected_behavior": "widget starts cleanly",
        "observed_behavior": "widget starts cleanly",
        "fallback_behavior": "startup exits loudly if bootstrap fails",
        "evidence_locations": "tests/test_widget.py::test_widget_bootstrap",
        "regression_test": "pytest tests/test_widget.py",
        "archive_decision": "behavior-verified",
    }
    lines = [f"#### {issue_id}\n"]
    for field_name in _BUNDLE_FIELD_ORDER:
        lines.append(f"{field_name}: {fields[field_name]}\n")
    return "".join(lines)


def _init_repo(repo: Path) -> Path:
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    _write(repo / TRACKER_SHORT, _baseline_tracker_text())
    _git(repo, "add", str(TRACKER_SHORT))
    _git(repo, "commit", "-m", "init tracker")
    return repo


def _baseline_tracker_text() -> str:
    return "> 日期：2026-06-01\n---\n#### FL-40\nopen issue\n"


def _round_one_tracker_text() -> str:
    return (
        "> 日期：2026-06-01\n"
        "---\n"
        "#### FL-40\n"
        "open issue\n"
        "#### FL-21\n"
        "issue_id: FL-21\n"
        "detection_type: validate\n"
        "description: refresh token misuse needs validate rule coverage in tracker checks\n"
        "## 已知局限（不修复，仅记录）\n"
        "| ID | 描述 |\n"
        "|----|------|\n"
        "| RV-51 | 本轮不在本次范围，等待行为证据 |\n"
    )


def _round_two_tracker_text() -> str:
    return (
        _round_one_tracker_text()
        + "#### FL-22\n"
        + "issue_id: FL-22\n"
        + "detection_type: validate\n"
        + "description: contract drift needs validate rule coverage in tracker checks\n"
    )


def _gap_state(repo: Path, version: str) -> FlowState:
    return FlowState(
        flow_type="solve",
        workspace=str(repo),
        started_at="2026-06-01T00:00:00Z",
        current_step=4,
        params={"tracker": str(TRACKER_SHORT), "version": version},
        steps_completed=[],
        steps_failed={},
        version=version,
    )


def _plan_state(repo: Path) -> FlowState:
    return FlowState(
        flow_type="solve",
        workspace=str(repo),
        started_at="2026-06-01T00:00:00Z",
        current_step=2,
        params={"tracker": str(TRACKER_SHORT)},
        steps_completed=[],
        steps_failed={},
    )


def _passing_validate_check(*_args, **_kwargs) -> CheckResult:
    return CheckResult(True, [{"check": "ralph validate", "passed": True, "message": "ok"}])


def _write_review_output(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "SESSION_ID": str(uuid.uuid4()),
                "success": True,
                "agent_messages": REVIEW_MESSAGE,
                "_sig": "review-sig",
            }
        ),
        encoding="utf-8",
    )


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _has_failed_check(result: CheckResult, check: str) -> bool:
    return any(detail["check"] == check and not detail["passed"] for detail in result.details)


def _git(repo: Path, *args: str) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
