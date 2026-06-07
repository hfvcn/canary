from types import SimpleNamespace

import pytest

from cccc.agentflow.actor_runner import CCCCActorRunner
from cccc.agentflow.af_engine import AFExecutionEngine
from cccc.agentflow.legacy_engine import LegacyExecutionEngine
from cccc.contracts.v1.agent_lease import AgentLease
from cccc.contracts.v1.execution_bundle import CCCCNodeMeta, ExecutionBundle

GROUP_ID = "group-1"
NODE_ID = "T1"
WORKFLOW_ID = "workflow-1"


class _Pool:
    def __init__(self, lease: AgentLease) -> None:
        self.lease = lease

    def acquire(self, request: object) -> AgentLease:
        return self.lease

    def release(self, lease: AgentLease, outcome: str) -> None:
        del lease, outcome


class _Gateway:
    def __init__(self) -> None:
        self.send_calls: list[dict] = []

    async def send_task(self, **kwargs: dict) -> None:
        self.send_calls.append(kwargs)


class _Trace:
    def __init__(self) -> None:
        self.attempt_ids: list[str] = []

    async def poll_terminal(self, attempt_id: str) -> SimpleNamespace:
        self.attempt_ids.append(attempt_id)
        return SimpleNamespace(kind="task_completed")


def _lease() -> AgentLease:
    return AgentLease(
        lease_id="lease-1",
        agent_id="agent-1",
        actor_id="actor-1",
        model_runtime="claude",
        model_id="claude-sonnet-4",
        model_key="claude-sonnet-4",
        is_new_actor=False,
        assignment_reason="test",
        task_id=NODE_ID,
        node_id=NODE_ID,
    )


def _node() -> dict:
    return {"id": NODE_ID, "prompt": "Run task", "depends_on": []}


def _meta() -> CCCCNodeMeta:
    return CCCCNodeMeta(
        task={"id": NODE_ID},
        group_id=GROUP_ID,
        workflow_id=WORKFLOW_ID,
        assignment_policy={"mode": "auto"},
    )


def _bundle() -> ExecutionBundle:
    node = _node()
    return ExecutionBundle(
        run_id="run-1",
        workflow_id=WORKFLOW_ID,
        pipeline={"nodes": [node]},
        cccc_meta={NODE_ID: _meta()},
    )


def _engine() -> AFExecutionEngine:
    return AFExecutionEngine(
        agent_pool=_Pool(_lease()),
        actor_gateway=_Gateway(),
        trace_bridge=_Trace(),
    )


def test_af_engine_with_full_dependencies_calls_runner_execute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    original_execute = CCCCActorRunner.execute

    async def execute_spy(self: CCCCActorRunner, node: dict, *args: object, **kwargs: object):
        calls.append(node["id"])
        return await original_execute(self, node, *args, **kwargs)

    monkeypatch.setattr(CCCCActorRunner, "execute", execute_spy)

    result = _engine()._execute_with_af(_node(), _meta(), _bundle())

    assert calls == [NODE_ID]
    assert result["engine"] == "af"
    assert result["exit_code"] == 0


def test_af_engine_with_missing_dependencies_raises_runtime_error() -> None:
    engine = AFExecutionEngine()

    with pytest.raises(RuntimeError, match=NODE_ID):
        engine._execute_with_af(_node(), _meta(), _bundle())


def test_af_engine_result_includes_attempt_id() -> None:
    result = _engine()._execute_with_af(_node(), _meta(), _bundle())

    assert result["attempt_id"]
    assert NODE_ID in result["attempt_id"]


def test_legacy_engine_with_orchestrator_delegates_to_assignment_controller() -> None:
    orchestrator = SimpleNamespace(_assignment_controller=object())
    engine = LegacyExecutionEngine(orchestrator=orchestrator)

    assert engine._execute_node(_node(), _meta(), _bundle()) == {
        "status": "completed",
        "engine": "legacy",
        "duration": 0,
        "node_id": NODE_ID,
        "delegated_to": "assignment_controller",
    }


def test_legacy_engine_without_orchestrator_returns_dry_run() -> None:
    engine = LegacyExecutionEngine()

    assert engine._execute_node(_node(), _meta(), _bundle()) == {
        "duration": 0,
        "note": "no orchestrator (dry run)",
    }
