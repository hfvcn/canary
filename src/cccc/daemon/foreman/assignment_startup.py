"""Assigned worker startup helpers for WorkflowOrchestrator."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ...contracts.v1 import DaemonRequest
from ...contracts.v1.ralph_ipc import TaskRef
from ...kernel.actors import find_actor
from ...kernel.group import load_group
from ...kernel.workflow_state import WorkflowTaskStatus
from ..ops.agent_ops import get_agent
from .agent_pool import TaskAssignment
from .assignment_constants import (
    FORBIDDEN_FLOWS_KEY,
    ORCHESTRATOR_SERVICE_ACTOR,
    PROMPT_ISSUES_KEY,
    RECOMMENDED_TESTS_KEY,
    TASK_STATUS_PENDING,
    TASK_STATUS_RUNNING,
)
from .workflow import BatchEvaluationResult


logger = logging.getLogger("cccc.daemon.foreman.assignment_controller")


@dataclass
class AssignmentStartContext:
    task: TaskRef
    agent_id: str
    tracked_task: Optional[Dict[str, Any]]


@dataclass(frozen=True)
class AssignmentPromptProjection:
    issues: List[Any]
    recommended_tests: List[str]
    forbidden_flows: List[Any]


class AssignmentStartupMixin:
    """Starts assigned agents and delivers task prompts."""

    def start_assigned_agents(self, result: BatchEvaluationResult) -> None:
        """Start agents for approved task assignments."""
        for assignment in result.assignments:
            context = self._prepare_start_context(assignment)
            if context is None:
                continue
            if not self._start_actor_for_assignment(assignment):
                self._rollback_tracked_task(context)
                continue
            task_prompt = self._build_assignment_prompt(assignment, context)
            if not self._send_assignment_prompt(context, task_prompt):
                self._rollback_tracked_task(context)
                continue
            self._mark_worker_started(context)

    def _prepare_start_context(self, assignment: TaskAssignment) -> Optional[AssignmentStartContext]:
        if not assignment.agent_id:
            return None
        task = assignment.task
        agent_id = assignment.agent_id
        self._owner._log(f"[orchestrator] Starting agent {agent_id} for task {task.id}")
        self._owner._task_to_agent[task.id] = agent_id
        model_id = assignment.model_id or "claude-sonnet-4-20250514"
        model_key = model_id if "-" in model_id else f"claude-{model_id}"
        self._owner._task_to_model[task.id] = model_key
        return AssignmentStartContext(task=task, agent_id=agent_id, tracked_task=self._mark_tracked_assigned(task.id))

    def _mark_tracked_assigned(self, task_id: str) -> Optional[Dict[str, Any]]:
        for workflow_data in self._owner._active_workflows.values():
            tracked_task = workflow_data.get("tasks", {}).get(task_id)
            if tracked_task:
                tracked_task["status"] = "assigned"
                return tracked_task
        return None

    def _start_actor_for_assignment(self, assignment: TaskAssignment) -> bool:
        started = self._owner._add_actor_via_daemon(assignment)
        if started or not self._owner._start_actor_fn:
            return started
        return self._legacy_start_actor(assignment)

    def _legacy_start_actor(self, assignment: TaskAssignment) -> bool:
        try:
            config = {
                "task_id": assignment.task.id,
                "task_title": assignment.task.title,
                "task_type": assignment.task.type,
                "model": assignment.model_id or "claude-sonnet-4-20250514",
            }
            resp = self._owner._start_actor_fn(self._owner.group_id, assignment.agent_id, config)
            if resp.ok:
                return True
            self._owner._log(f"[orchestrator] Failed to start agent {assignment.agent_id}: {resp.error}")
            return False
        except Exception as exc:
            self._owner._log(f"[orchestrator] Error starting agent {assignment.agent_id}: {exc}")
            return False

    def _build_assignment_prompt(
        self,
        assignment: TaskAssignment,
        context: AssignmentStartContext,
    ) -> str:
        worker_prompt = self.load_worker_prompt(context.agent_id)
        projection = self._build_prompt_projection(context.tracked_task)
        return self._owner._build_task_prompt(
            context.task,
            worker_prompt=worker_prompt,
            runtime=assignment.model_runtime,
            issues=projection.issues,
            recommended_tests=projection.recommended_tests,
            forbidden_flows=projection.forbidden_flows,
        )

    def _build_prompt_projection(
        self,
        tracked_task: Optional[Dict[str, Any]],
    ) -> AssignmentPromptProjection:
        if tracked_task is None:
            return AssignmentPromptProjection([], [], [])
        return AssignmentPromptProjection(
            issues=self._required_list(tracked_task, PROMPT_ISSUES_KEY),
            recommended_tests=self._required_string_list(
                tracked_task,
                RECOMMENDED_TESTS_KEY,
            ),
            forbidden_flows=self._forbidden_flows_for(tracked_task),
        )

    def _forbidden_flows_for(self, tracked_task: Dict[str, Any]) -> List[Any]:
        if FORBIDDEN_FLOWS_KEY in tracked_task:
            return self._required_list(tracked_task, FORBIDDEN_FLOWS_KEY)
        workflow_id = str(tracked_task.get("workflow_id") or "").strip()
        if not workflow_id:
            return []
        workflow = self._owner._active_workflows.get(workflow_id)
        if workflow is None:
            raise KeyError(f"tracked task references unknown workflow '{workflow_id}'")
        return self._required_list(workflow, FORBIDDEN_FLOWS_KEY)

    @staticmethod
    def _required_list(source: Dict[str, Any], key: str) -> List[Any]:
        if key not in source:
            return []
        value = source[key]
        if not isinstance(value, list):
            raise TypeError(f"{key} must be a list")
        return list(value)

    @staticmethod
    def _required_string_list(source: Dict[str, Any], key: str) -> List[str]:
        values = AssignmentStartupMixin._required_list(source, key)
        if not all(isinstance(item, str) for item in values):
            raise TypeError(f"{key} must contain only strings")
        return values

    def _send_assignment_prompt(self, context: AssignmentStartContext, task_prompt: str) -> bool:
        if self._owner._send_message_fn:
            return self._send_with_message_fn(context, task_prompt)
        if self._owner._daemon_request_fn:
            return self._send_with_daemon(context, task_prompt)
        warning = (
            f"Cannot send task to {context.agent_id}: both send_message_fn and "
            "daemon_request_fn are unavailable"
        )
        logger.warning(warning)
        self._owner._log(f"[orchestrator] {warning}")
        return False

    def _send_with_message_fn(self, context: AssignmentStartContext, task_prompt: str) -> bool:
        try:
            resp = self._owner._send_message_fn(self._owner.group_id, context.agent_id, task_prompt)
            send_ok = bool(resp is None or resp.ok)
            if not send_ok:
                err_msg = resp.error.message if resp and resp.error else "unknown"
                self._owner._log(f"[orchestrator] Failed to send task to {context.agent_id}: {err_msg}")
            return send_ok
        except Exception as exc:
            self._owner._log(f"[orchestrator] Error sending task to {context.agent_id}: {exc}")
            return False

    def _send_with_daemon(self, context: AssignmentStartContext, task_prompt: str) -> bool:
        try:
            req = DaemonRequest(
                op="send",
                args={
                    "group_id": self._owner.group_id,
                    "by": ORCHESTRATOR_SERVICE_ACTOR,
                    "to": [context.agent_id],
                    "text": task_prompt,
                },
            )
            resp, _ = self._owner._daemon_request_fn(req)
            if resp.ok:
                return True
            err_msg = resp.error.message if resp.error else "unknown"
            self._owner._log(f"[orchestrator] Failed to send task to {context.agent_id}: {err_msg}")
            return False
        except Exception as exc:
            self._owner._log(f"[orchestrator] Error sending task to {context.agent_id}: {exc}")
            return False

    @staticmethod
    def _rollback_tracked_task(context: AssignmentStartContext) -> None:
        if context.tracked_task is not None:
            context.tracked_task["status"] = TASK_STATUS_PENDING

    def _mark_worker_started(self, context: AssignmentStartContext) -> None:
        auto_started = False
        try:
            task_state = self._owner.engine.get_task(context.task.id)
            if task_state and task_state.status == WorkflowTaskStatus.ASSIGNED:
                self._owner.engine.report_worker_started(context.task.id, context.agent_id, hook_ctx={})
                auto_started = True
        except Exception:
            logger.debug("Auto-start after assignment failed for %s", context.task.id, exc_info=True)
        if context.tracked_task is not None:
            context.tracked_task["status"] = TASK_STATUS_RUNNING if auto_started else "assigned"

    def load_worker_prompt(self, agent_id: str) -> str:
        """Load the persisted worker prompt for an assigned agent."""
        if not agent_id:
            return ""
        try:
            agent = get_agent(agent_id, self._owner.foreman.agents_dir)
        except Exception as exc:
            self._owner._log(f"[orchestrator] Error loading agent prompt for {agent_id}: {exc}")
            return ""
        return str((agent.prompt if agent else "") or "").strip()

    def add_actor_via_daemon(self, assignment: TaskAssignment) -> bool:
        """Register a foreman agent as a real group actor via daemon actor_add."""
        if not self._owner._daemon_request_fn:
            return False

        group = load_group(self._owner.group_id)
        if group is None:
            self._owner._log(
                f"[orchestrator] Cannot register agent {assignment.agent_id}: "
                f"group {self._owner.group_id} not found"
            )
            return False
        if find_actor(group, assignment.agent_id) is not None:
            self._owner._log(f"[orchestrator] Agent {assignment.agent_id} already registered as group actor")
            return True
        return self._dispatch_actor_add(assignment)

    def _dispatch_actor_add(self, assignment: TaskAssignment) -> bool:
        agent_id = assignment.agent_id
        runtime = assignment.model_runtime or "claude"
        try:
            req = self._build_actor_add_request(assignment, runtime)
            resp, _ = self._owner._daemon_request_fn(req)
            if resp.ok:
                self._owner._log(f"[orchestrator] Registered agent {agent_id} as group actor (runtime={runtime})")
                return True
            err_msg = resp.error.message if resp.error else "unknown"
            self._owner._log(f"[orchestrator] Failed to register agent {agent_id}: {err_msg}")
            return False
        except Exception as exc:
            self._owner._log(f"[orchestrator] Error registering agent {agent_id} as actor: {exc}")
            return False

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
