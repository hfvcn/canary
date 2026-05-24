"""T-int: Integration tests for fix-v5-remaining (RO-38 + RO-39 + RO-37 + RO-30).

Validates all Batch 1-2 fixes work together end-to-end.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
import yaml

from cccc.contracts.v1.ralph_ipc import ReadyBatchSuggestion, TaskRef, VerificationResult, VerificationSpec
from cccc.daemon.foreman.prompt_builder import build_task_prompt
from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
from cccc.kernel.workflow_state import WorkflowTaskStatus
from cccc.ralph.flow_steps_e2e import E2E_STEPS
from cccc.ralph.plan_io import compute_structural_plan_digest, save_plan_state


def _write_plan(tmp_path: Path, *, fmt: str = "yaml") -> Path:
    plan = {
        "schema_version": "1.0.0",
        "tasks": [
            {
                "id": "T-up",
                "title": "upstream",
                "type": "backend",
                "claimed_paths": ["src/a.py"],
                "depends_on": [],
                "verification": {"command": "true", "level": "unit"},
            },
            {
                "id": "T-down",
                "title": "downstream",
                "type": "backend",
                "claimed_paths": ["src/b.py"],
                "depends_on": ["T-up"],
                "verification": {"command": "true", "level": "unit"},
            },
        ],
        "critical_flows": [
            {
                "id": "flow-critical",
                "description": "test critical flow",
                "entrypoints": ["src/a.py"],
            },
        ],
        "state": {"completed_task_ids": [], "running_tasks": [], "failed_task_ids": []},
    }
    if fmt == "json":
        path = tmp_path / "plan.json"
        path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    else:
        path = tmp_path / "plan.yaml"
        path.write_text(yaml.dump(plan, default_flow_style=False, allow_unicode=True), encoding="utf-8")
    return path


@pytest.fixture
def orchestrator(tmp_path: Path) -> WorkflowOrchestrator:
    group_dir = tmp_path / ".cccc" / "orchestrator" / "g-int"
    group_dir.mkdir(parents=True)
    (group_dir / "ledger.jsonl").touch()
    return WorkflowOrchestrator(project_root=tmp_path, group_id="g-int")


# ---------------------------------------------------------------------------
# 1. Structural digest: state change does NOT veto, task change DOES
# ---------------------------------------------------------------------------


class TestDigestStateExemptE2E:
    def test_state_change_does_not_veto_completion(self, orchestrator: WorkflowOrchestrator, tmp_path: Path):
        plan_path = _write_plan(tmp_path)
        workflow_id = "wf-digest"

        tasks = [
            TaskRef(id="T-up", title="upstream", type="backend", claimed_paths=["src/a.py"]),
            TaskRef(id="T-down", title="downstream", type="backend", depends_on=["T-up"], claimed_paths=["src/b.py"]),
        ]
        for t in tasks:
            orchestrator.engine.register_task(t, workflow_id)

        digest = compute_structural_plan_digest(plan_path)
        orchestrator.engine.set_workflow_meta(workflow_id, plan_path=str(plan_path), plan_digest=digest)
        orchestrator.engine.register_batch("batch-1", ["T-up"])
        orchestrator.engine.approve_batch("batch-1", [{"task_id": "T-up", "agent_id": "worker-1", "claimed_paths": ["src/a.py"]}])
        orchestrator.engine.report_worker_started("T-up", "worker-1")

        save_plan_state(plan_path, "T-up")

        orchestrator.engine.report_worker_completion("T-up", {"agent_id": "worker-1", "changed_files": ["src/a.py"], "idempotency_key": "k1"})
        state = orchestrator.engine.get_task("T-up")
        assert state is not None
        assert state.status == WorkflowTaskStatus.VERIFYING

    def test_task_definition_change_vetoes(self, orchestrator: WorkflowOrchestrator, tmp_path: Path):
        plan_path = _write_plan(tmp_path)
        workflow_id = "wf-veto"

        task = TaskRef(id="T-up", title="upstream", type="backend", claimed_paths=["src/a.py"])
        orchestrator.engine.register_task(task, workflow_id)

        digest = compute_structural_plan_digest(plan_path)
        orchestrator.engine.set_workflow_meta(workflow_id, plan_path=str(plan_path), plan_digest=digest)
        orchestrator.engine.register_batch("batch-v", ["T-up"])
        orchestrator.engine.approve_batch("batch-v", [{"task_id": "T-up", "agent_id": "w1", "claimed_paths": ["src/a.py"]}])
        orchestrator.engine.report_worker_started("T-up", "w1")

        data = yaml.safe_load(plan_path.read_text())
        data["tasks"][0]["claimed_paths"] = ["src/changed.py"]
        plan_path.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))

        from cccc.kernel.workflow_state_types import PreTransitionVetoed

        with pytest.raises(PreTransitionVetoed, match="modified after registration"):
            orchestrator.engine.report_worker_completion("T-up", {"agent_id": "w1", "changed_files": ["src/a.py"], "idempotency_key": "k2"})


# ---------------------------------------------------------------------------
# 2. Manual completion auto-advance via auto_dispatch
# ---------------------------------------------------------------------------


class TestManualCompleteAutoAdvanceE2E:
    def test_manual_complete_triggers_downstream_dispatch(self, orchestrator: WorkflowOrchestrator, tmp_path: Path):
        plan_path = _write_plan(tmp_path)
        workflow_id = "wf-advance"

        tasks = [
            TaskRef(id="T-up", title="upstream", type="backend", claimed_paths=["src/a.py"], verification=VerificationSpec(command="echo ok")),
            TaskRef(id="T-down", title="downstream", type="backend", depends_on=["T-up"], claimed_paths=["src/b.py"], verification=VerificationSpec(command="echo ok")),
        ]
        for t in tasks:
            orchestrator.engine.register_task(t, workflow_id)

        digest = compute_structural_plan_digest(plan_path)
        orchestrator.engine.set_workflow_meta(
            workflow_id,
            plan_path=str(plan_path),
            plan_digest=digest,
            auto_dispatch=True,
            assignment_map={"T-up": "worker-1", "T-down": "worker-2"},
        )
        orchestrator._ensure_active_workflow(
            workflow_id,
            auto_dispatch=True,
            assignment_map={"T-up": "worker-1", "T-down": "worker-2"},
        )

        orchestrator.engine.register_batch("batch-a", ["T-up", "T-down"])
        orchestrator.engine.approve_batch("batch-a", [{"task_id": "T-up", "agent_id": "worker-1", "claimed_paths": ["src/a.py"]}])
        orchestrator.engine.report_worker_started("T-up", "worker-1")

        save_plan_state(plan_path, "T-up")

        verification = VerificationResult(
            verification_id="ver-int",
            workflow_id=workflow_id,
            task_id="T-up",
            overall_outcome="passed",
            checks=[],
            summary="ok",
        )
        orchestrator.engine.report_worker_completion("T-up", {"agent_id": "worker-1", "changed_files": ["src/a.py"], "idempotency_key": "k-adv"})
        orchestrator.engine.record_verification_result("T-up", verification)

        with patch.object(orchestrator, "_start_assigned_agents"):
            orchestrator.on_task_completed(
                task_id="T-up",
                agent_id="foreman-manual",
                duration_seconds=10,
                changed_files=["src/a.py"],
                workflow_id=workflow_id,
                verification=verification,
            )

        down = orchestrator.engine.get_task("T-down")
        assert down is not None
        assert down.status in {WorkflowTaskStatus.ASSIGNED, WorkflowTaskStatus.READY}, (
            f"Expected T-down to be ASSIGNED or READY after upstream completion, got {down.status.value}"
        )


# ---------------------------------------------------------------------------
# 3. Critical flow auto-upgrade to challenge
# ---------------------------------------------------------------------------


class TestCriticalFlowChallengeE2E:
    def test_critical_flow_task_uses_challenge_mode(self, orchestrator: WorkflowOrchestrator, tmp_path: Path):
        plan_path = _write_plan(tmp_path)
        workflow_id = "wf-challenge"

        task = TaskRef(
            id="T-up",
            title="upstream",
            type="backend",
            claimed_paths=["src/a.py"],
            verification_mode="ralph",
        )
        orchestrator.engine.register_task(task, workflow_id)
        orchestrator.engine.set_workflow_meta(workflow_id, plan_path=str(plan_path), plan_digest="d")

        with patch.object(
            orchestrator.ralph,
            "_verify_completion_with_challenge",
            return_value=VerificationResult(
                verification_id="ver-ch",
                workflow_id=workflow_id,
                task_id="T-up",
                overall_outcome="passed",
                checks=[],
                summary="challenge ok",
            ),
        ) as mock_challenge:
            result = orchestrator.ralph.verify_completion(
                "T-up", ["src/a.py"], workflow_id=workflow_id, task_ref=task,
            )

        mock_challenge.assert_called_once()
        assert result.overall_outcome == "passed"
        assert result.summary == "challenge ok"


# ---------------------------------------------------------------------------
# 4. Docs: no MCP tool references remain
# ---------------------------------------------------------------------------


class TestDocsCleanup:
    def test_no_mcp_tool_references_in_workflow_doc(self):
        doc_path = Path(__file__).resolve().parent.parent / "docs" / "ralph-foreman-workflow.md"
        if not doc_path.exists():
            pytest.skip("docs/ralph-foreman-workflow.md not found")
        content = doc_path.read_text(encoding="utf-8")
        mcp_tools = ["cccc_message_send", "cccc_task", "cccc_bootstrap", "cccc_help", "cccc_capability_use", "cccc_coordination"]
        found = [tool for tool in mcp_tools if tool in content]
        assert not found, f"MCP tool references still in docs: {found}"


def test_failure_recovery_instruction_in_e2e_flow() -> None:
    instruction = E2E_STEPS[2].instruction_text.lower()

    assert "failure" in instruction
    assert "override" in instruction or "recovery" in instruction


# ---------------------------------------------------------------------------
# 5. RO-62: force-complete emits verification_skipped, not verification_passed
# ---------------------------------------------------------------------------


class TestForceCompleteEvent:
    def test_force_complete_emits_verification_skipped(self, orchestrator: WorkflowOrchestrator, tmp_path: Path, monkeypatch):
        """RO-62: force-complete should produce verification_skipped, not verification_passed."""
        from cccc.kernel.workflow_state_types import KIND_VERIFICATION_PASSED, KIND_VERIFICATION_SKIPPED
        from cccc.contracts.v1.ralph_ipc import TaskEvent

        monkeypatch.setattr(orchestrator.reporter, "on_task_completed", lambda *a, **kw: True)
        monkeypatch.setattr(orchestrator.reporter, "on_task_failed", lambda *a, **kw: True)

        task = TaskRef(id="T-fc", title="force me", type="backend")
        orchestrator.engine.register_task(task, "wf-fc")
        orchestrator.engine.register_batch("b-fc", ["T-fc"])
        orchestrator.engine.approve_batch("b-fc", [{"task_id": "T-fc", "agent_id": "w1", "claimed_paths": []}])
        orchestrator.engine.report_worker_started("T-fc", "w1")

        result = orchestrator.apply_task_event(
            TaskEvent(
                task_id="T-fc",
                event_type="completed",
                payload={"agent_id": "w1", "duration_seconds": 1, "changed_files": []},
            ),
            force_complete=True,
        )

        assert result["accepted"] is True
        assert result.get("verification_outcome") == "force_passed"

        ledger_path = orchestrator.group.ledger_path
        if ledger_path.exists():
            events = [json.loads(line) for line in ledger_path.read_text().splitlines() if line.strip()]
            event_kinds = [e["kind"] for e in events]
            assert KIND_VERIFICATION_SKIPPED in event_kinds
            assert KIND_VERIFICATION_PASSED not in event_kinds

    def test_force_complete_emits_force_completed_event(self, orchestrator: WorkflowOrchestrator, tmp_path: Path, monkeypatch):
        """RO-85: force-complete should produce an explicit workflow.force_completed ledger event."""
        from cccc.kernel.workflow_state_types import KIND_FORCE_COMPLETED
        from cccc.contracts.v1.ralph_ipc import TaskEvent

        monkeypatch.setattr(orchestrator.reporter, "on_task_completed", lambda *a, **kw: True)
        monkeypatch.setattr(orchestrator.reporter, "on_task_failed", lambda *a, **kw: True)

        task = TaskRef(id="T-fc2", title="force me 2", type="backend")
        orchestrator.engine.register_task(task, "wf-fc2")
        orchestrator.engine.register_batch("b-fc2", ["T-fc2"])
        orchestrator.engine.approve_batch("b-fc2", [{"task_id": "T-fc2", "agent_id": "w1", "claimed_paths": []}])
        orchestrator.engine.report_worker_started("T-fc2", "w1")

        orchestrator.apply_task_event(
            TaskEvent(
                task_id="T-fc2",
                event_type="completed",
                payload={"agent_id": "w1", "duration_seconds": 1, "changed_files": []},
            ),
            force_complete=True,
        )

        ledger_path = orchestrator.group.ledger_path
        if ledger_path.exists():
            events = [json.loads(line) for line in ledger_path.read_text().splitlines() if line.strip()]
            force_events = [e for e in events if e["kind"] == KIND_FORCE_COMPLETED]
            assert len(force_events) >= 1
            assert force_events[0]["data"]["task_id"] == "T-fc2"
            assert "reason" in force_events[0]["data"]

    def test_task_registered_contains_failure_path_and_awareness_paths(self, orchestrator: WorkflowOrchestrator, tmp_path: Path):
        """RO-82: task_registered event should contain failure_path and awareness_paths."""
        from cccc.kernel.workflow_state_types import KIND_TASK_REGISTERED

        task = TaskRef(
            id="T-ro82", title="test fields", type="backend",
            failure_path="rollback the migration",
            awareness_paths=["src/config.py", "src/models.py"],
        )
        orchestrator.engine.register_task(task, "wf-ro82")

        ledger_path = orchestrator.group.ledger_path
        if ledger_path.exists():
            events = [json.loads(line) for line in ledger_path.read_text().splitlines() if line.strip()]
            reg_events = [e for e in events if e["kind"] == KIND_TASK_REGISTERED and e["data"].get("task", {}).get("id") == "T-ro82"]
            assert len(reg_events) >= 1
            task_data = reg_events[0]["data"]["task"]
            assert task_data.get("failure_path") == "rollback the migration"
            assert task_data.get("awareness_paths") == ["src/config.py", "src/models.py"]


# ---------------------------------------------------------------------------
# 6. RO-63: ASSIGNED tasks can be retried and failed
# ---------------------------------------------------------------------------


class TestAssignedRetryFail:
    def test_retry_assigned_task(self, orchestrator: WorkflowOrchestrator, monkeypatch):
        """RO-63: retry should work on ASSIGNED tasks."""
        monkeypatch.setattr(orchestrator.reporter, "on_task_completed", lambda *a, **kw: True)
        monkeypatch.setattr(orchestrator.reporter, "on_task_failed", lambda *a, **kw: True)

        task = TaskRef(id="T-as", title="assigned task", type="backend")
        orchestrator.engine.register_task(task, "wf-as")
        orchestrator.engine.register_batch("b-as", ["T-as"])
        orchestrator.engine.approve_batch("b-as", [{"task_id": "T-as", "agent_id": "gemini-1", "claimed_paths": []}])

        state = orchestrator.engine.get_task("T-as")
        assert state is not None
        assert state.status == WorkflowTaskStatus.ASSIGNED

        result = orchestrator.retry_task("T-as")
        assert result["accepted"] is True

        state = orchestrator.engine.get_task("T-as")
        assert state is not None
        assert state.status == WorkflowTaskStatus.READY

    def test_fail_assigned_task(self, orchestrator: WorkflowOrchestrator):
        """RO-63: fail should work on ASSIGNED tasks at engine level."""
        task = TaskRef(id="T-af", title="fail me", type="backend")
        orchestrator.engine.register_task(task, "wf-af")
        orchestrator.engine.register_batch("b-af", ["T-af"])
        orchestrator.engine.approve_batch("b-af", [{"task_id": "T-af", "agent_id": "gemini-1", "claimed_paths": []}])

        state = orchestrator.engine.get_task("T-af")
        assert state.status == WorkflowTaskStatus.ASSIGNED

        orchestrator.engine.fail_task("T-af", "worker never started")

        state = orchestrator.engine.get_task("T-af")
        assert state is not None
        assert state.status == WorkflowTaskStatus.FAILED


# ---------------------------------------------------------------------------
# 7. RO-64: stall detection covers ASSIGNED tasks
# ---------------------------------------------------------------------------


class TestAssignedStallDetection:
    def test_stalled_assigned_task_detected(self, orchestrator: WorkflowOrchestrator, monkeypatch):
        """RO-64: ASSIGNED tasks that exceed threshold should be detected as stalled."""
        import time

        monkeypatch.setattr(orchestrator.reporter, "on_task_completed", lambda *a, **kw: True)
        monkeypatch.setattr(orchestrator.reporter, "on_task_failed", lambda *a, **kw: True)

        task = TaskRef(id="T-st", title="stall me", type="backend")
        orchestrator.engine.register_task(task, "wf-st")
        orchestrator.engine.register_batch("b-st", ["T-st"])
        orchestrator.engine.approve_batch(
            "b-st",
            [{"task_id": "T-st", "agent_id": "gemini-1", "claimed_paths": [],
              "assigned_at": time.time() - 700}],
        )

        state = orchestrator.engine.get_task("T-st")
        assert state.status == WorkflowTaskStatus.ASSIGNED

        stalled = orchestrator.check_stalled_tasks(threshold_seconds=300)
        assert "T-st" in stalled

    def test_fresh_assigned_task_not_stalled(self, orchestrator: WorkflowOrchestrator, monkeypatch):
        """ASSIGNED tasks within threshold should not be flagged."""
        monkeypatch.setattr(orchestrator.reporter, "on_task_completed", lambda *a, **kw: True)
        monkeypatch.setattr(orchestrator.reporter, "on_task_failed", lambda *a, **kw: True)

        task = TaskRef(id="T-fs", title="fresh", type="backend")
        orchestrator.engine.register_task(task, "wf-fs")
        orchestrator.engine.register_batch("b-fs", ["T-fs"])
        orchestrator.engine.approve_batch("b-fs", [{"task_id": "T-fs", "agent_id": "w1", "claimed_paths": []}])

        stalled = orchestrator.check_stalled_tasks(threshold_seconds=300)
        assert "T-fs" not in stalled

    def test_cold_start_500s_not_stalled(self, orchestrator: WorkflowOrchestrator, monkeypatch):
        """UX-14: ASSIGNED task at 500s should NOT be flagged (600s threshold)."""
        import time

        monkeypatch.setattr(orchestrator.reporter, "on_task_completed", lambda *a, **kw: True)
        monkeypatch.setattr(orchestrator.reporter, "on_task_failed", lambda *a, **kw: True)

        task = TaskRef(id="T-cs", title="cold start", type="backend")
        orchestrator.engine.register_task(task, "wf-cs")
        orchestrator.engine.register_batch("b-cs", ["T-cs"])
        orchestrator.engine.approve_batch(
            "b-cs",
            [{"task_id": "T-cs", "agent_id": "gemini-2", "claimed_paths": [],
              "assigned_at": time.time() - 500}],
        )

        stalled = orchestrator.check_stalled_tasks(threshold_seconds=300)
        assert "T-cs" not in stalled


def _create_actor_group_for_exit_tests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    desired_state: str = "running",
    runtime_state: str = "running",
    crash_count: int = 0,
) -> str:
    monkeypatch.setenv("CCCC_HOME", str(tmp_path / "home"))

    from cccc.kernel.actors import add_actor, update_actor
    from cccc.kernel.group import create_group
    from cccc.kernel.registry import load_registry

    group = create_group(load_registry(), title="pty-exit-tests", topic="")
    add_actor(group, actor_id="peer1", title="Peer 1", runner="pty", runtime="codex")
    update_actor(
        group,
        "peer1",
        {
            "desired_state": desired_state,
            "runtime_state": runtime_state,
            "crash_count": int(crash_count),
        },
    )
    return group.group_id


def _load_actor_for_exit_tests(group_id: str) -> Dict[str, Any]:
    from cccc.kernel.actors import find_actor
    from cccc.kernel.group import load_group

    group = load_group(group_id)
    assert group is not None
    actor = find_actor(group, "peer1")
    assert isinstance(actor, dict)
    return actor


# ---------------------------------------------------------------------------
# 8. UX-16 + UX-17: PTY crash exit logging, restart, and last_output
# ---------------------------------------------------------------------------


class TestPtyCrashExitRecovery:
    def test_normal_exit_marks_stopped_without_restart(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from cccc.daemon.actors.actor_lifecycle_ops import _mark_actor_stopped_on_exit

        group_id = _create_actor_group_for_exit_tests(
            tmp_path,
            monkeypatch,
            desired_state="stopped",
            runtime_state="running",
            crash_count=2,
        )
        scheduled: List[tuple[str, str, int, int]] = []

        _mark_actor_stopped_on_exit(
            group_id,
            "peer1",
            schedule_restart=lambda gid, aid, count, delay: scheduled.append((gid, aid, count, delay)),
        )

        actor = _load_actor_for_exit_tests(group_id)
        assert actor["desired_state"] == "stopped"
        assert actor["runtime_state"] == "stopped"
        assert actor["crash_count"] == 2
        assert scheduled == []

    def test_crash_exit_marks_crashed_and_schedules_restart(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from cccc.daemon.actors.actor_lifecycle_ops import _mark_actor_stopped_on_exit

        group_id = _create_actor_group_for_exit_tests(tmp_path, monkeypatch, crash_count=0)
        scheduled: List[tuple[str, str, int, int]] = []
        published: List[tuple[str, Dict[str, Any]]] = []

        _mark_actor_stopped_on_exit(
            group_id,
            "peer1",
            schedule_restart=lambda gid, aid, count, delay: scheduled.append((gid, aid, count, delay)),
            publish_global_event=lambda kind, data: published.append((kind, dict(data))),
        )

        actor = _load_actor_for_exit_tests(group_id)
        assert actor["desired_state"] == "running"
        assert actor["runtime_state"] == "crashed"
        assert actor["crash_count"] == 1
        assert scheduled == [(group_id, "peer1", 1, 1)]
        assert published == []

    def test_crash_limit_stops_actor_and_emits_event(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
        import logging

        from cccc.daemon.actors.actor_lifecycle_ops import _mark_actor_stopped_on_exit

        group_id = _create_actor_group_for_exit_tests(tmp_path, monkeypatch, crash_count=2)
        scheduled: List[tuple[str, str, int, int]] = []
        published: List[tuple[str, Dict[str, Any]]] = []

        with caplog.at_level(logging.ERROR, logger="cccc.daemon.actors"):
            _mark_actor_stopped_on_exit(
                group_id,
                "peer1",
                schedule_restart=lambda gid, aid, count, delay: scheduled.append((gid, aid, count, delay)),
                publish_global_event=lambda kind, data: published.append((kind, dict(data))),
            )

        actor = _load_actor_for_exit_tests(group_id)
        assert actor["desired_state"] == "stopped"
        assert actor["runtime_state"] == "crashed"
        assert actor["crash_count"] == 3
        assert scheduled == []
        assert published == [("actor.crash_limit", {"group_id": group_id, "actor_id": "peer1", "crash_count": 3})]
        assert "Actor crash limit reached" in caplog.text

    def test_server_restart_scheduler_dispatches_actor_restart(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from cccc.contracts.v1 import DaemonResponse
        from cccc.daemon import server as daemon_server

        group_id = _create_actor_group_for_exit_tests(tmp_path, monkeypatch, crash_count=1)
        requests: List[Dict[str, Any]] = []

        def _fake_handle_request(req: Any):
            requests.append(req.model_dump())
            return DaemonResponse(ok=True, result={}), False

        thread = daemon_server._schedule_actor_restart_after_crash(
            group_id,
            "peer1",
            1,
            0,
            sleep_fn=lambda _delay: None,
            request_fn=_fake_handle_request,
        )
        thread.join(timeout=1.0)

        assert requests == [
            {
                "v": 1,
                "op": "actor_restart",
                "args": {"group_id": group_id, "actor_id": "peer1", "by": "user"},
            }
        ]

    def test_server_exit_handler_logs_warning_on_actor_exit_failure(self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch):
        import logging
        from types import SimpleNamespace

        from cccc.daemon import server as daemon_server

        session = SimpleNamespace(group_id="g-exit", actor_id="peer1", pid=321)
        monkeypatch.setattr(daemon_server, "_remove_pty_state_if_pid", lambda *args, **kwargs: None)

        def _boom(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("exit hook failed")

        monkeypatch.setattr(daemon_server, "_on_actor_pty_session_exit", _boom)

        with caplog.at_level(logging.WARNING, logger="cccc.daemon.server"):
            daemon_server._handle_pty_session_exit(session)

        assert "Failed to process PTY session exit" in caplog.text
        assert "g-exit" in caplog.text
        assert "peer1" in caplog.text

    def test_scrollback_last_output_persists_tail(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from cccc.runners import pty as pty_runner

        monkeypatch.setenv("CCCC_HOME", str(tmp_path / "home"))
        payload = (b"A" * 5_000) + b"TAIL"

        pty_runner._write_last_output_snapshot("g-scroll", "peer1", payload)

        saved = pty_runner.last_output_path("g-scroll", "peer1").read_bytes()
        assert saved == payload[-pty_runner.LAST_OUTPUT_MAX_BYTES :]

    def test_scrollback_last_output_write_failure_is_logged(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
        import logging
        from pathlib import Path as StdPath

        from cccc.runners import pty as pty_runner

        monkeypatch.setenv("CCCC_HOME", str(tmp_path / "home"))

        def _fail_write(self: StdPath, _data: bytes) -> int:
            raise OSError("disk full")

        monkeypatch.setattr(StdPath, "write_bytes", _fail_write)

        with caplog.at_level(logging.WARNING, logger="cccc.runners.pty"):
            pty_runner._write_last_output_snapshot("g-scroll", "peer1", b"hello")

        assert "Failed to persist PTY last output" in caplog.text

    def test_pty_supervisor_logs_exit_warning(self, caplog: pytest.LogCaptureFixture):
        import logging

        from cccc.runners.pty import PtySupervisor

        class _FakeSession:
            group_id = "g-log"
            actor_id = "peer1"

            def exit_code(self) -> int:
                return 17

            def runtime_seconds(self) -> float:
                return 2.5

        session = _FakeSession()
        supervisor = PtySupervisor()
        supervisor._sessions[("g-log", "peer1")] = session  # type: ignore[assignment]

        with caplog.at_level(logging.WARNING, logger="cccc.runners.pty"):
            supervisor._on_session_exit(session)  # type: ignore[arg-type]

        assert "PTY session exited" in caplog.text
        assert "g-log" in caplog.text
        assert "peer1" in caplog.text
        assert "17" in caplog.text


def _collect_pytest_count_for_path(project_root: Path) -> str:
    import subprocess

    result = subprocess.run(
        ["pytest", "--co", "-q"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    assert lines, "pytest collection output is empty"
    return lines[-1].split(" ", 1)[0]


class TestWorkflowEvaluationTestCount:
    def test_evaluation_test_count_actual(self, orchestrator: WorkflowOrchestrator, tmp_path: Path):
        (tmp_path / "test_eval_count.py").write_text(
            "def test_eval_count_value():\n    assert True\n",
            encoding="utf-8",
        )
        expected = _collect_pytest_count_for_path(tmp_path)

        orchestrator._write_workflow_evaluation(
            workflow_id="wf-eval-count",
            completed_count=1,
            failed_count=0,
            total=1,
            summary="summary",
        )

        content = (tmp_path / "WORKFLOW_EVALUATION.md").read_text(encoding="utf-8")
        assert f"- test_count_actual: {expected}" in content
        assert f"| test_count_actual | {expected} |" in content

    def test_evaluation_test_count_fallback(
        self,
        orchestrator: WorkflowOrchestrator,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        from cccc.daemon.foreman import workflow_orchestrator as orchestrator_module

        def _raise_missing_pytest(*_args: Any, **_kwargs: Any) -> Any:
            raise FileNotFoundError("pytest")

        monkeypatch.setattr(orchestrator_module.subprocess, "run", _raise_missing_pytest)

        orchestrator._write_workflow_evaluation(
            workflow_id="wf-eval-fallback",
            completed_count=1,
            failed_count=0,
            total=1,
            summary="summary",
        )

        content = (tmp_path / "WORKFLOW_EVALUATION.md").read_text(encoding="utf-8")
        assert "- test_count_actual: N/A (collection failed)" in content
        assert "| test_count_actual | N/A (collection failed) |" in content


class TestDispatchObservability:
    def test_dispatch_log_contains_batch_info(self, orchestrator: WorkflowOrchestrator):
        from types import SimpleNamespace

        from cccc.daemon.foreman import workflow_orchestrator as orchestrator_module

        workflow_id = "wf-dispatch-log"
        task = TaskRef(id="T-dispatch", title="dispatch me", type="backend")
        orchestrator.engine.register_task(task, workflow_id)
        orchestrator._ensure_active_workflow(workflow_id, auto_process=True)

        suggestion = ReadyBatchSuggestion(
            suggestion_id="batch-dispatch",
            workflow_id=workflow_id,
            tasks=[task],
            estimated_parallelism=1,
            assignments={"T-dispatch": "worker-1"},
        )
        batch_result = SimpleNamespace(
            parallel_count=1,
            assignments=[SimpleNamespace(task=task, agent_id="worker-1", is_new_agent=False)],
        )

        with (
            patch.object(orchestrator.ralph, "suggest_ready_batch", return_value=suggestion),
            patch.object(orchestrator._assignment_controller, "process_batch_suggestion", return_value=batch_result),
            patch.object(orchestrator_module.logger, "info") as mock_log_info,
        ):
            orchestrator._resuggest_ready_tasks(workflow_id)

        formatted_messages = [
            call.args[0] % call.args[1:] if len(call.args) > 1 else call.args[0]
            for call in mock_log_info.call_args_list
        ]
        assert any(
            msg == "[dispatch] batch processed: 1 tasks, parallel=1"
            for msg in formatted_messages
        )
        assert any(
            msg == "[dispatch] batch batch-dispatch: 1 tasks dispatched to agents"
            for msg in formatted_messages
        )
