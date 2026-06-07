import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Optional

from cccc.agentflow.actor_runner import CCCCActorRunner, RawExecutionResult
from cccc.contracts.v1.agent_lease import AgentAcquireRequest, AgentLease, AssignmentPolicy

AGENT_ID = "agent-1"
CANCEL_EXIT_CODE = 130
GROUP_ID = "group-1"
NODE_ID = "T1"
SUCCESS_EXIT_CODE = 0
WORKFLOW_ID = "workflow-1"


@dataclass(frozen=True)
class _Meta:
    task: dict
    group_id: str = GROUP_ID
    workflow_id: str = WORKFLOW_ID
    assignment_policy: AssignmentPolicy = AssignmentPolicy(mode="auto")


class _Pool:
    def __init__(self, lease: AgentLease) -> None:
        self.lease = lease
        self.acquire_calls: list[AgentAcquireRequest] = []
        self.release_calls: list[tuple[AgentLease, str]] = []
        self.failed_calls: list[tuple[AgentLease, str]] = []

    def acquire(self, request: AgentAcquireRequest) -> AgentLease:
        self.acquire_calls.append(request)
        return self.lease

    def release(self, lease: AgentLease, outcome: str) -> None:
        self.release_calls.append((lease, outcome))

    def mark_failed(self, lease: AgentLease, reason: str) -> None:
        self.failed_calls.append((lease, reason))


class _Gateway:
    def __init__(self, error: Optional[Exception] = None) -> None:
        self.error = error
        self.send_calls: list[dict] = []

    async def send_task(self, **kwargs: dict) -> None:
        if self.error:
            raise self.error
        self.send_calls.append(kwargs)


class _EventStream:
    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.attempt_ids: list[str] = []

    async def poll_terminal(self, attempt_id: str) -> SimpleNamespace:
        self.attempt_ids.append(attempt_id)
        return SimpleNamespace(kind=self.kind)


def _lease() -> AgentLease:
    return AgentLease(
        lease_id="lease-1",
        agent_id=AGENT_ID,
        actor_id=AGENT_ID,
        model_runtime="claude",
        model_id="claude-sonnet-4",
        model_key="claude-sonnet-4",
        is_new_actor=False,
        assignment_reason="explicit",
        task_id=NODE_ID,
        node_id=NODE_ID,
    )


def _runner(
    pool: Optional[_Pool] = None,
    gateway: Optional[_Gateway] = None,
    event_stream: Optional[_EventStream] = None,
) -> CCCCActorRunner:
    return CCCCActorRunner(
        agent_pool=pool,
        actor_gateway=gateway,
        event_stream=event_stream,
        sidecar={NODE_ID: _Meta(task={"id": NODE_ID})},
    )


def _node() -> dict:
    return {"id": NODE_ID, "prompt": "Run task"}


def test_execute_dry_run_returns_exit_code_zero() -> None:
    result = asyncio.run(CCCCActorRunner().execute(_node()))

    assert result.exit_code == SUCCESS_EXIT_CODE
    assert result.stdout_lines == [f"dry-run:{NODE_ID}"]
    assert result.cancelled is False


def test_cancel_returns_exit_code_130_and_cancelled_true() -> None:
    pool = _Pool(_lease())

    result = asyncio.run(_runner(pool=pool).execute(_node(), should_cancel=lambda: True))

    assert result.exit_code == CANCEL_EXIT_CODE
    assert result.cancelled is True
    assert pool.release_calls == [(pool.lease, "cancelled")]


def test_lease_released_in_finally_after_terminal_completion() -> None:
    pool = _Pool(_lease())
    event_stream = _EventStream(kind="task_completed")

    result = asyncio.run(_runner(pool=pool, event_stream=event_stream).execute(_node()))

    assert result.exit_code == SUCCESS_EXIT_CODE
    assert pool.release_calls == [(pool.lease, "completed")]


def test_failed_execution_calls_mark_failed() -> None:
    pool = _Pool(_lease())
    gateway = _Gateway(error=RuntimeError("boom"))

    result = asyncio.run(_runner(pool=pool, gateway=gateway).execute(_node()))

    assert result.exit_code == 1
    assert result.stderr_lines == ["boom"]
    assert pool.failed_calls == [(pool.lease, "boom")]


def test_raw_execution_result_instantiation() -> None:
    result = RawExecutionResult(exit_code=SUCCESS_EXIT_CODE)
    other = RawExecutionResult(exit_code=1)

    result.stdout_lines.append("line")

    assert result.stderr_lines == []
    assert result.cancelled is False
    assert other.stdout_lines == []


def test_import_path_works() -> None:
    from cccc.agentflow.actor_runner import CCCCActorRunner as ImportedRunner

    assert ImportedRunner is CCCCActorRunner
