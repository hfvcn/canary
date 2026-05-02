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

from cccc.contracts.v1.ralph_ipc import ReadyBatchSuggestion, TaskRef, VerificationResult
from cccc.daemon.foreman.prompt_builder import build_task_prompt
from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
from cccc.kernel.workflow_state import WorkflowTaskStatus
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
        data["tasks"][0]["title"] = "CHANGED TITLE"
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
            TaskRef(id="T-up", title="upstream", type="backend", claimed_paths=["src/a.py"]),
            TaskRef(id="T-down", title="downstream", type="backend", depends_on=["T-up"], claimed_paths=["src/b.py"]),
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
