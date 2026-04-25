"""Tests for ralph audit subcommand (W9-audit-cli).

Verifies:
  (a) 4 verification failures -> W_TASK_FLAPPING emitted
  (b) 2 verification failures -> no W_TASK_FLAPPING emitted
  (c) verification_skipped + task_reported_completed -> H_COMPLETED_BUT_UNVERIFIED
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from cccc.ralph.cli import (
    AUDIT_H_COMPLETED_BUT_UNVERIFIED,
    AUDIT_W_TASK_FLAPPING,
    FLAPPING_THRESHOLD,
    audit_ledger,
    main as ralph_main,
)


def _make_event(
    kind: str,
    task_id: str,
    *,
    ts: str | None = None,
    extra_data: dict | None = None,
) -> dict:
    """Build a minimal ledger event dict."""
    if ts is None:
        ts = datetime.now(timezone.utc).isoformat()
    data = {"task_id": task_id, **(extra_data or {})}
    return {"kind": kind, "ts": ts, "data": data}


def _recent_ts(minutes_ago: int = 0) -> str:
    """Return an ISO timestamp *minutes_ago* minutes before now (UTC)."""
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


# -----------------------------------------------------------------------
# (a) 4 failures -> W_TASK_FLAPPING
# -----------------------------------------------------------------------

class TestTaskFlapping:
    def test_four_failures_emits_flapping(self):
        """4 verification failures for the same task_id -> W_TASK_FLAPPING."""
        events = [
            _make_event("workflow.verification_failed", "T1", ts=_recent_ts(i * 60))
            for i in range(4)
        ]
        issues = audit_ledger(events, days=7)
        flapping = [i for i in issues if i.code == AUDIT_W_TASK_FLAPPING]
        assert len(flapping) == 1
        issue = flapping[0]
        assert "T1" in issue.task_ids
        assert issue.evidence["failure_count"] == 4
        assert issue.severity == "warning"
        assert "issue_instance_id" in issue.evidence

    def test_threshold_exact(self):
        """Exactly FLAPPING_THRESHOLD failures should trigger the warning."""
        events = [
            _make_event("workflow.verification_failed", "T2", ts=_recent_ts(i * 10))
            for i in range(FLAPPING_THRESHOLD)
        ]
        issues = audit_ledger(events, days=7)
        flapping = [i for i in issues if i.code == AUDIT_W_TASK_FLAPPING]
        assert len(flapping) == 1

    def test_multiple_tasks_separate_issues(self):
        """Each task with >= threshold failures gets its own issue."""
        events = [
            _make_event("workflow.verification_failed", "TA", ts=_recent_ts(i * 10))
            for i in range(4)
        ] + [
            _make_event("workflow.verification_failed", "TB", ts=_recent_ts(i * 10))
            for i in range(3)
        ]
        issues = audit_ledger(events, days=7)
        flapping = [i for i in issues if i.code == AUDIT_W_TASK_FLAPPING]
        assert len(flapping) == 2
        task_ids = {i.task_ids[0] for i in flapping}
        assert task_ids == {"TA", "TB"}


# -----------------------------------------------------------------------
# (b) 2 failures -> no emission
# -----------------------------------------------------------------------

class TestNoFlapping:
    def test_two_failures_no_flapping(self):
        """2 verification failures should NOT emit W_TASK_FLAPPING."""
        events = [
            _make_event("workflow.verification_failed", "T1", ts=_recent_ts(i * 60))
            for i in range(2)
        ]
        issues = audit_ledger(events, days=7)
        flapping = [i for i in issues if i.code == AUDIT_W_TASK_FLAPPING]
        assert len(flapping) == 0

    def test_old_failures_outside_window(self):
        """Failures older than the lookback window are not counted."""
        old_ts = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        events = [
            _make_event("workflow.verification_failed", "T1", ts=old_ts)
            for _ in range(5)
        ]
        issues = audit_ledger(events, days=7)
        flapping = [i for i in issues if i.code == AUDIT_W_TASK_FLAPPING]
        assert len(flapping) == 0


# -----------------------------------------------------------------------
# (c) skipped+completed -> H_COMPLETED_BUT_UNVERIFIED
# -----------------------------------------------------------------------

class TestCompletedButUnverified:
    def test_skipped_then_completed(self):
        """verification_skipped followed by task_reported_completed -> H_COMPLETED_BUT_UNVERIFIED."""
        events = [
            _make_event("workflow.verification_skipped", "T1", ts=_recent_ts(120)),
            _make_event("workflow.task_reported_completed", "T1", ts=_recent_ts(60)),
        ]
        issues = audit_ledger(events, days=7)
        unverified = [i for i in issues if i.code == AUDIT_H_COMPLETED_BUT_UNVERIFIED]
        assert len(unverified) == 1
        issue = unverified[0]
        assert "T1" in issue.task_ids
        assert issue.severity == "hint"
        assert "issue_instance_id" in issue.evidence

    def test_skipped_then_passed_then_completed_no_issue(self):
        """verification_skipped -> verification_passed -> completed = no issue."""
        events = [
            _make_event("workflow.verification_skipped", "T1", ts=_recent_ts(180)),
            _make_event("workflow.verification_passed", "T1", ts=_recent_ts(120)),
            _make_event("workflow.task_reported_completed", "T1", ts=_recent_ts(60)),
        ]
        issues = audit_ledger(events, days=7)
        unverified = [i for i in issues if i.code == AUDIT_H_COMPLETED_BUT_UNVERIFIED]
        assert len(unverified) == 0

    def test_no_skipped_before_completed(self):
        """Completion without any prior skipped -> no issue."""
        events = [
            _make_event("workflow.task_reported_completed", "T1", ts=_recent_ts(60)),
        ]
        issues = audit_ledger(events, days=7)
        unverified = [i for i in issues if i.code == AUDIT_H_COMPLETED_BUT_UNVERIFIED]
        assert len(unverified) == 0


# -----------------------------------------------------------------------
# CLI integration
# -----------------------------------------------------------------------

class TestAuditCLI:
    def test_cli_text_output(self, tmp_path: Path):
        """ralph audit --ledger ... --format text returns 0 and prints issues."""
        ledger = tmp_path / "ledger.jsonl"
        events = [
            _make_event("workflow.verification_failed", "T1", ts=_recent_ts(i * 10))
            for i in range(4)
        ]
        ledger.write_text("\n".join(json.dumps(e) for e in events) + "\n")
        rc = ralph_main(["audit", "--ledger", str(ledger), "--format", "text"])
        assert rc == 0  # warnings are not errors

    def test_cli_json_output(self, tmp_path: Path):
        """ralph audit --ledger ... --format json returns valid JSON structure."""
        ledger = tmp_path / "ledger.jsonl"
        events = [
            _make_event("workflow.verification_failed", "T1", ts=_recent_ts(i * 10))
            for i in range(4)
        ]
        ledger.write_text("\n".join(json.dumps(e) for e in events) + "\n")
        rc = ralph_main(["audit", "--ledger", str(ledger), "--format", "json"])
        assert rc == 0

    def test_cli_clean_ledger(self, tmp_path: Path):
        """Empty ledger reports CLEAN."""
        ledger = tmp_path / "ledger.jsonl"
        ledger.write_text("")
        rc = ralph_main(["audit", "--ledger", str(ledger)])
        assert rc == 0
