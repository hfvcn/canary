"""Fallback assignment helpers for WorkflowOrchestrator."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ...contracts.v1.ralph_ipc import ReadyBatchSuggestion, TaskRef
from ...kernel.actors import get_effective_role, list_actors
from ...kernel.group import load_group
from ...kernel.workflow_state import WorkflowTaskStatus
from ...kernel.workflow_state_types import KIND_BATCH_FALLBACK_APPROVED
from ...util.conv import coerce_bool
from .admission import (
    build_fallback_result as _build_fallback_result,
    build_group_actor_assignment as _build_group_actor_assignment,
)
from .agent_pool import TaskAssignment
from .assignment_constants import ORCHESTRATOR_SERVICE_ACTOR
from .workflow import BatchEvaluationResult


class AssignmentFallbackMixin:
    """Handles explicit group-peer fallback after pool rejection."""

    def fallback_to_group_actors(
        self,
        suggestion: ReadyBatchSuggestion,
    ) -> Optional[BatchEvaluationResult]:
        if not getattr(suggestion, "fallback_allowed", False):
            return None
        peer_actors = self._owner._load_enabled_peer_actors()
        if not peer_actors:
            return None

        self._owner._log(
            f"[orchestrator] Pool rejected batch {suggestion.suggestion_id}; "
            f"falling back to {len(peer_actors)} group peer actors"
        )
        result = _build_fallback_result(suggestion, peer_actors)
        self.record_fallback_decision(suggestion, peer_actors, result)
        return result

    def record_fallback_decision(
        self,
        suggestion: ReadyBatchSuggestion,
        peer_actors: List[Dict[str, Any]],
        result: BatchEvaluationResult,
    ) -> None:
        from cccc.kernel.ledger import append_event

        scope_key = str(self._owner.group.doc.get("active_scope_key") or "").strip()
        append_event(
            self._owner.group.ledger_path,
            kind=KIND_BATCH_FALLBACK_APPROVED,
            group_id=self._owner.group.group_id,
            scope_key=scope_key,
            by=ORCHESTRATOR_SERVICE_ACTOR,
            data={
                "workflow_id": suggestion.workflow_id,
                "suggestion_id": suggestion.suggestion_id,
                "decision": result.decision,
                "reason": result.reason,
                "fallback_allowed": True,
                "task_ids": [task.id for task in suggestion.tasks],
                "peer_actor_ids": [str(actor.get("id") or "") for actor in peer_actors],
            },
        )

    @staticmethod
    def build_group_actor_assignment(task: TaskRef, actor: Dict[str, Any]) -> TaskAssignment:
        return _build_group_actor_assignment(task, actor)

    def sync_busy_agents_to_pool(self) -> None:
        """Sync engine busy agent IDs into pool's _active_assignments."""
        pool = getattr(self._owner.foreman, "pool_manager", None)
        if pool is None:
            return
        for task_id, agent_id in self._engine_busy_agents().items():
            if agent_id and agent_id not in pool._active_assignments:
                pool._active_assignments[agent_id] = task_id

    def _engine_busy_agents(self) -> Dict[str, str]:
        engine_busy: dict[str, str] = {}
        for task_state in self._owner._list_engine_tasks():
            if task_state.status not in (WorkflowTaskStatus.RUNNING, WorkflowTaskStatus.ASSIGNED):
                continue
            agent_id = task_state.agent_id or self._owner._task_to_agent.get(task_state.task.id, "")
            if agent_id:
                engine_busy[task_state.task.id] = agent_id
        return engine_busy

    def load_enabled_peer_actors(self) -> List[Dict[str, Any]]:
        group = load_group(self._owner.group_id) or self._owner.group
        peer_actors: List[Dict[str, Any]] = []
        for actor in list_actors(group):
            actor_id = str(actor.get("id") or "").strip()
            if not actor_id:
                continue
            if not coerce_bool(actor.get("enabled"), default=True):
                continue
            if get_effective_role(group, actor_id) != "peer":
                continue
            peer_actors.append(actor)
        return peer_actors
