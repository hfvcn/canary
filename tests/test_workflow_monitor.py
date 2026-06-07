"""Tests for workflow_monitor — runtime anomaly detection.

All tests are pure-logic: no daemon, no filesystem, no network.
"""

from __future__ import annotations

import pytest

from cccc.contracts.v1.ralph_ipc import TaskRef
from cccc.daemon.foreman.workflow_monitor import (
    MonitorAlert,
    MonitorConfig,
    MonitorMode,
    WORKER_EXCEEDED_SCOPE_CODE,
    check_liveness_deadline,
    check_completer_mismatch,
    check_file_overstepping,
    check_path_deviation,
    check_silent_agent,
    check_unauthorized_subagent,
    get_default_config,
)
from cccc.kernel.workflow_state import TaskState, WorkflowTaskStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> float:
    return 1_000_000.0  # fixed epoch for deterministic tests


def _task_state(
    *,
    task_id: str = "t-live",
    status: WorkflowTaskStatus,
    assigned_at: float | None = None,
    started_at: float | None = None,
    last_heartbeat: float | None = None,
) -> TaskState:
    return TaskState(
        task=TaskRef(id=task_id, title=f"Task {task_id}"),
        workflow_id="wf-monitor",
        status=status,
        assigned_at=assigned_at,
        started_at=started_at,
        last_heartbeat=last_heartbeat,
    )


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


class TestCheckLivenessDeadline:
    def test_assigned_task_alerts_only_after_strict_deadline(self):
        now = _now()
        task = _task_state(
            status=WorkflowTaskStatus.ASSIGNED,
            assigned_at=now - 301,
        )

        result = check_liveness_deadline(task, now=now, deadline_s=300)

        assert result is not None
        assert result.alert_type == "liveness"
        assert result.task_id == "t-live"
        assert result.evidence["status"] == WorkflowTaskStatus.ASSIGNED.value

    def test_running_task_uses_last_heartbeat_reference(self):
        now = _now()
        task = _task_state(
            status=WorkflowTaskStatus.RUNNING,
            assigned_at=now - 600,
            started_at=now - 500,
            last_heartbeat=now - 100,
        )

        result = check_liveness_deadline(task, now=now, deadline_s=300)

        assert result is None

    def test_non_active_task_never_alerts(self):
        now = _now()
        task = _task_state(
            status=WorkflowTaskStatus.FAILED,
            assigned_at=now - 1_000,
        )

        assert check_liveness_deadline(task, now=now, deadline_s=300) is None


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
        assert result.alert_type == WORKER_EXCEEDED_SCOPE_CODE
        assert result.severity == "error"
        assert "src/other/module.py" in result.evidence["exceeded_files"]

    def test_partial_overstepping(self):
        # One file within scope, one outside
        result = check_file_overstepping(
            task_id="t1",
            changed_files=["src/foo/ok.py", "src/other/bad.py"],
            claimed_paths=["src/foo"],
        )
        assert result is not None
        assert result.evidence["exceeded_files"] == ["src/other/bad.py"]

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


# ---------------------------------------------------------------------------
# MonitorMode / MonitorConfig / MonitorAlert.mode  (T1 additions)
# ---------------------------------------------------------------------------


class TestMonitorMode:
    def test_has_expected_values(self):
        assert list(MonitorMode) == [
            MonitorMode.OBSERVE,
            MonitorMode.WARN,
            MonitorMode.BLOCK,
        ]


class TestMonitorConfig:
    def test_create_config(self):
        config = MonitorConfig(
            silent_agent=MonitorMode.WARN,
            path_deviation=MonitorMode.BLOCK,
            unauthorized_subagent=MonitorMode.OBSERVE,
            completer_mismatch=MonitorMode.WARN,
            file_overstepping=MonitorMode.BLOCK,
            fresh_self_test=MonitorMode.WARN,
            liveness=MonitorMode.WARN,
        )
        assert config.silent_agent == MonitorMode.WARN
        assert config.path_deviation == MonitorMode.BLOCK
        assert config.fresh_self_test == MonitorMode.WARN
        assert config.liveness == MonitorMode.WARN

    def test_get_default_config_returns_expected_defaults(self):
        config = get_default_config()
        assert config.silent_agent == MonitorMode.OBSERVE
        assert config.path_deviation == MonitorMode.OBSERVE
        assert config.unauthorized_subagent == MonitorMode.OBSERVE
        assert config.completer_mismatch == MonitorMode.OBSERVE
        assert config.file_overstepping == MonitorMode.OBSERVE
        assert config.fresh_self_test == MonitorMode.WARN
        assert config.liveness == MonitorMode.WARN


class TestMonitorAlertMode:
    def test_defaults_mode_to_observe(self):
        alert = MonitorAlert(
            alert_type="silent_agent",
            severity="warning",
            task_id="t1",
            message="agent silent",
            evidence={},
        )
        assert alert.mode == MonitorMode.OBSERVE

    def test_accepts_explicit_mode(self):
        alert = MonitorAlert(
            alert_type="unauthorized_subagent",
            severity="error",
            task_id="t1",
            message="blocked",
            evidence={},
            mode=MonitorMode.BLOCK,
        )
        assert alert.mode == MonitorMode.BLOCK
