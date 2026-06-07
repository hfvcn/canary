from __future__ import annotations

from pathlib import Path

import pytest

from cccc.contracts.v1.ralph_ipc import ReadyBatchSuggestion, TaskRef, VerificationSpec
from cccc.daemon.foreman.workflow_orchestrator import (
    AF_ENGINE_ENABLED_ENV_VAR,
    WorkflowOrchestrator,
)

EXECUTION_ENGINE_AF = "af"
EXECUTION_ENGINE_LEGACY = "legacy"
WORKFLOW_ID = "wf-af-fallback"


def _orchestrator() -> WorkflowOrchestrator:
    orchestrator = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
    orchestrator.group_id = "g-af-fallback"
    return orchestrator


def _suggestion(workflow_id: str = WORKFLOW_ID) -> ReadyBatchSuggestion:
    return ReadyBatchSuggestion(
        suggestion_id="sg-af-fallback",
        workflow_id=workflow_id,
        tasks=[
            TaskRef(
                id="T1",
                title="Compile AF bundle",
                goal_behavior="Compile the workflow into an AF execution bundle.",
                role="leaf",
                claimed_paths=["src/cccc/daemon/foreman/workflow_orchestrator.py"],
                verification=VerificationSpec(
                    level="unit",
                    command="python -m pytest tests/agentflow/test_engine_fallback.py -v",
                ),
                acceptance_criteria="Bundle contains one executable node.",
            )
        ],
    )


def test_pre_dispatch_fallback_logs_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cccc.agentflow.af_engine import AFExecutionEngine

    orchestrator = _orchestrator()
    orchestrator._send_message_fn = None
    orchestrator._assignment_controller = None
    monkeypatch.setattr(AFExecutionEngine, "is_available", staticmethod(lambda: False))

    orchestrator._try_af_execution(_suggestion())


def test_af_available_compiles_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AF compile path produces correct bundle from task refs."""
    from cccc.agentflow.af_engine import AFExecutionEngine
    from cccc.agentflow.plan_compiler import PlanCompiler
    from cccc.daemon.foreman.af_gateway_bridge import task_ref_to_plan_task, plan_execution_engine

    monkeypatch.setattr(AFExecutionEngine, "is_available", staticmethod(lambda: True))

    suggestion = _suggestion()
    compiler = PlanCompiler()
    task_dicts = [task_ref_to_plan_task(t) for t in suggestion.tasks]
    bundle = compiler.compile(
        {"tasks": task_dicts, "execution_engine": plan_execution_engine(suggestion)},
        workflow_id=WORKFLOW_ID,
        group_id="g-af-fallback",
    )

    assert bundle.workflow_id == WORKFLOW_ID
    assert bundle.pipeline["nodes"][0]["id"] == "T1"


def test_engine_tag_legacy_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrator = WorkflowOrchestrator(project_root=tmp_path, group_id="g-engine-tag-default")
    monkeypatch.setenv(AF_ENGINE_ENABLED_ENV_VAR, "0")

    assert orchestrator._execution_engine_tag == EXECUTION_ENGINE_LEGACY


def test_engine_tag_af_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cccc.agentflow.af_engine import AFExecutionEngine

    orchestrator = _orchestrator()
    monkeypatch.setenv(AF_ENGINE_ENABLED_ENV_VAR, "1")
    monkeypatch.setattr(AFExecutionEngine, "is_available", staticmethod(lambda: True))

    assert orchestrator._execution_engine_tag == EXECUTION_ENGINE_AF
