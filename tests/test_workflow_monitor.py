"""Tests for workflow_monitor — runtime anomaly detection.

All tests are pure-logic: no daemon, no filesystem, no network.
"""

from __future__ import annotations

import pytest

from cccc.daemon.foreman.workflow_monitor import (
    MonitorAlert,
    check_completer_mismatch,
    check_file_overstepping,
    check_path_deviation,
    check_silent_agent,
    check_unauthorized_subagent,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> float:
    return 1_000_000.0  # fixed epoch for deterministic tests


# ---------------------------------------------------------------------------
# TestCheckSilentAgent
# ---------------------------------------------------------------------------

class TestCheckSilentAgent:
    def test_no_alert_within_timeout(self):
        now = _now()
        result = check_silent_agent(
            task_id="t1",
            assigned_at=now - 60,
            last_event_at=now - 30,
            now=now,
            timeout_s=300,
        )
        assert result is None

    def test_alert_after_timeout(self):
        now = _now()
        result = check_silent_agent(
            task_id="t1",
            assigned_at=now - 400,
            last_event_at=now - 350,
            now=now,
            timeout_s=300,
        )
        assert result is not None
        assert isinstance(result, MonitorAlert)
        assert result.alert_type == "silent_agent"
        assert result.severity == "warning"
        assert result.task_id == "t1"
        assert result.evidence["elapsed_s"] >= 300

    def test_alert_with_no_events(self):
        # last_event_at=0 means no event has been received yet
        now = _now()
        result = check_silent_agent(
            task_id="t2",
            assigned_at=now - 600,
            last_event_at=0,
            now=now,
            timeout_s=300,
        )
        assert result is not None
        assert result.alert_type == "silent_agent"
        assert result.evidence["last_event_at"] == 0

    def test_exactly_at_timeout_boundary(self):
        # elapsed == timeout_s should trigger the alert (>= check)
        now = _now()
        result = check_silent_agent(
            task_id="t3",
            assigned_at=now - 300,
            last_event_at=0,
            now=now,
            timeout_s=300,
        )
        assert result is not None

    def test_one_second_before_timeout(self):
        now = _now()
        result = check_silent_agent(
            task_id="t3",
            assigned_at=now - 299,
            last_event_at=now - 299,
            now=now,
            timeout_s=300,
        )
        assert result is None


# ---------------------------------------------------------------------------
# TestCheckCompleterMismatch
# ---------------------------------------------------------------------------

class TestCheckCompleterMismatch:
    def test_no_alert_when_match(self):
        result = check_completer_mismatch(
            task_id="t1",
            assigned_agent="agent-A",
            completing_agent="agent-A",
        )
        assert result is None

    def test_alert_when_mismatch(self):
        result = check_completer_mismatch(
            task_id="t1",
            assigned_agent="agent-A",
            completing_agent="agent-B",
        )
        assert result is not None
        assert result.alert_type == "completer_mismatch"
        assert result.severity == "error"
        assert result.task_id == "t1"
        assert result.evidence["assigned_agent"] == "agent-A"
        assert result.evidence["completing_agent"] == "agent-B"

    def test_no_alert_when_empty_assigned(self):
        # If assigned_agent is empty we cannot judge — no alert
        result = check_completer_mismatch(
            task_id="t1",
            assigned_agent="",
            completing_agent="agent-B",
        )
        assert result is None

    def test_no_alert_when_empty_completing(self):
        result = check_completer_mismatch(
            task_id="t1",
            assigned_agent="agent-A",
            completing_agent="",
        )
        assert result is None


# ---------------------------------------------------------------------------
# TestCheckFileOverstepping
# ---------------------------------------------------------------------------

class TestCheckFileOverstepping:
    def test_no_alert_within_scope(self):
        result = check_file_overstepping(
            task_id="t1",
            changed_files=["src/foo/bar.py", "src/foo/baz.py"],
            claimed_paths=["src/foo"],
        )
        assert result is None

    def test_alert_outside_scope(self):
        result = check_file_overstepping(
            task_id="t1",
            changed_files=["src/other/module.py"],
            claimed_paths=["src/foo"],
        )
        assert result is not None
        assert result.alert_type == "file_overstepping"
        assert result.severity == "error"
        assert "src/other/module.py" in result.evidence["overstepping_files"]

    def test_partial_overstepping(self):
        # One file within scope, one outside
        result = check_file_overstepping(
            task_id="t1",
            changed_files=["src/foo/ok.py", "src/other/bad.py"],
            claimed_paths=["src/foo"],
        )
        assert result is not None
        assert result.evidence["overstepping_files"] == ["src/other/bad.py"]

    def test_directory_claim_covers_children(self):
        result = check_file_overstepping(
            task_id="t1",
            changed_files=[
                "src/foo/sub/deep/file.py",
                "src/foo/__init__.py",
            ],
            claimed_paths=["src/foo"],
        )
        assert result is None

    def test_no_alert_empty_changed_files(self):
        result = check_file_overstepping(
            task_id="t1",
            changed_files=[],
            claimed_paths=["src/foo"],
        )
        assert result is None

    def test_no_alert_empty_claimed_paths(self):
        # Empty claimed_paths = global scope, no restriction
        result = check_file_overstepping(
            task_id="t1",
            changed_files=["anywhere/file.py"],
            claimed_paths=[],
        )
        assert result is None

    def test_exact_file_matches_claimed_file(self):
        result = check_file_overstepping(
            task_id="t1",
            changed_files=["src/foo/bar.py"],
            claimed_paths=["src/foo/bar.py"],
        )
        assert result is None

    def test_global_claim_covers_everything(self):
        result = check_file_overstepping(
            task_id="t1",
            changed_files=["literally/anything/file.py"],
            claimed_paths=["/"],
        )
        assert result is None


# ---------------------------------------------------------------------------
# TestCheckUnauthorizedSubagent
# ---------------------------------------------------------------------------

class TestCheckUnauthorizedSubagent:
    def test_known_agent_ok(self):
        result = check_unauthorized_subagent(
            agent_id="agent-A",
            known_agents={"agent-A", "agent-B"},
        )
        assert result is None

    def test_unknown_agent_alert(self):
        result = check_unauthorized_subagent(
            agent_id="rogue-agent",
            known_agents={"agent-A", "agent-B"},
        )
        assert result is not None
        assert result.alert_type == "unauthorized_subagent"
        assert result.severity == "error"
        assert result.evidence["agent_id"] == "rogue-agent"

    def test_empty_known_set_always_alerts(self):
        result = check_unauthorized_subagent(
            agent_id="any-agent",
            known_agents=set(),
        )
        assert result is not None

    def test_task_id_empty_for_non_task_alert(self):
        result = check_unauthorized_subagent(
            agent_id="rogue",
            known_agents={"x"},
        )
        assert result is not None
        assert result.task_id == ""


# ---------------------------------------------------------------------------
# TestCheckPathDeviation
# ---------------------------------------------------------------------------

class TestCheckPathDeviation:
    def test_normal_event_ok(self):
        result = check_path_deviation(
            task_id="t1",
            event_type="message_send",
            event_payload={"content": "Hey, how are you doing?"},
        )
        assert result is None

    def test_proper_channel_ok(self):
        result = check_path_deviation(
            task_id="t1",
            event_type="workflow.task_assigned",
            event_payload={"content": "assign task-1 to agent-A"},
        )
        # Proper channel — never flag
        assert result is None

    def test_direct_assignment_detected(self):
        result = check_path_deviation(
            task_id="t1",
            event_type="message_send",
            event_payload={"content": "Please assign task-42 to agent-X"},
        )
        assert result is not None
        assert result.alert_type == "path_deviation"
        assert result.severity == "warning"
        assert "assign" in result.evidence["matched_keywords"]

    def test_case_insensitive_keyword_match(self):
        result = check_path_deviation(
            task_id="t1",
            event_type="message_send",
            event_payload={"content": "ASSIGN this task to someone"},
        )
        assert result is not None

    def test_multiple_content_keys(self):
        # Uses "text" key when "content" is absent
        result = check_path_deviation(
            task_id="t1",
            event_type="message_send",
            event_payload={"text": "your task is to refactor the module"},
        )
        assert result is not None
        assert result.alert_type == "path_deviation"

    def test_no_content_no_alert(self):
        result = check_path_deviation(
            task_id="t1",
            event_type="message_send",
            event_payload={},
        )
        assert result is None
