from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cccc.agentflow.af_engine import AFExecutionEngine
from cccc.agentflow.legacy_engine import LegacyExecutionEngine
from cccc.agentflow.plan_compiler import PlanCompiler
from cccc.contracts.v1.agent_lease import AgentLease
from cccc.contracts.v1.execution_bundle import (
    CCCCNodeMeta,
    ExecutionBundle,
    VerificationSpec,
)
from cccc.contracts.v1.ralph_ipc import (
    ReadyBatchSuggestion,
    TaskRef,
    VerificationSpec as RalphVerificationSpec,
)
from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

ASSIGNED = "assigned"
COMPLETED = "completed"
DEPENDENT_TASK_ID = "T2"
FAILED = "failed"
GROUP_ID = "group-1"
ROOT_TASK_ID = "T1"
VERIFYING = "verifying"
RUNNING = "running"
WORKFLOW_ID = "workflow-1"


class _Pool:
    def acquire(self, request: object) -> AgentLease:
        node_id = getattr(request, "node_id", "")
        attempt_id = getattr(request, "attempt_id", "")
        return AgentLease(
            lease_id=f"lease-{node_id or 'node'}",
            agent_id="agent-1",
            actor_id="actor-1",
            model_runtime="claude",
            model_id="claude-sonnet-4",
            model_key="claude-sonnet-4",
            is_new_actor=False,
            assignment_reason="test",
            task_id=node_id,
            node_id=node_id,
            attempt_id=attempt_id,
        )

    def release(self, lease: AgentLease, outcome: str) -> None:
        del lease, outcome

    def mark_failed(self, lease: AgentLease, reason: str) -> None:
        del lease, reason


class _Gateway:
    def __init__(self) -> None:
        self.send_calls: list[dict[str, object]] = []

    async def send_task(self, **kwargs: object) -> None:
        self.send_calls.append(kwargs)


class _Trace:
    def __init__(self) -> None:
        self.attempt_ids: list[str] = []

    async def poll_terminal(self, attempt_id: str) -> SimpleNamespace:
        self.attempt_ids.append(attempt_id)
        return SimpleNamespace(kind="task_completed")


def _task(
    task_id: str,
    *,
    depends_on: list[str] | None = None,
    covers_tasks: list[str] | None = None,
    covers_paths: list[str] | None = None,
) -> dict:
    task = {
        "id": task_id,
        "title": f"Task {task_id}",
        "goal_behavior": f"Execute {task_id}",
        "acceptance_criteria": f"{task_id} completes successfully.",
        "depends_on": depends_on or [],
        "role": "worker",
    }
    if covers_tasks is not None or covers_paths is not None:
        task["verification"] = {
            "level": "integration",
            "checks": [
                {
                    "name": "pytest",
                    "command": "python -m pytest -q",
                }
            ],
            "covers": {
                "tasks": covers_tasks or [],
                "paths": covers_paths or [],
            },
        }
    return task


def _compile(tasks: list[dict], workflow_id: str = WORKFLOW_ID) -> ExecutionBundle:
    return PlanCompiler().compile(
        {"tasks": tasks},
        workflow_id=workflow_id,
        group_id=GROUP_ID,
    )


def _engine() -> AFExecutionEngine:
    return AFExecutionEngine(
        agent_pool=_Pool(),
        actor_gateway=_Gateway(),
        trace_bridge=_Trace(),
    )


def _suggestion(workflow_id: str = WORKFLOW_ID) -> ReadyBatchSuggestion:
    return ReadyBatchSuggestion(
        suggestion_id="sg-af-e2e",
        workflow_id=workflow_id,
        tasks=[
            TaskRef(
                id=ROOT_TASK_ID,
                title="Compile AF bundle",
                goal_behavior="Compile the workflow into an AF execution bundle.",
                role="leaf",
                claimed_paths=["src/cccc/daemon/foreman/workflow_orchestrator.py"],
                verification=RalphVerificationSpec(
                    level="unit",
                    command="python -m pytest tests/agentflow/test_af_e2e_integration.py -v",
                ),
                acceptance_criteria="Bundle contains one executable node.",
            )
        ],
    )


def test_plan_compiler_to_af_engine_e2e() -> None:
    bundle = _compile(
        [
            _task(ROOT_TASK_ID),
            _task(DEPENDENT_TASK_ID, depends_on=[ROOT_TASK_ID]),
        ]
    )

    results = _engine().execute_bundle(bundle, workflow_id=bundle.workflow_id)

    assert isinstance(bundle, ExecutionBundle)
    assert list(results) == [ROOT_TASK_ID, DEPENDENT_TASK_ID]
    assert all(result["status"] == COMPLETED for result in results.values())
    assert isinstance(bundle.cccc_meta[ROOT_TASK_ID], CCCCNodeMeta)
    assert bundle.cccc_meta[ROOT_TASK_ID].task_id == ROOT_TASK_ID
    assert bundle.cccc_meta[DEPENDENT_TASK_ID].task_id == DEPENDENT_TASK_ID


def test_per_workflow_isolation_e2e(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    success_bundle = _compile([_task(ROOT_TASK_ID)], workflow_id="workflow-success")
    failed_bundle = _compile([_task("T-fail")], workflow_id="workflow-failed")
    original_execute = engine._execute_with_af

    def execute_with_selected_failure(
        node: dict,
        meta: CCCCNodeMeta | None,
        bundle: ExecutionBundle,
    ) -> dict:
        if node["id"] == "T-fail":
            raise RuntimeError("workflow-specific failure")
        return original_execute(node, meta, bundle)

    monkeypatch.setattr(engine, "_execute_with_af", execute_with_selected_failure)

    success_results = engine.execute_bundle(
        success_bundle,
        workflow_id=success_bundle.workflow_id,
    )
    failed_results = engine.execute_bundle(
        failed_bundle,
        workflow_id=failed_bundle.workflow_id,
    )

    assert success_results[ROOT_TASK_ID]["status"] == COMPLETED
    assert failed_results["T-fail"]["status"] == FAILED
    assert engine.get_status("workflow-success") == COMPLETED
    assert engine.get_status("workflow-failed") == FAILED


def test_verification_spec_covers_preserved() -> None:
    bundle = _compile(
        [
            _task(
                ROOT_TASK_ID,
                covers_tasks=[ROOT_TASK_ID, DEPENDENT_TASK_ID],
                covers_paths=["tests/agentflow/test_af_e2e_integration.py"],
            )
        ]
    )

    spec = bundle.cccc_meta[ROOT_TASK_ID].verification_spec

    assert isinstance(spec, VerificationSpec)
    assert spec.covers_tasks == (ROOT_TASK_ID, DEPENDENT_TASK_ID)
    assert spec.covers_paths == ("tests/agentflow/test_af_e2e_integration.py",)


def test_status_callback_receives_transitions() -> None:
    events: list[tuple[str, str, str]] = []
    bundle = _compile([_task(ROOT_TASK_ID)], workflow_id="workflow-callback")

    _engine().execute_bundle(
        bundle,
        workflow_id=bundle.workflow_id,
        status_callback=lambda node_id, status, workflow_id: events.append(
            (node_id, status, workflow_id)
        ),
    )

    assert events == [
        (ROOT_TASK_ID, ASSIGNED, "workflow-callback"),
        (ROOT_TASK_ID, RUNNING, "workflow-callback"),
        (ROOT_TASK_ID, VERIFYING, "workflow-callback"),
    ]


def test_af_engine_missing_deps_raises() -> None:
    bundle = _compile([_task("T-missing")], workflow_id="workflow-missing")
    node = bundle.pipeline["nodes"][0]
    meta = bundle.cccc_meta[node["id"]]
    engine = AFExecutionEngine(agent_pool=Mock(), actor_gateway=None)

    with pytest.raises(RuntimeError, match="T-missing"):
        engine._execute_with_af(node, meta, bundle)

    results = engine.execute_bundle(bundle, workflow_id=bundle.workflow_id)

    assert results["T-missing"]["status"] == FAILED
    assert "requires agent_pool, actor_gateway, and trace_bridge" in results["T-missing"]["error"]


def test_legacy_engine_with_orchestrator_delegates() -> None:
    bundle = _compile([_task(ROOT_TASK_ID)], workflow_id="workflow-legacy")
    engine = LegacyExecutionEngine(
        orchestrator=SimpleNamespace(_assignment_controller=object())
    )

    results = engine.execute_bundle(bundle)

    assert results[ROOT_TASK_ID]["status"] == COMPLETED
    assert results[ROOT_TASK_ID]["delegated_to"] == "assignment_controller"


def test_pre_dispatch_fallback_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrator = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
    orchestrator.group_id = GROUP_ID
    orchestrator._send_message_fn = None
    orchestrator._assignment_controller = None

    monkeypatch.setattr(AFExecutionEngine, "is_available", staticmethod(lambda: True))

    def raise_compile_error(
        self,
        plan: dict,
        workflow_id: str,
        group_id: str,
    ) -> ExecutionBundle:
        del self, plan, workflow_id, group_id
        raise RuntimeError("compile exploded")

    monkeypatch.setattr(PlanCompiler, "compile", raise_compile_error)

    orchestrator._try_af_execution(_suggestion())
