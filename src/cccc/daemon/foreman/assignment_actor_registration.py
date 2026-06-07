"""Actor registration helpers for workflow assignments."""

from __future__ import annotations

from dataclasses import dataclass

from ...contracts.v1 import DaemonRequest
from .agent_pool import TaskAssignment
from .assignment_constants import ORCHESTRATOR_SERVICE_ACTOR


@dataclass(frozen=True)
class ActorAddResult:
    ok: bool
    running: bool | None = None
    start_error: str | None = None


class AssignmentActorRegistrationMixin:
    """Registers pool agents as group actors through daemon requests."""

    def add_actor_via_daemon(self, assignment: TaskAssignment) -> ActorAddResult:
        """Register a foreman agent as a real group actor via daemon actor_add."""
        from ...kernel.actors import find_actor
        from ...kernel.group import load_group

        if not self._owner._daemon_request_fn:
            return ActorAddResult(ok=False)
        group = load_group(self._owner.group_id)
        if group is None:
            self._owner._log(
                f"[orchestrator] Cannot register agent {assignment.agent_id}: "
                f"group {self._owner.group_id} not found"
            )
            return ActorAddResult(ok=False)
        if find_actor(group, assignment.agent_id) is not None:
            self._owner._log(f"[orchestrator] Agent {assignment.agent_id} already registered as group actor")
            return ActorAddResult(ok=True)
        return self._dispatch_actor_add(assignment)

    def _dispatch_actor_add(self, assignment: TaskAssignment) -> ActorAddResult:
        agent_id = assignment.agent_id
        runtime = assignment.model_runtime or "codex"
        try:
            req = self._build_actor_add_request(assignment, runtime)
            resp, _ = self._owner._daemon_request_fn(req)
        except Exception as exc:
            self._owner._log(f"[orchestrator] Error registering agent {agent_id} as actor: {exc}")
            return ActorAddResult(ok=False, start_error=str(exc))
        if resp.ok:
            result = resp.result if isinstance(resp.result, dict) else {}
            suffix = f"; start_error={result.get('start_error') or 'unknown'}" if result.get("running") is False else ""
            self._owner._log(
                f"[orchestrator] Registered agent {agent_id} as group actor "
                f"(runtime={runtime}){suffix}"
            )
            return ActorAddResult(
                ok=True,
                running=result.get("running"),
                start_error=result.get("start_error"),
            )
        err_msg = resp.error.message if resp.error else "unknown"
        self._owner._log(f"[orchestrator] Failed to register agent {agent_id}: {err_msg}")
        return ActorAddResult(ok=False, start_error=str(resp.error))

    def _build_actor_add_request(self, assignment: TaskAssignment, runtime: str) -> DaemonRequest:
        agent_id = assignment.agent_id
        return DaemonRequest(
            op="actor_add",
            args={
                "group_id": self._owner.group_id,
                "actor_id": agent_id,
                "title": assignment.agent_name or agent_id,
                "runner": "pty",
                "runtime": runtime,
                "worker_prompt": self.load_worker_prompt(agent_id),
                "capability_autoload": ["pack:group-runtime"],
                "by": ORCHESTRATOR_SERVICE_ACTOR,
            },
        )
