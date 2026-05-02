"""Wave 2 integration tests — plan-digest freshness guard end-to-end.

Tests:
1. Register plan, run workflow, edit plan mid-workflow (add task + suppress),
   attempt task complete -> assert hard-block (PreTransitionVetoed).
2. Re-run with override_stale_digest=True -> assert pass + ledger event
   with override_used=true.
3. Scan ledger for exactly one workflow.plan_digest_divergence event.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml

from cccc.contracts.v1.ralph_ipc import (
    ReadyBatchSuggestion,
    TaskEvent,
    TaskRef,
    VerificationResult,
)
from cccc.kernel.workflow_state import WorkflowEngine, WorkflowTaskStatus
from cccc.kernel.workflow_state_types import (
    KIND_PLAN_DIGEST_DIVERGENCE,
    PreTransitionVetoed,
)
from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
from cccc.ralph.plan_io import compute_structural_plan_digest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

WORKFLOW_ID = "wf-wave2-test"
BATCH_ID = "batch-wave2-test"


def _plan_digest(path: Path) -> str:
    return compute_structural_plan_digest(path)


def _write_plan(path: Path, payload: Dict[str, Any]) -> Path:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _base_plan() -> Dict[str, Any]:
    return {
        "tasks": [
            {
                "id": "T1",
                "title": "Initial task",
                "claimed_paths": ["src/module.py"],
                "acceptance_criteria": "module works",
                "verification": {
                    "level": "unit",
                    "command": "pytest tests/test_module.py -q",
                },
            },
        ],
    }


def _edited_plan() -> Dict[str, Any]:
    """Plan with an added task and a suppress annotation (simulates mid-workflow edit)."""
    return {
        "tasks": [
            {
                "id": "T1",
                "title": "Initial task",
                "claimed_paths": ["src/module.py"],
                "acceptance_criteria": "module works",
                "verification": {
                    "level": "unit",
                    "command": "pytest tests/test_module.py -q",
                },
            },
            {
                "id": "T2",
                "title": "Added mid-workflow",
                "claimed_paths": ["src/extra.py"],
                "acceptance_criteria": "extra logic",
                "verification": {
                    "level": "unit",
                    "command": "pytest tests/test_extra.py -q",
                },
            },
        ],
        "suppress": ["W_EMPTY_ACCEPTANCE"],
    }


def _build_orchestrator(tmp_path: Path, plan_path: Path) -> WorkflowOrchestrator:
    """Build a WorkflowOrchestrator wired to a temp group with the plan digest registered."""
    orch = WorkflowOrchestrator(
        project_root=tmp_path,
        group_id="wave2-test-group",
    )
    # Register workflow metadata with the plan digest
    digest = _plan_digest(plan_path)
    orch.engine.set_workflow_meta(
        WORKFLOW_ID,
        plan_path=str(plan_path),
        plan_digest=digest,
    )
    return orch


def _advance_task_to_running(
    orch: WorkflowOrchestrator,
    task_ref: TaskRef,
    agent_id: str = "agent-1",
) -> None:
    """Register, batch, approve, and start a task so it reaches RUNNING."""
    orch.engine.register_task(task_ref, WORKFLOW_ID)
    orch.engine.register_batch(BATCH_ID, [task_ref.id])
    orch.engine.approve_batch(
        BATCH_ID,
        [{"task_id": task_ref.id, "agent_id": agent_id, "claimed_paths": task_ref.claimed_paths}],
    )
    orch.engine.report_worker_started(task_ref.id, agent_id)
    state = orch.engine.get_task(task_ref.id)
    assert state is not None
    assert state.status == WorkflowTaskStatus.RUNNING


def _read_ledger_events(ledger_path: Path) -> List[Dict[str, Any]]:
    """Parse all JSONL events from the ledger file."""
    events: List[Dict[str, Any]] = []
    if not ledger_path.exists():
        return events
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))
    return events


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_plan_digest_divergence_hard_blocks_completion(tmp_path: Path) -> None:
    """Editing the plan mid-workflow MUST hard-block task completion (PreTransitionVetoed)."""
    plan_path = _write_plan(tmp_path / "plan.yaml", _base_plan())
    orch = _build_orchestrator(tmp_path, plan_path)

    task_ref = TaskRef(
        id="T1",
        title="Initial task",
        claimed_paths=["src/module.py"],
        acceptance_criteria="module works",
    )
    _advance_task_to_running(orch, task_ref)

    # Mutate the plan on disk (add a task + suppress)
    _write_plan(plan_path, _edited_plan())
    assert _plan_digest(plan_path) != orch.engine.get_workflow_meta(WORKFLOW_ID).plan_digest

    # Attempt completion — should raise PreTransitionVetoed
    event = TaskEvent(
        event_type="completed",
        task_id="T1",
        payload={
            "agent_id": "agent-1",
            "duration_seconds": 42,
            "changed_files": ["src/module.py"],
        },
    )
    result = orch.apply_task_event(event, override_stale_digest=False)
    assert result["accepted"] is False
    assert result["code"] == "plan_digest_divergence"
    assert "plan_digest_divergence" in result["reason"]


def test_override_stale_digest_allows_completion(tmp_path: Path) -> None:
    """override_stale_digest=True MUST allow completion and emit a ledger event with override_used."""
    plan_path = _write_plan(tmp_path / "plan.yaml", _base_plan())
    orch = _build_orchestrator(tmp_path, plan_path)

    task_ref = TaskRef(
        id="T1",
        title="Initial task",
        claimed_paths=["src/module.py"],
        acceptance_criteria="module works",
    )
    _advance_task_to_running(orch, task_ref)

    # Mutate the plan on disk
    _write_plan(plan_path, _edited_plan())

    # Attempt completion with override_stale_digest=True — should succeed
    event = TaskEvent(
        event_type="completed",
        task_id="T1",
        payload={
            "agent_id": "agent-1",
            "duration_seconds": 42,
            "changed_files": ["src/module.py"],
        },
    )
    result = orch.apply_task_event(event, override_stale_digest=True)
    assert result["accepted"] is True
    assert "verification_outcome" in result

    # Verify ledger has divergence event with override_used=true
    ledger_events = _read_ledger_events(orch.group.ledger_path)
    divergence_events = [
        ev for ev in ledger_events
        if ev.get("kind") == KIND_PLAN_DIGEST_DIVERGENCE
    ]
    assert len(divergence_events) >= 1, (
        f"Expected at least 1 {KIND_PLAN_DIGEST_DIVERGENCE} event in ledger, "
        f"found {len(divergence_events)}"
    )
    # At least one must have override_used=True
    override_events = [
        ev for ev in divergence_events
        if ev.get("data", {}).get("override_used") is True
    ]
    assert len(override_events) >= 1, (
        "Expected at least one divergence event with override_used=True"
    )


def test_exactly_one_divergence_event_in_ledger(tmp_path: Path) -> None:
    """Full scenario: block, then override — ledger MUST contain exactly one
    workflow.plan_digest_divergence event from the vetoed (blocked) attempt.

    The override pass also emits divergence events (one per pre-transition hook
    checkpoint), but those have override_used=True.  The vetoed attempt produces
    exactly one event with override_used absent or False.
    """
    plan_path = _write_plan(tmp_path / "plan.yaml", _base_plan())
    orch = _build_orchestrator(tmp_path, plan_path)

    task_ref = TaskRef(
        id="T1",
        title="Initial task",
        claimed_paths=["src/module.py"],
        acceptance_criteria="module works",
    )
    _advance_task_to_running(orch, task_ref)

    # Mutate plan
    _write_plan(plan_path, _edited_plan())

    # First attempt: no override — should block
    event = TaskEvent(
        event_type="completed",
        task_id="T1",
        payload={
            "agent_id": "agent-1",
            "duration_seconds": 42,
            "changed_files": ["src/module.py"],
        },
    )
    result_blocked = orch.apply_task_event(event, override_stale_digest=False)
    assert result_blocked["accepted"] is False

    # Task should still be RUNNING (the transition was vetoed).
    state_after_block = orch.engine.get_task("T1")
    assert state_after_block is not None
    assert state_after_block.status == WorkflowTaskStatus.RUNNING

    # Second attempt: with override — should succeed
    result_override = orch.apply_task_event(event, override_stale_digest=True)
    assert result_override["accepted"] is True

    # Scan ledger: collect all divergence events
    ledger_events = _read_ledger_events(orch.group.ledger_path)
    divergence_events = [
        ev for ev in ledger_events
        if ev.get("kind") == KIND_PLAN_DIGEST_DIVERGENCE
    ]
    assert len(divergence_events) >= 1, "Expected at least 1 divergence event"

    # Exactly one vetoed (non-override) event from the blocked attempt
    vetoed_events = [
        ev for ev in divergence_events
        if not ev.get("data", {}).get("override_used")
    ]
    assert len(vetoed_events) == 1, (
        f"Expected exactly 1 vetoed divergence event, got {len(vetoed_events)}"
    )

    # At least one override event from the successful pass
    override_events = [
        ev for ev in divergence_events
        if ev.get("data", {}).get("override_used") is True
    ]
    assert len(override_events) >= 1, (
        "Expected at least 1 divergence event with override_used=True"
    )
