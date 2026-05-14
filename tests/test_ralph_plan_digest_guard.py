"""Tests for W2-1 — pre-transition plan digest freshness guard.

Covers:
  (a)  Stale plan → task completion vetoed, only divergence event in ledger
  (a2) Verification-passed also vetoed on stale plan
  (a3) Verification-failed also vetoed on stale plan
  (a4) Verification-skipped also vetoed on stale plan
  (a5) Task-failed also vetoed on stale plan
  (b)  --force-stale-complete overrides → event has override_used=true
  (c)  W_REGISTERED_PLAN_STALE emitted by validator
  (d)  Existing test_foreman_workflow.py tests still pass (not duplicated here — run separately)
  (e)  Post-hoc advisory behavior
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import List

import pytest

from cccc.contracts.v1.ralph_ipc import (
    TaskEvent,
    TaskRef,
    VerificationResult,
)
from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
from cccc.kernel.workflow_state_types import (
    KIND_PLAN_DIGEST_DIVERGENCE,
    KIND_PLAN_DIGEST_DIVERGENCE_POST_HOC,
    PreTransitionVetoed,
    WorkflowMeta,
)
from cccc.ralph.plan_io import compute_structural_plan_digest
from cccc.ralph.validator import check_plan_digest_freshness


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _prepare_project_root(project_root: Path) -> Path:
    for rel in (".cccc/agents", ".cccc/models", ".cccc/capabilities"):
        (project_root / rel).mkdir(parents=True, exist_ok=True)
    from cccc.contracts.v1.agent import ModelRegistry
    from cccc.daemon.ops.agent_ops import save_model_registry
    save_model_registry(ModelRegistry(models={}), project_root / ".cccc" / "models" / "registry.yaml")
    return project_root


def _register_running_task(
    orchestrator: WorkflowOrchestrator,
    task: TaskRef,
    *,
    workflow_id: str = "wf-digest",
    agent_id: str = "worker-1",
) -> None:
    """Register a task and advance it to RUNNING for event testing."""
    orchestrator.engine.register_task(task, workflow_id)
    orchestrator.engine.register_batch(f"b-{task.id}", [task.id])
    orchestrator.engine.approve_batch(
        f"b-{task.id}",
        [{"task_id": task.id, "agent_id": agent_id, "claimed_paths": []}],
    )
    orchestrator.engine.report_worker_started(task.id, agent_id)


def _write_plan(plan_path: Path, content: str = "tasks: []") -> str:
    """Write a plan file and return its structural digest.

    Shorthand strings (no ``:``) produce structurally distinct plans by
    varying ``claimed_paths`` (a structural field included in the digest).
    """
    rendered = content
    if ":" not in content and not content.lstrip().startswith("{"):
        rendered = (
            f"tasks:\n  - id: T1\n    claimed_paths:\n      - {content!r}\n"
        )
    plan_path.write_text(rendered, encoding="utf-8")
    return compute_structural_plan_digest(plan_path)


@pytest.fixture
def project_root(tmp_path):
    return _prepare_project_root(tmp_path)


@pytest.fixture
def orchestrator(project_root, monkeypatch):
    monkeypatch.setattr(
        "cccc.daemon.foreman.workflow_orchestrator.load_group",
        lambda gid: None,
    )
    orch = WorkflowOrchestrator(project_root=project_root, group_id="test-digest")
    monkeypatch.setattr(orch.reporter, "on_task_completed", lambda *a, **kw: True)
    monkeypatch.setattr(orch.reporter, "on_task_failed", lambda *a, **kw: True)
    return orch


def _ledger_events(orchestrator: WorkflowOrchestrator) -> list[dict]:
    """Read all ledger events."""
    ledger_path = orchestrator.group.ledger_path
    if not ledger_path.exists():
        return []
    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _events_of_kind(orchestrator: WorkflowOrchestrator, kind: str) -> list[dict]:
    return [e for e in _ledger_events(orchestrator) if e.get("kind") == kind]


# ---------------------------------------------------------------------------
# (a) Stale plan → task completion vetoed
# ---------------------------------------------------------------------------

class TestStalePlanVetoed:
    """When a plan file has been modified after registration, task completions are blocked."""

    def test_stale_plan_vetoes_completion(self, orchestrator, project_root, monkeypatch):
        """(a) Completion should be vetoed and divergence event written."""
        plan_path = project_root / "plan.yaml"
        original_digest = _write_plan(plan_path, "tasks:\n  - id: T1\n")

        task = TaskRef(id="T-a1", title="Test task", type="backend")
        _register_running_task(orchestrator, task, workflow_id="wf-a1")
        orchestrator.engine.set_workflow_meta("wf-a1", plan_path=str(plan_path), plan_digest=original_digest)

        # Mutate the plan file
        _write_plan(plan_path, "tasks:\n  - id: T1\n  - id: T2\n")

        # Stub verification so we can reach the completion gate
        verification = VerificationResult(
            verification_id="ver-a1",
            workflow_id="wf-a1",
            task_id="T-a1",
            overall_outcome="passed",
            checks=[],
            summary="ok",
        )
        monkeypatch.setattr(orchestrator.ralph, "verify_completion", lambda *a, **kw: verification)

        result = orchestrator.apply_task_event(
            TaskEvent(
                task_id="T-a1",
                event_type="completed",
                payload={
                    "agent_id": "worker-1",
                    "duration_seconds": 5,
                    "changed_files": [],
                },
            )
        )

        assert result["accepted"] is False
        assert "plan_digest_divergence" in result.get("reason", "")

        # Divergence event should be in ledger
        divergence_events = _events_of_kind(orchestrator, KIND_PLAN_DIGEST_DIVERGENCE)
        assert len(divergence_events) >= 1
        data = divergence_events[0]["data"]
        assert data["task_id"] == "T-a1"
        assert data["code"] == "plan_digest_divergence"

    def test_stale_plan_vetoes_verification_passed(self, orchestrator, project_root, monkeypatch):
        """(a2) Verification-passed should also be vetoed on stale plan."""
        plan_path = project_root / "plan.yaml"
        original_digest = _write_plan(plan_path, "original")

        task = TaskRef(id="T-a2", title="Test task", type="backend")
        _register_running_task(orchestrator, task, workflow_id="wf-a2")
        orchestrator.engine.set_workflow_meta("wf-a2", plan_path=str(plan_path), plan_digest=original_digest)

        # Mutate plan
        _write_plan(plan_path, "modified")

        # Try to complete — hooks will fire on report_worker_completion
        verification = VerificationResult(
            verification_id="ver-a2",
            workflow_id="wf-a2",
            task_id="T-a2",
            overall_outcome="passed",
            checks=[],
            summary="ok",
        )
        monkeypatch.setattr(orchestrator.ralph, "verify_completion", lambda *a, **kw: verification)

        result = orchestrator.apply_task_event(
            TaskEvent(
                task_id="T-a2",
                event_type="completed",
                payload={"agent_id": "worker-1", "duration_seconds": 1, "changed_files": []},
            )
        )

        assert result["accepted"] is False

    def test_stale_plan_vetoes_verification_failed(self, orchestrator, project_root, monkeypatch):
        """(a3) Verification-failed should also be vetoed on stale plan."""
        plan_path = project_root / "plan.yaml"
        original_digest = _write_plan(plan_path, "original")

        task = TaskRef(id="T-a3", title="Test task", type="backend")
        _register_running_task(orchestrator, task, workflow_id="wf-a3")
        orchestrator.engine.set_workflow_meta("wf-a3", plan_path=str(plan_path), plan_digest=original_digest)

        # Mutate plan
        _write_plan(plan_path, "modified")

        verification = VerificationResult(
            verification_id="ver-a3",
            workflow_id="wf-a3",
            task_id="T-a3",
            overall_outcome="failed",
            checks=[],
            summary="test failed",
        )
        monkeypatch.setattr(orchestrator.ralph, "verify_completion", lambda *a, **kw: verification)

        result = orchestrator.apply_task_event(
            TaskEvent(
                task_id="T-a3",
                event_type="completed",
                payload={"agent_id": "worker-1", "duration_seconds": 1, "changed_files": []},
            )
        )

        assert result["accepted"] is False

    def test_stale_plan_vetoes_verification_skipped(self, orchestrator, project_root, monkeypatch):
        """(a4) Verification-skipped should also be vetoed on stale plan."""
        plan_path = project_root / "plan.yaml"
        original_digest = _write_plan(plan_path, "original")

        task = TaskRef(id="T-a4", title="Test task", type="backend")
        _register_running_task(orchestrator, task, workflow_id="wf-a4")
        orchestrator.engine.set_workflow_meta("wf-a4", plan_path=str(plan_path), plan_digest=original_digest)

        # Mutate plan
        _write_plan(plan_path, "modified")

        verification = VerificationResult(
            verification_id="ver-a4",
            workflow_id="wf-a4",
            task_id="T-a4",
            overall_outcome="skipped",
            checks=[],
            summary="no checks",
        )
        monkeypatch.setattr(orchestrator.ralph, "verify_completion", lambda *a, **kw: verification)

        result = orchestrator.apply_task_event(
            TaskEvent(
                task_id="T-a4",
                event_type="completed",
                payload={"agent_id": "worker-1", "duration_seconds": 1, "changed_files": []},
            )
        )

        assert result["accepted"] is False

    def test_stale_plan_vetoes_task_failed(self, orchestrator, project_root, monkeypatch):
        """(a5) Task-failed should also be vetoed on stale plan."""
        plan_path = project_root / "plan.yaml"
        original_digest = _write_plan(plan_path, "original")

        task = TaskRef(id="T-a5", title="Test task", type="backend")
        _register_running_task(orchestrator, task, workflow_id="wf-a5")
        orchestrator.engine.set_workflow_meta("wf-a5", plan_path=str(plan_path), plan_digest=original_digest)

        # Mutate plan
        _write_plan(plan_path, "modified")

        result = orchestrator.apply_task_event(
            TaskEvent(
                task_id="T-a5",
                event_type="failed",
                payload={
                    "agent_id": "worker-1",
                    "error_message": "boom",
                },
            )
        )

        assert result["accepted"] is False
        assert "plan_digest_divergence" in result.get("reason", "")


# ---------------------------------------------------------------------------
# Fresh plan → operations proceed normally
# ---------------------------------------------------------------------------

class TestFreshPlanAllowed:
    """When the plan file is unchanged, operations proceed as normal."""

    def test_fresh_plan_allows_completion(self, orchestrator, project_root, monkeypatch):
        plan_path = project_root / "plan.yaml"
        digest = _write_plan(plan_path, "tasks:\n  - id: T-fresh\n")

        task = TaskRef(id="T-fresh", title="Fresh task", type="backend")
        _register_running_task(orchestrator, task, workflow_id="wf-fresh")
        orchestrator.engine.set_workflow_meta("wf-fresh", plan_path=str(plan_path), plan_digest=digest)

        verification = VerificationResult(
            verification_id="ver-fresh",
            workflow_id="wf-fresh",
            task_id="T-fresh",
            overall_outcome="passed",
            checks=[],
            summary="ok",
        )
        monkeypatch.setattr(orchestrator.ralph, "verify_completion", lambda *a, **kw: verification)

        result = orchestrator.apply_task_event(
            TaskEvent(
                task_id="T-fresh",
                event_type="completed",
                payload={"agent_id": "worker-1", "duration_seconds": 3, "changed_files": []},
            )
        )

        assert result["accepted"] is True

    def test_no_meta_allows_completion(self, orchestrator, project_root, monkeypatch):
        """Tasks without registered workflow meta should pass through freely."""
        task = TaskRef(id="T-nometa", title="No meta", type="backend")
        _register_running_task(orchestrator, task, workflow_id="wf-nometa")
        # Note: no set_workflow_meta call

        verification = VerificationResult(
            verification_id="ver-nometa",
            workflow_id="wf-nometa",
            task_id="T-nometa",
            overall_outcome="passed",
            checks=[],
            summary="ok",
        )
        monkeypatch.setattr(orchestrator.ralph, "verify_completion", lambda *a, **kw: verification)

        result = orchestrator.apply_task_event(
            TaskEvent(
                task_id="T-nometa",
                event_type="completed",
                payload={"agent_id": "worker-1", "duration_seconds": 1, "changed_files": []},
            )
        )

        assert result["accepted"] is True


# ---------------------------------------------------------------------------
# (b) --force-stale-complete override
# ---------------------------------------------------------------------------

class TestForceStaleCompleteOverride:
    """The override_stale_digest flag should bypass the guard."""

    def test_override_allows_stale_completion(self, orchestrator, project_root, monkeypatch):
        plan_path = project_root / "plan.yaml"
        original_digest = _write_plan(plan_path, "original")

        task = TaskRef(id="T-b1", title="Override task", type="backend")
        _register_running_task(orchestrator, task, workflow_id="wf-b1")
        orchestrator.engine.set_workflow_meta("wf-b1", plan_path=str(plan_path), plan_digest=original_digest)

        # Mutate plan
        _write_plan(plan_path, "modified")

        verification = VerificationResult(
            verification_id="ver-b1",
            workflow_id="wf-b1",
            task_id="T-b1",
            overall_outcome="passed",
            checks=[],
            summary="ok",
        )
        monkeypatch.setattr(orchestrator.ralph, "verify_completion", lambda *a, **kw: verification)

        result = orchestrator.apply_task_event(
            TaskEvent(
                task_id="T-b1",
                event_type="completed",
                payload={"agent_id": "worker-1", "duration_seconds": 2, "changed_files": []},
            ),
            override_stale_digest=True,
        )

        assert result["accepted"] is True

        # Should still have a divergence event with override_used=True
        divergence_events = _events_of_kind(orchestrator, KIND_PLAN_DIGEST_DIVERGENCE)
        assert any(
            e["data"].get("override_used") is True
            for e in divergence_events
        ), "Expected a divergence event with override_used=True"


# ---------------------------------------------------------------------------
# (c) W_REGISTERED_PLAN_STALE emitted by validator
# ---------------------------------------------------------------------------

class TestValidatorPlanStaleness:
    """check_plan_digest_freshness should emit W_REGISTERED_PLAN_STALE."""

    def test_stale_plan_emits_warning(self, tmp_path):
        plan_path = tmp_path / "plan.yaml"
        original_digest = _write_plan(plan_path, "original content")

        # Mutate the plan
        _write_plan(plan_path, "modified content")

        issue = check_plan_digest_freshness(plan_path, original_digest)

        assert issue is not None
        assert issue.code == "W_REGISTERED_PLAN_STALE"
        assert issue.severity == "warning"
        assert original_digest[:12] in issue.message
        assert "modified since registration" in issue.message

    def test_fresh_plan_no_warning(self, tmp_path):
        plan_path = tmp_path / "plan.yaml"
        digest = _write_plan(plan_path, "unchanged content")

        issue = check_plan_digest_freshness(plan_path, digest)

        assert issue is None

    def test_no_digest_no_warning(self, tmp_path):
        plan_path = tmp_path / "plan.yaml"
        _write_plan(plan_path, "content")

        issue = check_plan_digest_freshness(plan_path, "")

        assert issue is None

    def test_missing_file_no_warning(self, tmp_path):
        plan_path = tmp_path / "nonexistent.yaml"

        issue = check_plan_digest_freshness(plan_path, "abc123")

        assert issue is None


# ---------------------------------------------------------------------------
# (e) Post-hoc advisory behavior
# ---------------------------------------------------------------------------

class TestPostHocAdvisory:
    """Post-hoc check should emit advisory events without blocking."""

    def test_post_hoc_emits_advisory_on_stale(self, orchestrator, project_root):
        plan_path = project_root / "plan.yaml"
        original_digest = _write_plan(plan_path, "original")
        orchestrator.engine.set_workflow_meta("wf-post", plan_path=str(plan_path), plan_digest=original_digest)

        # Mutate plan
        _write_plan(plan_path, "modified")

        # Call post-hoc check directly
        orchestrator._post_hoc_plan_digest_check("T-post", "wf-post")

        post_hoc_events = _events_of_kind(orchestrator, KIND_PLAN_DIGEST_DIVERGENCE_POST_HOC)
        assert len(post_hoc_events) >= 1
        data = post_hoc_events[0]["data"]
        assert data["task_id"] == "T-post"
        assert data["code"] == "plan_digest_divergence_post_hoc"

    def test_post_hoc_silent_on_fresh(self, orchestrator, project_root):
        plan_path = project_root / "plan.yaml"
        digest = _write_plan(plan_path, "unchanged")
        orchestrator.engine.set_workflow_meta("wf-fresh-post", plan_path=str(plan_path), plan_digest=digest)

        orchestrator._post_hoc_plan_digest_check("T-fresh-post", "wf-fresh-post")

        post_hoc_events = _events_of_kind(orchestrator, KIND_PLAN_DIGEST_DIVERGENCE_POST_HOC)
        assert len(post_hoc_events) == 0

    def test_post_hoc_silent_on_no_meta(self, orchestrator):
        # No workflow meta registered — should be a no-op
        orchestrator._post_hoc_plan_digest_check("T-none", "wf-nonexistent")

        post_hoc_events = _events_of_kind(orchestrator, KIND_PLAN_DIGEST_DIVERGENCE_POST_HOC)
        assert len(post_hoc_events) == 0


# ---------------------------------------------------------------------------
# PreTransitionVetoed class behavior
# ---------------------------------------------------------------------------

class TestOperationalFieldsExcluded:
    """RO-61: Operational fields (verification, title, goal_behavior) excluded from digest."""

    def test_verification_command_change_same_digest(self, tmp_path):
        plan_path = tmp_path / "plan.yaml"
        plan_path.write_text(
            "tasks:\n  - id: T1\n    claimed_paths: [src/]\n"
            "    verification:\n      level: integration\n      command: pytest tests/\n",
            encoding="utf-8",
        )
        digest_before = compute_structural_plan_digest(plan_path)

        plan_path.write_text(
            "tasks:\n  - id: T1\n    claimed_paths: [src/]\n"
            "    verification:\n      level: integration\n      command: sh -c 'pytest tests/'\n",
            encoding="utf-8",
        )
        digest_after = compute_structural_plan_digest(plan_path)

        assert digest_before == digest_after

    def test_title_change_same_digest(self, tmp_path):
        plan_path = tmp_path / "plan.yaml"
        plan_path.write_text("tasks:\n  - id: T1\n    title: Old title\n", encoding="utf-8")
        d1 = compute_structural_plan_digest(plan_path)

        plan_path.write_text("tasks:\n  - id: T1\n    title: New title\n", encoding="utf-8")
        d2 = compute_structural_plan_digest(plan_path)

        assert d1 == d2

    def test_structural_change_different_digest(self, tmp_path):
        plan_path = tmp_path / "plan.yaml"
        plan_path.write_text("tasks:\n  - id: T1\n    depends_on: []\n", encoding="utf-8")
        d1 = compute_structural_plan_digest(plan_path)

        plan_path.write_text("tasks:\n  - id: T1\n    depends_on: [T0]\n", encoding="utf-8")
        d2 = compute_structural_plan_digest(plan_path)

        assert d1 != d2

    def test_claimed_paths_change_different_digest(self, tmp_path):
        plan_path = tmp_path / "plan.yaml"
        plan_path.write_text("tasks:\n  - id: T1\n    claimed_paths: [src/]\n", encoding="utf-8")
        d1 = compute_structural_plan_digest(plan_path)

        plan_path.write_text("tasks:\n  - id: T1\n    claimed_paths: [lib/]\n", encoding="utf-8")
        d2 = compute_structural_plan_digest(plan_path)

        assert d1 != d2

    def test_goal_behavior_change_same_digest(self, tmp_path):
        plan_path = tmp_path / "plan.yaml"
        plan_path.write_text("tasks:\n  - id: T1\n    goal_behavior: old\n", encoding="utf-8")
        d1 = compute_structural_plan_digest(plan_path)

        plan_path.write_text("tasks:\n  - id: T1\n    goal_behavior: new\n", encoding="utf-8")
        d2 = compute_structural_plan_digest(plan_path)

        assert d1 == d2


class TestPreTransitionVetoed:
    """Verify the exception class itself works correctly."""

    def test_attributes(self):
        exc = PreTransitionVetoed(code="test_code", message="test message")
        assert exc.code == "test_code"
        assert str(exc) == "test message"
        assert isinstance(exc, RuntimeError)


# ---------------------------------------------------------------------------
# WorkflowMeta
# ---------------------------------------------------------------------------

class TestWorkflowMeta:
    """Verify WorkflowMeta dataclass."""

    def test_defaults(self):
        meta = WorkflowMeta(workflow_id="wf-1")
        assert meta.workflow_id == "wf-1"
        assert meta.plan_path == ""
        assert meta.plan_digest == ""

    def test_with_values(self):
        meta = WorkflowMeta(workflow_id="wf-2", plan_path="/tmp/plan.yaml", plan_digest="abc123")
        assert meta.plan_path == "/tmp/plan.yaml"
        assert meta.plan_digest == "abc123"


# ---------------------------------------------------------------------------
# Engine hook system
# ---------------------------------------------------------------------------

class TestEngineHookSystem:
    """Verify the engine hook system independently."""

    def test_register_and_run_hook(self, orchestrator):
        calls = []

        def my_hook(task_id, kind, ctx):
            calls.append((task_id, kind, ctx))

        orchestrator.engine.register_pre_transition_hook(my_hook)

        task = TaskRef(id="T-hook", title="Hook test", type="backend")
        _register_running_task(orchestrator, task, workflow_id="wf-hook")

        # Completing should trigger the hook
        orchestrator.engine.report_worker_completion(
            "T-hook",
            {"agent_id": "worker-1", "duration_seconds": 1, "changed_files": []},
        )

        # Hook was called at least for the completion event
        assert any(c[0] == "T-hook" for c in calls)

    def test_hook_veto_blocks_transition(self, orchestrator):
        task = TaskRef(id="T-block", title="Block test", type="backend")
        _register_running_task(orchestrator, task, workflow_id="wf-block")

        # Register the blocking hook AFTER task is already in RUNNING state
        def blocking_hook(task_id, kind, ctx):
            raise PreTransitionVetoed(code="blocked", message="blocked by test")

        orchestrator.engine.register_pre_transition_hook(blocking_hook)

        with pytest.raises(PreTransitionVetoed, match="blocked by test"):
            orchestrator.engine.report_worker_completion(
                "T-block",
                {"agent_id": "worker-1", "duration_seconds": 1, "changed_files": []},
            )

        # Task should still be RUNNING (transition blocked)
        state = orchestrator.engine.get_task("T-block")
        assert state is not None
        assert state.status.value == "running"


# ---------------------------------------------------------------------------
# RalphService defense-in-depth
# ---------------------------------------------------------------------------

class TestRalphServiceDefenseInDepth:
    """RalphService._auto_sync_plan_state advisory."""

    def test_advisory_logs_on_mismatch(self, tmp_path, caplog):
        import logging
        from cccc.daemon.foreman.ralph_service import RalphService

        service = RalphService(project_root=tmp_path, group_id="test")
        plan_path = tmp_path / "plan.yaml"
        original_digest = _write_plan(plan_path, "original")
        _write_plan(plan_path, "modified")

        with caplog.at_level(logging.WARNING, logger="cccc.daemon.foreman.ralph_service"):
            service._auto_sync_plan_state(str(plan_path), original_digest)

        assert any("Plan digest advisory" in r.message for r in caplog.records)

    def test_advisory_silent_on_match(self, tmp_path, caplog):
        import logging
        from cccc.daemon.foreman.ralph_service import RalphService

        service = RalphService(project_root=tmp_path, group_id="test")
        plan_path = tmp_path / "plan.yaml"
        digest = _write_plan(plan_path, "unchanged")

        with caplog.at_level(logging.WARNING, logger="cccc.daemon.foreman.ralph_service"):
            service._auto_sync_plan_state(str(plan_path), digest)

        assert not any("Plan digest advisory" in r.message for r in caplog.records)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
