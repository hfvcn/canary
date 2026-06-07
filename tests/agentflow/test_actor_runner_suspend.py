import asyncio
import logging
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Optional

from cccc.agentflow.actor_runner import (
    CANCEL_EXIT_CODE,
    FAILURE_EXIT_CODE,
    SUCCESS_EXIT_CODE,
    CCCCActorRunner,
)
from cccc.contracts.v1.agent_lease import AgentAcquireRequest, AgentLease, AssignmentPolicy

AGENT_ID = "agent-1"
ATTEMPT_ID = "attempt-1"
GROUP_ID = "group-1"
NODE_ID = "T1"
POLL_INTERVAL = 0.001
WAIT_TIMEOUT = 0.05
WORKFLOW_ID = "workflow-1"


@dataclass(frozen=True)
class _Meta:
    task: dict
    attempt_id: str = ATTEMPT_ID
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


class _EventStream:
    def __init__(self) -> None:
        self.attempt_ids: list[str] = []
        self.poll_count = 0
        self._event: Optional[SimpleNamespace] = None

    async def poll_terminal(self, attempt_id: str) -> Optional[SimpleNamespace]:
        self.attempt_ids.append(attempt_id)
        self.poll_count += 1
        event = self._event
        self._event = None
        return event

    def record_terminal(self, kind: str) -> None:
        self._event = SimpleNamespace(kind=kind)


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
        attempt_id=ATTEMPT_ID,
    )


def _runner(
    *,
    pool: Optional[_Pool] = None,
    event_stream: Optional[_EventStream] = None,
    timeout: float = WAIT_TIMEOUT,
) -> CCCCActorRunner:
    return CCCCActorRunner(
        agent_pool=pool,
        event_stream=event_stream,
        poll_interval=POLL_INTERVAL,
        timeout=timeout,
        sidecar={NODE_ID: _Meta(task={"id": NODE_ID})},
    )


def _node() -> dict:
    return {"id": NODE_ID, "prompt": "Run task"}


async def _wait_for_polls(stream: _EventStream, minimum_polls: int) -> None:
    deadline = asyncio.get_running_loop().time() + WAIT_TIMEOUT
    while stream.poll_count < minimum_polls:
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(f"poll count did not reach {minimum_polls}")
        await asyncio.sleep(0)


def test_execute_waits_for_terminal_and_wakes_on_completion(caplog) -> None:
    pool = _Pool(_lease())
    stream = _EventStream()
    runner = _runner(pool=pool, event_stream=stream)
    caplog.set_level(logging.INFO, logger="cccc.agentflow.actor_runner")

    async def exercise():
        pending = asyncio.create_task(runner.execute(_node()))
        await _wait_for_polls(stream, minimum_polls=3)
        assert pending.done() is False
        stream.record_terminal("task_completed")
        return await asyncio.wait_for(pending, timeout=WAIT_TIMEOUT)

    result = asyncio.run(exercise())

    assert result.exit_code == SUCCESS_EXIT_CODE
    assert result.stdout_lines == ["completed"]
    assert stream.poll_count >= 3
    assert stream.attempt_ids == [ATTEMPT_ID] * stream.poll_count
    assert pool.release_calls == [(pool.lease, "completed")]
    assert "[af] worker terminal received" in caplog.text
    assert "attempt_id=attempt-1" in caplog.text
    assert "kind=task_completed" in caplog.text


def test_execute_times_out_when_terminal_never_arrives() -> None:
    pool = _Pool(_lease())
    result = asyncio.run(_runner(pool=pool, event_stream=_EventStream(), timeout=0.01).execute(_node()))

    assert result.exit_code == FAILURE_EXIT_CODE
    assert "terminal timeout" in result.stderr_lines[0]
    assert ATTEMPT_ID in result.stderr_lines[0]
    assert pool.failed_calls == [(pool.lease, f"terminal timeout attempt_id={ATTEMPT_ID}")]


def test_execute_can_cancel_while_waiting_for_terminal() -> None:
    pool = _Pool(_lease())
    stream = _EventStream()
    should_cancel = lambda: stream.poll_count >= 2

    result = asyncio.run(
        _runner(pool=pool, event_stream=stream).execute(_node(), should_cancel=should_cancel)
    )

    assert result.exit_code == CANCEL_EXIT_CODE
    assert result.cancelled is True
    assert pool.release_calls == [(pool.lease, "cancelled")]


def test_execute_maps_task_failed_to_failed_result() -> None:
    pool = _Pool(_lease())
    stream = _EventStream()
    stream.record_terminal("task_failed")

    result = asyncio.run(_runner(pool=pool, event_stream=stream).execute(_node()))

    assert result.exit_code == FAILURE_EXIT_CODE
    assert "task_failed" in result.stderr_lines[0]
    assert pool.failed_calls == [(pool.lease, "worker terminal kind=task_failed")]


def test_execute_maps_task_cancelled_terminal_to_cancelled_result() -> None:
    pool = _Pool(_lease())
    stream = _EventStream()
    stream.record_terminal("task_cancelled")

    result = asyncio.run(_runner(pool=pool, event_stream=stream).execute(_node()))

    assert result.exit_code == CANCEL_EXIT_CODE
    assert result.cancelled is True
    assert pool.release_calls == [(pool.lease, "cancelled")]


def test_execute_maps_unknown_terminal_kind_to_failed_result() -> None:
    pool = _Pool(_lease())
    stream = _EventStream()
    stream.record_terminal("mystery_terminal")

    result = asyncio.run(_runner(pool=pool, event_stream=stream).execute(_node()))

    assert result.exit_code == FAILURE_EXIT_CODE
    assert "mystery_terminal" in result.stderr_lines[0]
    assert pool.failed_calls == [(pool.lease, "worker terminal kind=mystery_terminal")]
