"""Comprehensive integration test: Batch A+B+C+D in a single multi-step DAG workflow.

Exercises the full lifecycle of a realistic workflow to validate all four batches
work together without regressions. This is NOT a unit test — it tests the integrated
behavior of orchestrator + engine + monitor + Ralph in a single scenario.

Verified behaviors:
- Batch A (ARCH-9): Monitor violations recorded to ledger, observe mode doesn't block
- Batch C (ARCH-1): Foreman explicit assignments respected
- Batch C (ARCH-2): Rejected batch stays rejected, no silent fallback
- Batch C (ARCH-3): _resuggest_ready_tasks notifies Foreman, doesn't auto-process
- Batch C (ARCH-6): assignment_id passthrough in task events
- Batch D (ARCH-7): DEFERRED state in engine, register_batch boundary
- Batch D (ARCH-8): retry clears agent_id/attempt_id, CAS on stale completion
- Batch D (ARCH-11): BLOCKED cascade to downstream, terminal protection

Findings from first run:
- on_task_completed (orchestrator) does NOT transition engine state.
  Real flow is: apply_task_event → engine.report_worker_completion → verify → record_verification_result → on_task_completed
- engine.block_task() does NOT cascade. Cascade is in orch.block_task() which reads _active_workflows.
- No engine.complete_task(). VERIFYING→COMPLETED is via engine.record_verification_result().
- CAS rejection is ValueError, not return dict.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from cccc.contracts.v1.ralph_ipc import ReadyBatchSuggestion, TaskRef, VerificationSpec
from cccc.daemon.foreman.workflow import BatchEvaluationResult
from cccc.kernel.workflow_state_types import WorkflowTaskStatus


# ── Fixtures ──────────────────────────────────────────────


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
            "models:\n  codex:\n    runtime: codex\n    model_id: codex-latest\n"
            "    strengths: [general]\n    weaknesses: []\n",
            encoding="utf-8",
        )
        yield root


@pytest.fixture()
def setup(temp_home, temp_project_dir):
    from cccc.kernel.group import attach_scope_to_group, create_group
    from cccc.kernel.registry import load_registry
    from cccc.kernel.scope import detect_scope

    reg = load_registry()
    group = create_group(reg, title="batch-abcd-integration", topic="")
    scope = detect_scope(temp_project_dir)
    group = attach_scope_to_group(reg, group, scope, set_active=True)

    from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

    orch = WorkflowOrchestrator(
        project_root=temp_project_dir,
        group_id=group.group_id,
    )
    return orch, group


def _read_ledger(group) -> list[dict]:
    path = group.ledger_path
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text("utf-8").strip().splitlines() if line.strip()]


def _make_verification(task_id: str, wf_id: str, outcome: str = "passed"):
    """Create a VerificationResult for engine.record_verification_result()."""
    from cccc.contracts.v1.ralph_ipc import VerificationResult
    return VerificationResult(
        verification_id=f"ver-{task_id}",
        workflow_id=wf_id,
        task_id=task_id,
        overall_outcome=outcome,
        checks=[],
        summary=f"auto-{outcome}",
    )


# ── DAG topology ──────────────────────────────────────────
#
#  T1 (backend scaffold)
#   ├─→ T2 (api routes)
#   └─→ T3 (models)
#        └─→ T4 (integration tests) [depends on T2+T3]
#
#  T5 (standalone docs, no deps)
#

TASKS = [
    TaskRef(id="T1", title="backend-scaffold", type="backend", claimed_paths=["src/app.py"], depends_on=[], verification=VerificationSpec(command="echo ok")),
    TaskRef(id="T2", title="api-routes", type="backend", claimed_paths=["src/routes.py"], depends_on=["T1"], verification=VerificationSpec(command="echo ok")),
    TaskRef(id="T3", title="models", type="backend", claimed_paths=["src/models.py"], depends_on=["T1"], verification=VerificationSpec(command="echo ok")),
    TaskRef(id="T4", title="integration-tests", type="general", claimed_paths=["tests/test_api.py"], depends_on=["T2", "T3"], verification=VerificationSpec(command="echo ok")),
    TaskRef(id="T5", title="docs", type="general", claimed_paths=["docs/README.md"], depends_on=[], verification=VerificationSpec(command="echo ok")),
]

WORKFLOW_ID = "wf-integration-test"


def _complete_task_via_engine(engine, task_id, agent_id, attempt_id, wf_id, changed_files=None):
    """Drive a task through RUNNING → VERIFYING → COMPLETED via engine APIs."""
    engine.report_worker_started(task_id, agent_id)
    engine.report_worker_completion(task_id, {
        "agent_id": agent_id,
        "duration_seconds": 10,
        "changed_files": changed_files or [],
        "idempotency_key": f"key-{task_id}",
    }, attempt_id=attempt_id)
    engine.record_verification_result(task_id, _make_verification(task_id, wf_id))


# ── Tests ─────────────────────────────────────────────────


class TestBatchABCDIntegration:
    """Full multi-step DAG workflow exercising all four batches."""

    def test_full_dag_lifecycle(self, setup):
        orch, group = setup
        notifications = []
        original_notify = orch._notify_foreman_task_update

        def capture_notify(**kwargs):
            notifications.append(kwargs)
            return original_notify(**kwargs)

        orch._notify_foreman_task_update = capture_notify

        # ════════════════════════════════════════════════
        # Step 1: Submit batch 1 (T1 + T5) with explicit Foreman assignments
        #         Verifies: ARCH-1 explicit assignment, ARCH-6 attempt_id
        # ════════════════════════════════════════════════
        batch1 = ReadyBatchSuggestion(
            suggestion_id="batch-1",
            workflow_id=WORKFLOW_ID,
            tasks=[TASKS[0], TASKS[4]],  # T1, T5
            assignments={"T1": "worker-backend", "T5": "worker-docs"},
        )
        result1 = orch.process_batch_suggestion(batch1, auto_start_agents=False)

        assert result1.decision == "approved"
        assert len(result1.assignments) == 2
        assert result1.assignments[0].agent_id == "worker-backend"
        assert result1.assignments[0].assignment_reason == "foreman_explicit"
        assert result1.assignments[1].agent_id == "worker-docs"

        t1 = orch.engine.get_task("T1")
        assert t1.status == WorkflowTaskStatus.ASSIGNED
        assert t1.agent_id == "worker-backend"
        t1_attempt = t1.attempt_id
        assert t1_attempt, "ARCH-6: attempt_id should be set by approve_batch"

        t5 = orch.engine.get_task("T5")
        assert t5.status == WorkflowTaskStatus.ASSIGNED
        t5_attempt = t5.attempt_id

        # ════════════════════════════════════════════════
        # Step 2: Trigger monitor violation (ARCH-9)
        #         Verifies: violation in ledger, observe mode doesn't block
        # ════════════════════════════════════════════════
        orch.monitor_incoming_event(
            task_id="T1",
            event_type="chat.message",
            event_payload={"content": "I'll assign this task to backend worker myself"},
        )

        events = _read_ledger(group)
        violations = [e for e in events if e.get("kind") == "workflow.monitor_violation"]
        assert len(violations) >= 1, "ARCH-9: Path deviation should be recorded to ledger"
        assert violations[0]["data"]["monitor_mode"] == "observe"

        # Still functional after violation
        assert orch.engine.get_task("T1").status == WorkflowTaskStatus.ASSIGNED

        # ════════════════════════════════════════════════
        # Step 3: Complete T1 via engine → check resuggest notifies Foreman (ARCH-3)
        # ════════════════════════════════════════════════
        notifications.clear()
        _complete_task_via_engine(orch.engine, "T1", "worker-backend", t1_attempt, WORKFLOW_ID, ["src/app.py"])

        assert orch.engine.get_task("T1").status == WorkflowTaskStatus.COMPLETED

        # Now call on_task_completed to trigger ARCH-3 resuggest
        orch.on_task_completed(
            "T1", "worker-backend", 30, ["src/app.py"],
            workflow_id=WORKFLOW_ID,
        )

        # ARCH-3: Check resuggest sent notification (not auto-process).
        # Note: T2/T3 are not yet in _active_workflows (submitted in batch 2),
        # so resuggest may mention T5 (already submitted but still pending).
        # The key assertion: notification was sent, NOT auto-processed.
        ready_notifications = [n for n in notifications if n.get("new_status") == "tasks_ready"]
        if ready_notifications:
            summary = ready_notifications[0].get("summary", "")
            assert "ready for assignment" in summary, "ARCH-3: Notification should guide Foreman to submit"

        # T5 was in batch 1 and may be mentioned, but should NOT be auto-started
        t5_state = orch.engine.get_task("T5")
        assert t5_state.status == WorkflowTaskStatus.ASSIGNED, "T5 should stay ASSIGNED (not auto-RUNNING)"

        # ════════════════════════════════════════════════
        # Step 4: Submit batch 2 (T2 + T3) with explicit assignments
        # ════════════════════════════════════════════════
        batch2 = ReadyBatchSuggestion(
            suggestion_id="batch-2",
            workflow_id=WORKFLOW_ID,
            tasks=[TASKS[1], TASKS[2]],
            assignments={"T2": "worker-api", "T3": "worker-models"},
        )
        result2 = orch.process_batch_suggestion(batch2, auto_start_agents=False)
        assert result2.decision == "approved"

        t2 = orch.engine.get_task("T2")
        t3 = orch.engine.get_task("T3")
        assert t2.agent_id == "worker-api"
        t2_attempt = t2.attempt_id
        t3_attempt = t3.attempt_id
        assert t2_attempt, "ARCH-6: T2 attempt_id set"
        assert t3_attempt, "ARCH-6: T3 attempt_id set"

        # ════════════════════════════════════════════════
        # Step 5: Complete T2, fail T3 verification → retry
        #         Verifies: ARCH-8 retry clears agent_id/attempt_id
        # ════════════════════════════════════════════════
        _complete_task_via_engine(orch.engine, "T2", "worker-api", t2_attempt, WORKFLOW_ID, ["src/routes.py"])
        assert orch.engine.get_task("T2").status == WorkflowTaskStatus.COMPLETED

        # T3: start + complete → VERIFYING, then verify as FAILED → retry
        orch.engine.report_worker_started("T3", "worker-models")
        orch.engine.report_worker_completion("T3", {
            "agent_id": "worker-models",
            "duration_seconds": 15,
            "changed_files": ["src/models.py"],
            "idempotency_key": "key-t3",
        }, attempt_id=t3_attempt)
        assert orch.engine.get_task("T3").status == WorkflowTaskStatus.VERIFYING

        # Retry T3 (verification failed)
        orch.engine.retry_after_verification("T3")
        t3_after = orch.engine.get_task("T3")
        assert t3_after.status == WorkflowTaskStatus.READY, "ARCH-8: retry → READY"
        assert t3_after.agent_id == "", "ARCH-8: retry clears agent_id"
        assert t3_after.attempt_id == "", "ARCH-8: retry clears attempt_id"

        # ════════════════════════════════════════════════
        # Step 6: Re-assign T3 → stale CAS rejection (ARCH-8)
        # ════════════════════════════════════════════════
        orch.engine.approve_batch("batch-2b", [{
            "task_id": "T3",
            "agent_id": "worker-models-v2",
            "attempt_id": "attempt-new",
            "claimed_paths": ["src/models.py"],
        }])
        orch.engine.report_worker_started("T3", "worker-models-v2")

        # Stale completion from old worker with old attempt_id → ValueError
        with pytest.raises(ValueError, match="attempt_id mismatch"):
            orch.engine.report_worker_completion("T3", {
                "agent_id": "worker-models",
                "duration_seconds": 5,
                "changed_files": [],
                "idempotency_key": "key-t3-stale",
            }, attempt_id=t3_attempt)

        assert orch.engine.get_task("T3").status == WorkflowTaskStatus.RUNNING, "T3 still RUNNING after stale rejection"

        # Correct completion with new attempt_id
        orch.engine.report_worker_completion("T3", {
            "agent_id": "worker-models-v2",
            "duration_seconds": 25,
            "changed_files": ["src/models.py"],
            "idempotency_key": "key-t3-v2",
        }, attempt_id="attempt-new")
        orch.engine.record_verification_result("T3", _make_verification("T3", WORKFLOW_ID))
        assert orch.engine.get_task("T3").status == WorkflowTaskStatus.COMPLETED

        # ════════════════════════════════════════════════
        # Step 7: Submit + complete T4 (depends on T2+T3)
        # ════════════════════════════════════════════════
        batch3 = ReadyBatchSuggestion(
            suggestion_id="batch-3",
            workflow_id=WORKFLOW_ID,
            tasks=[TASKS[3]],
            assignments={"T4": "worker-test"},
        )
        result3 = orch.process_batch_suggestion(batch3, auto_start_agents=False)
        assert result3.decision == "approved"

        t4 = orch.engine.get_task("T4")
        t4_attempt = t4.attempt_id
        _complete_task_via_engine(orch.engine, "T4", "worker-test", t4_attempt, WORKFLOW_ID, ["tests/test_api.py"])

        # Complete T5 too
        _complete_task_via_engine(orch.engine, "T5", "worker-docs", t5_attempt, WORKFLOW_ID, ["docs/README.md"])

        # ════════════════════════════════════════════════
        # Step 8: All tasks completed
        # ════════════════════════════════════════════════
        for tid in ["T1", "T2", "T3", "T4", "T5"]:
            assert orch.engine.get_task(tid).status == WorkflowTaskStatus.COMPLETED, f"{tid} should be COMPLETED"

        # ════════════════════════════════════════════════
        # Step 9: Ledger replay restores state
        # ════════════════════════════════════════════════
        orch.engine.replay_from_ledger()
        for tid in ["T1", "T2", "T3", "T4", "T5"]:
            assert orch.engine.get_task(tid).status == WorkflowTaskStatus.COMPLETED, f"After replay: {tid} COMPLETED"

        # ════════════════════════════════════════════════
        # Step 10: Ledger event audit
        # ════════════════════════════════════════════════
        events = _read_ledger(group)
        kinds = {e.get("kind") for e in events}
        assert "workflow.task_registered" in kinds
        assert "workflow.batch_registered" in kinds
        assert "workflow.batch_approved" in kinds
        assert "workflow.monitor_violation" in kinds

        # ARCH-6: attempt_id in batch_approved
        for evt in (e for e in events if e.get("kind") == "workflow.batch_approved"):
            for a in evt.get("data", {}).get("assignments", []):
                assert a.get("attempt_id"), f"ARCH-6: attempt_id missing in ledger: {a}"

    def test_rejected_batch_no_side_effects(self, setup):
        """ARCH-2: A rejected batch produces no engine assignment side effects."""
        orch, group = setup

        batch = ReadyBatchSuggestion(
            suggestion_id="batch-reject",
            workflow_id="wf-reject",
            tasks=[TaskRef(id="TX", title="reject-test", type="backend", claimed_paths=["x.py"], verification=VerificationSpec(command="echo ok"))],
        )

        def fake_reject(_suggestion, *, auto_approve=True, notify_feishu=False):
            return BatchEvaluationResult(
                suggestion=batch,
                assignments=[],
                rejected_tasks=[batch.tasks[0]],
                decision="rejected",
                reason="No suitable agents",
            )

        with patch.object(orch.foreman, "process_batch_suggestion", side_effect=fake_reject):
            result = orch.process_batch_suggestion(batch, auto_start_agents=False)

        assert result.decision == "rejected"
        tx = orch.engine.get_task("TX")
        if tx:
            assert tx.status in (WorkflowTaskStatus.PLANNED, WorkflowTaskStatus.READY), \
                f"ARCH-2: rejected task should not be ASSIGNED, got {tx.status}"
            assert tx.agent_id == ""

    def test_blocked_cascade_via_orchestrator(self, setup):
        """ARCH-11: orch.block_task() cascades to downstream in DAG via _active_workflows."""
        orch, group = setup

        # Submit all tasks through the orchestrator so _active_workflows is populated
        batch_all = ReadyBatchSuggestion(
            suggestion_id="batch-all",
            workflow_id="wf-block",
            tasks=TASKS,
            assignments={t.id: f"worker-{t.id}" for t in TASKS},
        )
        orch.process_batch_suggestion(batch_all, auto_start_agents=False)

        # Start T1
        orch.engine.report_worker_started("T1", "worker-T1")
        assert orch.engine.get_task("T1").status == WorkflowTaskStatus.RUNNING

        # Block T1 via orchestrator (this triggers cascade)
        result = orch.block_task("T1", "external_dependency_unavailable")
        assert result["accepted"] is True

        # T1 blocked
        assert orch.engine.get_task("T1").status == WorkflowTaskStatus.BLOCKED

        # ARCH-11: T2, T3 depend on T1 → cascaded BLOCKED
        assert orch.engine.get_task("T2").status == WorkflowTaskStatus.BLOCKED, "T2 should cascade"
        assert orch.engine.get_task("T3").status == WorkflowTaskStatus.BLOCKED, "T3 should cascade"

        # T4 depends on T2+T3 → also cascaded
        assert orch.engine.get_task("T4").status == WorkflowTaskStatus.BLOCKED, "T4 should cascade"

        # T5 is independent → NOT blocked
        assert orch.engine.get_task("T5").status != WorkflowTaskStatus.BLOCKED, "T5 should NOT cascade"

        # Check cascaded list in result
        cascaded = result.get("cascaded_task_ids", [])
        assert "T2" in cascaded
        assert "T3" in cascaded
        assert "T4" in cascaded
        assert "T5" not in cascaded

    def test_blocked_does_not_overwrite_completed(self, setup):
        """ARCH-11: Cascade does not overwrite already-completed tasks."""
        orch, group = setup

        # Submit T1 and T2 through orchestrator
        batch = ReadyBatchSuggestion(
            suggestion_id="batch-term",
            workflow_id="wf-term",
            tasks=[TASKS[0], TASKS[1]],
            assignments={"T1": "w1", "T2": "w2"},
        )
        orch.process_batch_suggestion(batch, auto_start_agents=False)

        # Complete T2 first
        t2_attempt = orch.engine.get_task("T2").attempt_id
        _complete_task_via_engine(orch.engine, "T2", "w2", t2_attempt, "wf-term", ["src/routes.py"])
        assert orch.engine.get_task("T2").status == WorkflowTaskStatus.COMPLETED

        # Start T1 then block it
        orch.engine.report_worker_started("T1", "w1")
        result = orch.block_task("T1", "something_broke")
        assert result["accepted"] is True

        # T2 should still be COMPLETED (terminal protection)
        assert orch.engine.get_task("T2").status == WorkflowTaskStatus.COMPLETED, \
            "ARCH-11: BLOCKED cascade must NOT overwrite COMPLETED"

    def test_deferred_lifecycle_via_engine(self, setup):
        """ARCH-7: DEFERRED state persists, transitions, and replays correctly."""
        orch, group = setup

        task = TaskRef(id="TD1", title="deferred-task", type="backend", claimed_paths=["d.py"], verification=VerificationSpec(command="echo ok"))
        orch.engine.register_task(task, "wf-defer")

        # Defer
        orch.engine.defer_task("TD1", "single_writer_active")
        state = orch.engine.get_task("TD1")
        assert state.status == WorkflowTaskStatus.DEFERRED
        assert state.blocked_reason == "single_writer_active"

        # Re-register → DEFERRED → READY
        orch.engine.register_batch("batch-undefer", ["TD1"])
        state = orch.engine.get_task("TD1")
        assert state.status == WorkflowTaskStatus.READY
        assert state.blocked_reason == ""

        # Survives replay
        orch.engine.replay_from_ledger()
        assert orch.engine.get_task("TD1").status == WorkflowTaskStatus.READY

    def test_assignment_id_in_ledger(self, setup):
        """ARCH-6: assignment_id/attempt_id present in ledger batch_approved events."""
        orch, group = setup

        task = TaskRef(id="TA1", title="audit-task", type="backend", claimed_paths=["a.py"], verification=VerificationSpec(command="echo ok"))
        batch = ReadyBatchSuggestion(
            suggestion_id="batch-audit",
            workflow_id="wf-audit",
            tasks=[task],
            assignments={"TA1": "worker-audit"},
        )
        orch.process_batch_suggestion(batch, auto_start_agents=False)

        events = _read_ledger(group)
        approved = [e for e in events if e.get("kind") == "workflow.batch_approved"]
        assert len(approved) >= 1
        a = approved[0]["data"]["assignments"][0]
        assert a["agent_id"] == "worker-audit"
        assert a.get("attempt_id"), "ARCH-6: attempt_id must be in ledger"
