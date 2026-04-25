from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from cccc.ralph.cli import main as ralph_main


def _ts(minutes_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _event(kind: str, task_id: str, minutes_ago: int) -> dict:
    return {
        "kind": kind,
        "ts": _ts(minutes_ago),
        "data": {"task_id": task_id},
    }


def _capture(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
        rc = ralph_main(argv)
    return rc, stdout.getvalue(), stderr.getvalue()


def test_wave9_audit_realistic_ledger_fixture(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    events = [
        _event("workflow.verification_failed", "T-flap", 180),
        _event("workflow.verification_failed", "T-flap", 120),
        _event("workflow.verification_failed", "T-flap", 60),
        _event("workflow.verification_skipped", "T-skip", 90),
        _event("workflow.task_reported_completed", "T-skip", 30),
        _event("workflow.verification_passed", "T-healthy", 20),
        _event("workflow.task_reported_completed", "T-healthy", 10),
    ]
    ledger.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
    assert callable(ralph_main)

    rc, stdout, stderr = _capture(["audit", "--ledger", str(ledger), "--format", "text"])

    assert rc == 0
    assert stderr == ""
    assert "W_TASK_FLAPPING" in stdout
    assert "H_COMPLETED_BUT_UNVERIFIED" in stdout
    assert "T-healthy" not in stdout
