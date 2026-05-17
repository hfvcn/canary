"""E2E test: monitor violations are recorded to ledger in observe mode.

Verifies ARCH-9: violations are recorded, workflow is not blocked.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture()
def temp_home():
    old_home = os.environ.get("CCCC_HOME")
    with tempfile.TemporaryDirectory() as td:
        os.environ["CCCC_HOME"] = td
        yield Path(td)
    if old_home is None:
        os.environ.pop("CCCC_HOME", None)
    else:
        os.environ["CCCC_HOME"] = old_home


@pytest.fixture()
def temp_project_dir():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".cccc" / "agents").mkdir(parents=True, exist_ok=True)
        (root / ".cccc" / "capabilities").mkdir(parents=True, exist_ok=True)
        (root / ".cccc" / "models").mkdir(parents=True, exist_ok=True)
        (root / ".cccc" / "models" / "registry.yaml").write_text(
            "models:\n  codex:\n    runtime: codex\n    model_id: codex-latest\n    strengths: [general]\n    weaknesses: []\n",
            encoding="utf-8",
        )
        yield root


@pytest.fixture()
def orchestrator_with_group(temp_home, temp_project_dir):
    from cccc.kernel.group import attach_scope_to_group, create_group
    from cccc.kernel.registry import load_registry
    from cccc.kernel.scope import detect_scope

    reg = load_registry()
    group = create_group(reg, title="monitor-test", topic="")
    scope = detect_scope(temp_project_dir)
    group = attach_scope_to_group(reg, group, scope, set_active=True)

    from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

    orch = WorkflowOrchestrator(
        project_root=temp_project_dir,
        group_id=group.group_id,
    )
    return orch, group


def _read_ledger_events(group) -> list[dict]:
    """Read all events from a group's ledger."""
    ledger_path = group.ledger_path
    if not ledger_path.exists():
        return []
    events = []
    for line in ledger_path.read_text(encoding="utf-8").strip().splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


class TestMonitorViolationLedger:
    def test_path_deviation_recorded_to_ledger(self, orchestrator_with_group):
        """Triggering a path deviation alert writes a violation event to ledger."""
        orch, group = orchestrator_with_group

        # Trigger a path deviation: message with assignment keywords
        orch.monitor_incoming_event(
            task_id="T1",
            event_type="chat.message",
            event_payload={"content": "please take this task and assign it to yourself"},
        )

        events = _read_ledger_events(group)
        violations = [e for e in events if e.get("kind") == "workflow.monitor_violation"]

        assert len(violations) >= 1, f"Expected violation event in ledger, got {len(violations)}"
        v = violations[0]
        data = v.get("data", {})
        assert data["alert_type"] == "path_deviation"
        assert data["task_id"] == "T1"
        assert data["monitor_mode"] == "observe"
        assert data["invariant_id"] == "path_deviation"
        assert data["severity"] == "warning"

    def test_observe_mode_does_not_block_workflow(self, orchestrator_with_group):
        """In observe mode, violations are recorded but workflow continues normally."""
        orch, group = orchestrator_with_group

        # Trigger violation — should not raise
        orch.monitor_incoming_event(
            task_id="T1",
            event_type="chat.message",
            event_payload={"content": "assign this to the backend worker"},
        )

        # Workflow operations should still work after violation
        # (register a batch to prove the orchestrator is still functional)
        from unittest.mock import patch
        from cccc.ports.web.app import create_app

        def _local_call_daemon(req):
            from cccc.contracts.v1 import DaemonRequest
            from cccc.daemon.server import handle_request
            request = DaemonRequest.model_validate(req)
            resp, _ = handle_request(request)
            return resp.model_dump(exclude_none=True)

        from fastapi.testclient import TestClient
        with patch("cccc.ports.web.app.call_daemon", side_effect=_local_call_daemon):
            with TestClient(create_app()) as client:
                suggest = client.post(
                    f"/api/v1/groups/{group.group_id}/workflow/batch/suggest",
                    json={
                        "workflow_id": "wf-post-violation",
                        "tasks": [
                            {"id": "T1", "title": "test", "type": "backend", "depends_on": [], "claimed_paths": ["src/a.py"], "verification": {"command": "echo ok"}},
                        ],
                        "auto_process": True,
                        "auto_start_agents": False,
                    },
                )
                assert suggest.status_code == 200
                assert suggest.json().get("ok")

    def test_no_violation_when_proper_channel(self, orchestrator_with_group):
        """Proper workflow.task_assigned events produce no violation."""
        orch, group = orchestrator_with_group

        orch.monitor_incoming_event(
            task_id="T1",
            event_type="workflow.task_assigned",
            event_payload={"content": "assign this task"},
        )

        events = _read_ledger_events(group)
        violations = [e for e in events if e.get("kind") == "workflow.monitor_violation"]
        assert len(violations) == 0, "Should not record violation for proper channel"
