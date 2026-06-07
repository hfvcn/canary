"""CCCCActorRunner: AF Runner implementation using CCCC daemon persistent actor sessions."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from ..contracts.v1.agent_lease import AgentAcquireRequest, AgentLease, AssignmentPolicy

logger = logging.getLogger("cccc.agentflow.actor_runner")

ATTEMPT_SUFFIX_LENGTH = 8
AF_TERMINAL_POLL_INTERVAL_SECONDS = 0.01
AF_TERMINAL_TIMEOUT_ENV_VAR = "CCCC_AF_TERMINAL_TIMEOUT_SECONDS"
AF_TERMINAL_TIMEOUT_SECONDS = 1800.0
CANCEL_EXIT_CODE = 130
FAILURE_EXIT_CODE = 1
SUCCESS_EXIT_CODE = 0
_AF_GLOBAL_CANCEL = threading.Event()


def request_af_global_cancel() -> None:
    _AF_GLOBAL_CANCEL.set()


def clear_af_global_cancel() -> None:
    _AF_GLOBAL_CANCEL.clear()


def af_global_cancel_is_set() -> bool:
    return _AF_GLOBAL_CANCEL.is_set()


def _default_terminal_timeout() -> float:
    raw = os.getenv(AF_TERMINAL_TIMEOUT_ENV_VAR)
    return AF_TERMINAL_TIMEOUT_SECONDS if raw is None else max(float(raw), 0.0)


@dataclass
class RawExecutionResult:
    """Result from a single runner execution."""

    exit_code: int
    stdout_lines: Optional[List[str]] = None
    stderr_lines: Optional[List[str]] = None
    cancelled: bool = False

    def __post_init__(self) -> None:
        if self.stdout_lines is None:
            self.stdout_lines = []
        if self.stderr_lines is None:
            self.stderr_lines = []


@dataclass(frozen=True)
class _AttemptContext:
    node_id: str
    run_id: str
    attempt_id: str
    task: Any
    group_id: str
    workflow_id: str
    assignment_policy: Any


@dataclass(frozen=True)
class _LeaseFinalization:
    lease: Optional[AgentLease]
    outcome: str
    failure_reason: str = ""


class CCCCActorRunner:
    """AF Runner that executes tasks through persistent actor sessions."""

    def __init__(
        self,
        agent_pool: Any = None,
        actor_gateway: Any = None,
        event_stream: Any = None,
        sidecar: Optional[Dict[str, Any]] = None,
        poll_interval: float = AF_TERMINAL_POLL_INTERVAL_SECONDS,
        timeout: Optional[float] = None,
    ) -> None:
        self.agent_pool = agent_pool
        self.actor_gateway = actor_gateway
        self.event_stream = event_stream
        self.sidecar = sidecar or {}
        self.poll_interval = max(float(poll_interval), 0.0)
        self.timeout = max(float(_default_terminal_timeout() if timeout is None else timeout), 0.0)
        self._last_attempt_id = ""
        self._last_outcome = "unknown"

    async def execute(
        self,
        node: dict,
        prepared: Any = None,
        paths: Any = None,
        on_output: Optional[Callable] = None,
        should_cancel: Optional[Callable] = None,
    ) -> RawExecutionResult:
        """Execute one task through a CCCC actor session."""
        del prepared, paths, on_output
        lease: Optional[AgentLease] = None
        outcome = "unknown"
        failure_reason = ""

        try:
            context = self._build_attempt_context(node)
            self._last_attempt_id = context.attempt_id
            request = self._build_acquire_request(context, node)
            lease = self._acquire_lease(request, context)
            await self._send_task(node, context, lease)
            if self._is_cancelled(should_cancel):
                outcome = "cancelled"
                return RawExecutionResult(
                    exit_code=CANCEL_EXIT_CODE,
                    cancelled=True,
                    stdout_lines=["Task cancelled"],
                )
            result = await self._poll_terminal(context, should_cancel)
            outcome = self._outcome_for(result)
            failure_reason = self._failure_reason_for(result, outcome)
            return result
        except Exception as exc:
            outcome = "failed"
            failure_reason = str(exc)
            return RawExecutionResult(
                exit_code=FAILURE_EXIT_CODE,
                stderr_lines=[failure_reason],
            )
        finally:
            self._last_outcome = outcome
            self._finalize_lease(_LeaseFinalization(lease, outcome, failure_reason))

    def _build_attempt_context(self, node: dict) -> _AttemptContext:
        node_id = node.get("id", "")
        run_id = str(uuid.uuid4())
        meta = self.sidecar.get(node_id)
        return _AttemptContext(
            node_id=node_id,
            run_id=run_id,
            attempt_id=self._resolve_attempt_id(meta, run_id, node_id),
            task=self._meta_value(meta, "task", None),
            group_id=self._meta_value(meta, "group_id", ""),
            workflow_id=self._meta_value(meta, "workflow_id", ""),
            assignment_policy=self._assignment_policy(meta),
        )

    def _build_acquire_request(
        self,
        context: _AttemptContext,
        node: dict,
    ) -> AgentAcquireRequest:
        return AgentAcquireRequest(
            run_id=context.run_id,
            workflow_id=context.workflow_id,
            node_id=context.node_id,
            task=context.task or node,
            attempt_id=context.attempt_id,
            group_id=context.group_id,
            project_root="",
            assignment_policy=context.assignment_policy,
        )

    def _acquire_lease(self, request: AgentAcquireRequest, context: _AttemptContext) -> AgentLease:
        if self.agent_pool and hasattr(self.agent_pool, "acquire"):
            return self.agent_pool.acquire(request)

        logger.debug("CCCCActorRunner dry-run without agent pool")
        return AgentLease(
            lease_id=str(uuid.uuid4()),
            agent_id="dry-run",
            actor_id="dry-run",
            model_runtime="claude",
            model_id="",
            model_key="",
            is_new_actor=False,
            assignment_reason="dry-run (no pool)",
            task_id=context.node_id,
            node_id=context.node_id,
            attempt_id=context.attempt_id,
        )

    async def _send_task(self, node: dict, context: _AttemptContext, lease: AgentLease) -> None:
        if not self.actor_gateway or not hasattr(self.actor_gateway, "send_task"):
            return

        await self.actor_gateway.send_task(
            group_id=context.group_id,
            actor_id=lease.actor_id,
            text=node.get("prompt", ""),
            metadata={
                "run_id": context.run_id,
                "node_id": context.node_id,
                "attempt_id": context.attempt_id,
                "lease_id": lease.lease_id,
            },
        )

    async def _poll_terminal(self, context: _AttemptContext, should_cancel: Optional[Callable] = None) -> RawExecutionResult:
        if not self.event_stream or not hasattr(self.event_stream, "poll_terminal"):
            return RawExecutionResult(
                exit_code=SUCCESS_EXIT_CODE,
                stdout_lines=[f"dry-run:{context.node_id}"],
            )

        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.timeout
        while True:
            if af_global_cancel_is_set():
                return self._cancelled_result("af global cancel")
            if self._is_cancelled(should_cancel):
                return self._cancelled_result()
            event = await self.event_stream.poll_terminal(context.attempt_id)
            if event is not None:
                return self._result_for_terminal_event(context, event)
            if loop.time() >= deadline:
                return self._timeout_result(context)
            await asyncio.sleep(self.poll_interval)

    def _finalize_lease(self, finalization: _LeaseFinalization) -> None:
        if not finalization.lease or not self.agent_pool:
            return
        if finalization.outcome == "failed":
            self._mark_failed(finalization)
            return
        if hasattr(self.agent_pool, "release"):
            self.agent_pool.release(finalization.lease, finalization.outcome)

    def _mark_failed(self, finalization: _LeaseFinalization) -> None:
        if hasattr(self.agent_pool, "mark_failed"):
            self.agent_pool.mark_failed(
                finalization.lease,
                finalization.failure_reason or "failed",
            )

    def _cancelled_result(self, stderr: str = "") -> RawExecutionResult:
        if stderr:
            return RawExecutionResult(exit_code=CANCEL_EXIT_CODE, cancelled=True, stderr_lines=[stderr])
        return RawExecutionResult(exit_code=CANCEL_EXIT_CODE, cancelled=True, stdout_lines=["Task cancelled"])

    def _failure_reason_for(self, result: RawExecutionResult, outcome: str) -> str:
        return result.stderr_lines[0] if outcome == "failed" and result.stderr_lines else ""

    def _failed_result(self, reason: str) -> RawExecutionResult:
        return RawExecutionResult(exit_code=FAILURE_EXIT_CODE, stderr_lines=[reason])

    def _result_for_terminal_event(self, context: _AttemptContext, event: Any) -> RawExecutionResult:
        kind = str(getattr(event, "kind", "") or "").strip() or "unknown"
        logger.info(
            "[af] worker terminal received attempt_id=%s kind=%s",
            context.attempt_id,
            kind,
        )
        if kind == "task_completed":
            return RawExecutionResult(exit_code=SUCCESS_EXIT_CODE, stdout_lines=["completed"])
        if kind in {"task_failed", "failed"}:
            return self._failed_result(f"worker terminal kind={kind}")
        if kind == "task_cancelled":
            return self._cancelled_result()
        return self._failed_result(f"worker terminal kind={kind}")

    def _timeout_result(self, context: _AttemptContext) -> RawExecutionResult:
        return self._failed_result(f"terminal timeout attempt_id={context.attempt_id}")

    def _assignment_policy(self, meta: Any) -> Any:
        policy = self._meta_value(meta, "assignment_policy", AssignmentPolicy(mode="auto"))
        if isinstance(policy, dict):
            return AssignmentPolicy(**policy)
        return policy

    def _outcome_for(self, result: RawExecutionResult) -> str:
        if result.cancelled:
            return "cancelled"
        if result.exit_code == SUCCESS_EXIT_CODE:
            return "completed"
        return "failed"

    def _is_cancelled(self, should_cancel: Optional[Callable]) -> bool:
        return bool(should_cancel and should_cancel())

    def _attempt_id(self, run_id: str, node_id: str) -> str:
        suffix = uuid.uuid4().hex[:ATTEMPT_SUFFIX_LENGTH]
        return f"{run_id}:{node_id}:{suffix}"

    def _resolve_attempt_id(self, meta: Any, run_id: str, node_id: str) -> str:
        attempt_id = str(self._meta_value(meta, "attempt_id", "") or "").strip()
        return attempt_id or self._attempt_id(run_id, node_id)

    def _meta_value(self, meta: Any, name: str, default: Any) -> Any:
        if meta is None:
            return default
        return meta.get(name, default) if isinstance(meta, dict) else getattr(meta, name, default)
