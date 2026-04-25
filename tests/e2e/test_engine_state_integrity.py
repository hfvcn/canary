"""E2E tests for Engine state transition integrity (Batch D).

Verifies:
- ARCH-7: DEFERRED persisted in Engine, register_batch state boundary
- ARCH-8: retry clears agent_id/attempt_id, CAS on stale completion
- ARCH-11: BLOCKED cascades to downstream DAG, diamond dedup, terminal protection
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from cccc.contracts.v1.ralph_ipc import ReadyBatchSuggestion, TaskRef
from cccc.kernel.workflow_state_types import (
    KIND_TASK_BLOCKED,
    KIND_TASK_DEFERRED,
    WorkflowTaskStatus,
)


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
def group(temp_home, temp_project_dir):
    from cccc.kernel.group import attach_scope_to_group, create_group
    from cccc.kernel.registry import load_registry
    from cccc.kernel.scope import detect_scope

    reg = load_registry()
    grp = create_group(reg, title="engine-integrity-test", topic="")
    scope = detect_scope(temp_project_dir)
    grp = attach_scope_to_group(reg, grp, scope, set_active=True)
    return grp


@pytest.fixture()
def engine(group):
    from cccc.kernel.workflow_state import WorkflowEngine

    return WorkflowEngine(group)


@pytest.fixture()
def orchestrator(temp_home, temp_project_dir, group):
    from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

    return WorkflowOrchestrator(
        project_root=temp_project_dir,
        group_id=group.group_id,
    )


# ──────────────────────────────────────────────────────────
# ARCH-7: DEFERRED persistence
# ──────────────────────────────────────────────────────────


class TestDeferredPersistence:
    def test_deferred_persisted_in_engine(self, engine):
        """DEFERRED state persists in ledger and survives replay."""
        task = TaskRef(id="T1", title="task-1", type="backend", claimed_paths=["a.py"])
        engine.register_task(task, "wf-1")
        engine.defer_task("T1", "single_writer_active")

        # Verify state
        state = engine.get_task("T1")
        assert state.status == WorkflowTaskStatus.DEFERRED
        assert state.blocked_reason == "single_writer_active"

        # Verify ledger event
        events = _read_ledger_events(engine)
        deferred_events = [e for e in events if e["kind"] == KIND_TASK_DEFERRED]
        assert len(deferred_events) == 1
        assert deferred_events[0]["data"]["reason"] == "single_writer_active"

        # Replay and verify
        engine.replay_from_ledger()
        state = engine.get_task("T1")
        assert state.status == WorkflowTaskStatus.DEFERRED
        assert state.blocked_reason == "single_writer_active"

    def test_deferred_to_ready_clears_blocked_reason(self, engine):
        """register_batch clears blocked_reason when moving DEFERRED → READY."""
        task = TaskRef(id="T1", title="task-1", type="backend", claimed_paths=["a.py"])
        engine.register_task(task, "wf-1")
        engine.defer_task("T1", "single_writer_active")

        # Re-register in new batch → should become READY with clean state
        engine.register_batch("batch-2", ["T1"])
        state = engine.get_task("T1")
        assert state.status == WorkflowTaskStatus.READY
        assert state.blocked_reason == ""

    def test_register_batch_rejects_invalid_source_states(self, engine):
        """register_batch only accepts PLANNED/READY/DEFERRED, rejects others."""
        task = TaskRef(id="T1", title="task-1", type="backend", claimed_paths=["a.py"])
        engine.register_task(task, "wf-1")
        engine.register_batch("batch-1", ["T1"])
        engine.approve_batch("batch-1", [{"task_id": "T1", "agent_id": "agent-1", "claimed_paths": ["a.py"]}])
        engine.report_worker_started("T1", "agent-1")

        # RUNNING → register_batch should fail
        with pytest.raises(ValueError, match="non-batchable status"):
            engine.register_batch("batch-2", ["T1"])


# ──────────────────────────────────────────────────────────
# ARCH-8: retry + attempt_id CAS
# ──────────────────────────────────────────────────────────


class TestRetryAndAttemptId:
    def _setup_task_to_verifying(self, engine):
        """Helper: register → batch → approve → start → complete → VERIFYING."""
        task = TaskRef(id="T1", title="task-1", type="backend", claimed_paths=["a.py"])
        engine.register_task(task, "wf-1")
        engine.register_batch("batch-1", ["T1"])
        engine.approve_batch("batch-1", [
            {"task_id": "T1", "agent_id": "agent-A", "attempt_id": "attempt-1", "claimed_paths": ["a.py"]},
        ])
        engine.report_worker_started("T1", "agent-A")
        engine.report_worker_completion("T1", {
            "agent_id": "agent-A", "duration_seconds": 10,
            "changed_files": [], "idempotency_key": "key-1",
        }, attempt_id="attempt-1")
        return engine

    def test_retry_clears_agent_id_and_attempt_id(self, engine):
        """After retry, agent_id and attempt_id are empty."""
        self._setup_task_to_verifying(engine)

        state = engine.get_task("T1")
        assert state.status == WorkflowTaskStatus.VERIFYING
        assert state.agent_id == "agent-A"
        assert state.attempt_id == "attempt-1"

        engine.retry_after_verification("T1")
        state = engine.get_task("T1")
        assert state.status == WorkflowTaskStatus.READY
        assert state.agent_id == ""
        assert state.attempt_id == ""

        # Re-assign with new attempt
        engine.approve_batch("batch-2", [
            {"task_id": "T1", "agent_id": "agent-B", "attempt_id": "attempt-2", "claimed_paths": ["a.py"]},
        ])
        state = engine.get_task("T1")
        assert state.agent_id == "agent-B"
        assert state.attempt_id == "attempt-2"

    def test_stale_completion_rejected_by_attempt_id(self, engine):
        """Old worker's completion with wrong attempt_id is rejected."""
        self._setup_task_to_verifying(engine)
        engine.retry_after_verification("T1")

        # Re-assign with new attempt_id
        engine.approve_batch("batch-2", [
            {"task_id": "T1", "agent_id": "agent-B", "attempt_id": "attempt-2", "claimed_paths": ["a.py"]},
        ])
        engine.report_worker_started("T1", "agent-B")

        # Old agent tries to complete with stale attempt_id
        with pytest.raises(ValueError, match="attempt_id mismatch"):
            engine.report_worker_completion("T1", {
                "agent_id": "agent-A", "duration_seconds": 5,
                "changed_files": [], "idempotency_key": "key-stale",
            }, attempt_id="attempt-1")

    def test_old_client_completion_backward_compat(self, engine):
        """Old client without attempt_id can still complete (CAS skipped).
        Even when engine has attempt_id, empty caller attempt_id skips CAS."""
        task = TaskRef(id="T1", title="task-1", type="backend", claimed_paths=["a.py"])
        engine.register_task(task, "wf-1")
        engine.register_batch("batch-1", ["T1"])
        # Approve WITH attempt_id (new engine generates it)
        engine.approve_batch("batch-1", [
            {"task_id": "T1", "agent_id": "agent-A", "attempt_id": "att-server", "claimed_paths": ["a.py"]},
        ])
        engine.report_worker_started("T1", "agent-A")

        # Old client completes without attempt_id — CAS skipped, should succeed
        engine.report_worker_completion("T1", {
            "agent_id": "agent-A", "duration_seconds": 5,
            "changed_files": [], "idempotency_key": "key-old",
        })
        state = engine.get_task("T1")
        assert state.status == WorkflowTaskStatus.VERIFYING


# ──────────────────────────────────────────────────────────
# ARCH-11: BLOCKED cascade
# ──────────────────────────────────────────────────────────


class TestBlockedCascade:
    def _setup_dag(self, orchestrator, dag_spec):
        """Helper: Register tasks with dependencies in orchestrator.

        dag_spec: list of (task_id, title, depends_on, claimed_paths)
        """
        orch = orchestrator
        workflow_id = "wf-cascade"

        # Register tasks in engine
        for tid, title, deps, paths in dag_spec:
            task = TaskRef(id=tid, title=title, type="backend",
                           claimed_paths=paths, depends_on=deps)
            orch.engine.register_task(task, workflow_id)

        # Set up _active_workflows shadow state
        orch._active_workflows[workflow_id] = {
            "workflow_id": workflow_id,
            "tasks": {},
            "batches": [],
        }
        for tid, title, deps, paths in dag_spec:
            task = TaskRef(id=tid, title=title, type="backend",
                           claimed_paths=paths, depends_on=deps)
            orch._active_workflows[workflow_id]["tasks"][tid] = {
                "status": "pending",
                "task_ref": task,
                "claimed_paths": paths,
            }

        return workflow_id

    def test_blocked_cascades_to_downstream(self, orchestrator):
        """Block T-A → T-B, T-C, T-D all get BLOCKED (linear + branch DAG)."""
        orch = orchestrator
        dag = [
            ("T-A", "task-a", [], ["a.py"]),
            ("T-B", "task-b", ["T-A"], ["b.py"]),
            ("T-C", "task-c", ["T-A"], ["c.py"]),
            ("T-D", "task-d", ["T-B"], ["d.py"]),
        ]
        wf_id = self._setup_dag(orch, dag)

        # Register all in a batch so engine knows them
        orch.engine.register_batch("batch-1", ["T-A", "T-B", "T-C", "T-D"])

        result = orch.block_task("T-A", "manual block")
        assert result["accepted"]

        # All downstream should be BLOCKED
        for tid in ["T-B", "T-C", "T-D"]:
            state = orch.engine.get_task(tid)
            assert state.status == WorkflowTaskStatus.BLOCKED, f"{tid} should be BLOCKED"

        # Verify ledger: exactly 4 block events (T-A + 3 cascade)
        events = _read_ledger_events(orch.engine)
        block_events = [e for e in events if e["kind"] == KIND_TASK_BLOCKED]
        assert len(block_events) == 4

    def test_blocked_diamond_dag_dedup(self, orchestrator):
        """Diamond DAG: T-A → T-B, T-A → T-C, T-B → T-D, T-C → T-D.
        T-D should be blocked exactly once."""
        orch = orchestrator
        dag = [
            ("T-A", "task-a", [], ["a.py"]),
            ("T-B", "task-b", ["T-A"], ["b.py"]),
            ("T-C", "task-c", ["T-A"], ["c.py"]),
            ("T-D", "task-d", ["T-B", "T-C"], ["d.py"]),
        ]
        wf_id = self._setup_dag(orch, dag)
        orch.engine.register_batch("batch-1", ["T-A", "T-B", "T-C", "T-D"])

        result = orch.block_task("T-A", "diamond test")

        # All should be BLOCKED
        for tid in ["T-A", "T-B", "T-C", "T-D"]:
            state = orch.engine.get_task(tid)
            assert state.status == WorkflowTaskStatus.BLOCKED, f"{tid} should be BLOCKED"

        # T-D blocked exactly once (dedup via visited set)
        events = _read_ledger_events(orch.engine)
        block_events = [e for e in events if e["kind"] == KIND_TASK_BLOCKED]
        blocked_ids = [e["data"]["task_id"] for e in block_events]
        assert blocked_ids.count("T-D") == 1, f"T-D should appear once, got: {blocked_ids}"
        assert len(block_events) == 4  # T-A, T-B, T-C, T-D

    def test_block_does_not_overwrite_completed(self, orchestrator):
        """COMPLETED tasks cannot be blocked — engine raises ValueError."""
        orch = orchestrator
        dag = [
            ("T-A", "task-a", [], ["a.py"]),
            ("T-B", "task-b", ["T-A"], ["b.py"]),
        ]
        wf_id = self._setup_dag(orch, dag)
        orch.engine.register_batch("batch-1", ["T-A", "T-B"])
        orch.engine.approve_batch("batch-1", [
            {"task_id": "T-A", "agent_id": "agent-1", "claimed_paths": ["a.py"]},
            {"task_id": "T-B", "agent_id": "agent-2", "claimed_paths": ["b.py"]},
        ])

        # Complete T-A fully
        orch.engine.report_worker_started("T-A", "agent-1")
        orch.engine.report_worker_completion("T-A", {
            "agent_id": "agent-1", "duration_seconds": 5,
            "changed_files": [], "idempotency_key": "key-a",
        })
        from cccc.contracts.v1.ralph_ipc import VerificationResult
        orch.engine.record_verification_result("T-A", VerificationResult(
            verification_id="ver-a", workflow_id=wf_id,
            task_id="T-A", overall_outcome="passed", checks=[], summary="ok",
        ))

        assert orch.engine.get_task("T-A").status == WorkflowTaskStatus.COMPLETED

        # Trying to block COMPLETED should raise
        with pytest.raises(ValueError, match="cannot block terminal task"):
            orch.engine.block_task("T-A", "should fail")

    def test_blocked_running_sibling_unaffected(self, orchestrator):
        """Parallel siblings: block T-A doesn't affect T-B (independent)."""
        orch = orchestrator
        dag = [
            ("T-A", "task-a", [], ["a.py"]),
            ("T-B", "task-b", [], ["b.py"]),
            ("T-C", "task-c", ["T-A", "T-B"], ["c.py"]),
        ]
        wf_id = self._setup_dag(orch, dag)
        orch.engine.register_batch("batch-1", ["T-A", "T-B", "T-C"])
        orch.engine.approve_batch("batch-1", [
            {"task_id": "T-A", "agent_id": "agent-1", "claimed_paths": ["a.py"]},
            {"task_id": "T-B", "agent_id": "agent-2", "claimed_paths": ["b.py"]},
            {"task_id": "T-C", "agent_id": "agent-3", "claimed_paths": ["c.py"]},
        ])
        orch.engine.report_worker_started("T-A", "agent-1")
        orch.engine.report_worker_started("T-B", "agent-2")

        orch.block_task("T-A", "block a")

        # T-A blocked, T-C blocked (depends on T-A), T-B unaffected
        assert orch.engine.get_task("T-A").status == WorkflowTaskStatus.BLOCKED
        assert orch.engine.get_task("T-B").status == WorkflowTaskStatus.RUNNING
        assert orch.engine.get_task("T-C").status == WorkflowTaskStatus.BLOCKED


# ──────────────────────────────────────────────────────────
# Full lifecycle replay
# ──────────────────────────────────────────────────────────


class TestFullLifecycleReplay:
    def test_ledger_replay_full_lifecycle(self, engine):
        """Complete lifecycle: register → defer → undefer → assign → run →
        complete → verify_fail → retry → re-assign → block → cascade.
        Replay restores all state correctly."""
        t1 = TaskRef(id="T1", title="task-1", type="backend",
                     claimed_paths=["a.py"], depends_on=[])
        t2 = TaskRef(id="T2", title="task-2", type="backend",
                     claimed_paths=["b.py"], depends_on=["T1"])

        # Register
        engine.register_task(t1, "wf-1")
        engine.register_task(t2, "wf-1")

        # Defer T1
        engine.defer_task("T1", "single_writer")
        assert engine.get_task("T1").status == WorkflowTaskStatus.DEFERRED

        # Undefer via register_batch
        engine.register_batch("batch-1", ["T1", "T2"])
        assert engine.get_task("T1").status == WorkflowTaskStatus.READY
        assert engine.get_task("T1").blocked_reason == ""

        # Assign with attempt_id
        engine.approve_batch("batch-1", [
            {"task_id": "T1", "agent_id": "agent-A", "attempt_id": "att-1", "claimed_paths": ["a.py"]},
            {"task_id": "T2", "agent_id": "agent-B", "attempt_id": "att-2", "claimed_paths": ["b.py"]},
        ])

        # Run T1
        engine.report_worker_started("T1", "agent-A")
        engine.report_worker_completion("T1", {
            "agent_id": "agent-A", "duration_seconds": 10,
            "changed_files": ["a.py"], "idempotency_key": "key-1",
        }, attempt_id="att-1")

        # Verify fail
        from cccc.contracts.v1.ralph_ipc import VerificationResult
        engine.record_verification_result("T1", VerificationResult(
            verification_id="ver-1", workflow_id="wf-1",
            task_id="T1", overall_outcome="failed", checks=[], summary="bad",
        ))
        assert engine.get_task("T1").status == WorkflowTaskStatus.FAILED

        # Retry — clears agent_id and attempt_id
        engine.retry_after_verification("T1")
        assert engine.get_task("T1").status == WorkflowTaskStatus.READY
        assert engine.get_task("T1").agent_id == ""
        assert engine.get_task("T1").attempt_id == ""

        # Re-assign
        engine.approve_batch("batch-2", [
            {"task_id": "T1", "agent_id": "agent-C", "attempt_id": "att-3", "claimed_paths": ["a.py"]},
        ])
        assert engine.get_task("T1").attempt_id == "att-3"

        # Block T1 → T2 should be blockable too
        engine.report_worker_started("T1", "agent-C")
        engine.block_task("T1", "manual block")
        assert engine.get_task("T1").status == WorkflowTaskStatus.BLOCKED

        # Block T2 (cascade would do this in orchestrator, here we do it manually)
        engine.block_task("T2", "upstream T1 blocked")
        assert engine.get_task("T2").status == WorkflowTaskStatus.BLOCKED

        # Now replay from scratch
        engine.replay_from_ledger()

        # Verify all final states
        assert engine.get_task("T1").status == WorkflowTaskStatus.BLOCKED
        assert engine.get_task("T1").blocked_reason == "manual block"
        assert engine.get_task("T2").status == WorkflowTaskStatus.BLOCKED
        assert engine.get_task("T2").blocked_reason == "upstream T1 blocked"


# ──────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────


def _read_ledger_events(engine) -> list[dict]:
    """Read all events from the engine's ledger file."""
    path = engine._group.ledger_path
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))
    return events
