"""Batch assignment processing helpers for WorkflowOrchestrator."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Dict, List

from ...contracts.v1.ralph_ipc import ReadyBatchSuggestion, RestartSuggestion, TaskRef
from .agent_pool import TaskAssignment
from .assignment_constants import (
    FORBIDDEN_FLOWS_KEY,
    PROMPT_ISSUES_KEY,
    RECOMMENDED_TESTS_KEY,
    TASK_STATUS_PENDING,
)
from .workflow import BatchEvaluationResult


class AssignmentBatchMixin:
    """Handles ready-batch registration, evaluation, and reporting."""

    def process_batch_suggestion(
        self,
        suggestion: ReadyBatchSuggestion,
        *,
        auto_start_agents: bool = True,
    ) -> BatchEvaluationResult:
        workflow_id = suggestion.workflow_id
        batch_id = suggestion.suggestion_id
        self._owner._log(f"[orchestrator] Processing batch {batch_id} for workflow {workflow_id}")
        workflow_data = self._register_batch_inputs(suggestion)

        deferred_result = self.defer_batch_for_single_writer(suggestion)
        if deferred_result is not None:
            workflow_data["batches"].append(batch_id)
            return deferred_result

        pressure_result = self.defer_batch_for_cross_workflow_pressure(suggestion)
        if pressure_result is not None:
            workflow_data["batches"].append(batch_id)
            return pressure_result

        result = self._evaluate_batch(suggestion)
        workflow_data["batches"].append(batch_id)
        result = self._apply_authorized_fallback(suggestion, result)
        if result.decision == "rejected":
            return self._reject_batch(batch_id, result)

        self._record_assignment_details(workflow_id, batch_id, workflow_data, result)
        self.sync_batch_to_control_plane(result)
        self._report_batch_started(batch_id, workflow_id, result)
        if auto_start_agents and result.approved_tasks:
            self._owner._start_assigned_agents(result)
        return result

    def _register_batch_inputs(self, suggestion: ReadyBatchSuggestion) -> Dict[str, Any]:
        workflow_id = suggestion.workflow_id
        batch_id = suggestion.suggestion_id
        for task in suggestion.tasks:
            self._owner.engine.register_task(task, workflow_id)
            self._owner._track_task_ref(workflow_id, task)
        states = [self._owner.engine.get_task(t.id) for t in suggestion.tasks]
        if not all(state and state.batch_id == batch_id for state in states):
            self._owner.engine.register_batch(batch_id, [t.id for t in suggestion.tasks])
        workflow_data = self._owner._ensure_active_workflow(workflow_id, started_at=suggestion.created_at)
        self._record_prompt_projection_metadata(suggestion, workflow_data)
        return workflow_data

    def _record_prompt_projection_metadata(
        self,
        suggestion: ReadyBatchSuggestion,
        workflow_data: Dict[str, Any],
    ) -> None:
        if suggestion.forbidden_flows:
            workflow_data[FORBIDDEN_FLOWS_KEY] = list(suggestion.forbidden_flows)
        self._record_task_prompt_metadata(
            workflow_data,
            PROMPT_ISSUES_KEY,
            suggestion.prompt_issues,
        )
        self._record_task_prompt_metadata(
            workflow_data,
            RECOMMENDED_TESTS_KEY,
            suggestion.recommended_tests,
        )

    @staticmethod
    def _record_task_prompt_metadata(
        workflow_data: Dict[str, Any],
        key: str,
        values_by_task: Dict[str, List[Any]],
    ) -> None:
        tasks = workflow_data.get("tasks", {})
        for task_id, values in values_by_task.items():
            tracked = tasks.get(task_id)
            if tracked is None:
                raise ValueError(f"{key} references unknown task '{task_id}'")
            tracked[key] = list(values)

    def _evaluate_batch(self, suggestion: ReadyBatchSuggestion) -> BatchEvaluationResult:
        if suggestion.assignments:
            return self._build_explicit_assignment_result(suggestion)
        self.sync_busy_agents_to_pool()
        return self._owner.foreman.process_batch_suggestion(
            suggestion,
            auto_approve=True,
            notify_feishu=False,
        )

    def _build_explicit_assignment_result(self, suggestion: ReadyBatchSuggestion) -> BatchEvaluationResult:
        self._owner._log(
            f"[orchestrator] Using Foreman explicit assignments for batch {suggestion.suggestion_id}"
        )
        explicit_assignments = []
        for task in suggestion.tasks:
            actor_id = suggestion.assignments.get(task.id, "")
            if not actor_id:
                continue
            explicit_assignments.append(
                TaskAssignment(
                    task=task,
                    agent_id=actor_id,
                    agent_name=actor_id,
                    assignment_reason="foreman_explicit",
                )
            )
        return BatchEvaluationResult(
            suggestion=suggestion,
            decision="approved",
            reason=f"Foreman explicit assignment for {len(explicit_assignments)} tasks",
            assignments=explicit_assignments,
            approved_tasks=list(suggestion.tasks),
            rejected_tasks=[],
        )

    def _apply_authorized_fallback(
        self,
        suggestion: ReadyBatchSuggestion,
        result: BatchEvaluationResult,
    ) -> BatchEvaluationResult:
        if suggestion.assignments or result.decision != "rejected":
            return result
        if not getattr(suggestion, "fallback_allowed", False):
            return result
        self._owner._log("[orchestrator] Fallback to group actors explicitly authorized")
        fallback_result = self._owner._fallback_to_group_actors(suggestion)
        return fallback_result if fallback_result is not None else result

    def _reject_batch(self, batch_id: str, result: BatchEvaluationResult) -> BatchEvaluationResult:
        self._owner._log(f"[orchestrator] Batch {batch_id} rejected: {result.reason}")
        rejected_ids = [task.id for task in result.rejected_tasks]
        self._owner._notify_foreman_task_update(
            task_id=batch_id,
            new_status="batch_rejected",
            summary=f"Batch rejected: {result.reason}. Tasks needing assignment: {rejected_ids}",
        )
        return result

    def _record_assignment_details(
        self,
        workflow_id: str,
        batch_id: str,
        workflow_data: Dict[str, Any],
        result: BatchEvaluationResult,
    ) -> None:
        self._track_result_assignments(workflow_id, result)
        approved_assignments = self._build_approved_assignments(workflow_data, result)
        if approved_assignments:
            self._owner.engine.approve_batch(batch_id, approved_assignments)

    def _track_result_assignments(self, workflow_id: str, result: BatchEvaluationResult) -> None:
        for assignment in result.assignments:
            if not assignment.agent_id:
                continue
            tracked = self._owner._track_task_ref(
                workflow_id,
                assignment.task,
                status=TASK_STATUS_PENDING,
            )
            tracked.update(self._tracked_assignment_data(assignment))
            tracked.pop("assignment_attempt_id", None)

    @staticmethod
    def _tracked_assignment_data(assignment: TaskAssignment) -> Dict[str, Any]:
        return {
            "agent_id": assignment.agent_id,
            "agent_name": assignment.agent_name or assignment.agent_id,
            "is_new_agent": assignment.is_new_agent,
            "model_runtime": assignment.model_runtime or "",
            "model_id": assignment.model_id or "",
        }

    def _build_approved_assignments(
        self,
        workflow_data: Dict[str, Any],
        result: BatchEvaluationResult,
    ) -> List[Dict[str, Any]]:
        approved_ids = {task.id for task in result.approved_tasks}
        approved_assignments = []
        for assignment in result.assignments:
            if not assignment.agent_id or assignment.task.id not in approved_ids:
                continue
            attempt_id = str(uuid.uuid4())[:12]
            approved_assignments.append(self._approved_assignment(assignment, attempt_id))
            tracked = workflow_data["tasks"].get(assignment.task.id)
            if tracked is not None:
                tracked["assignment_attempt_id"] = attempt_id
        return approved_assignments

    @staticmethod
    def _approved_assignment(assignment: TaskAssignment, attempt_id: str) -> Dict[str, Any]:
        return {
            "task_id": assignment.task.id,
            "agent_id": assignment.agent_id,
            "attempt_id": attempt_id,
            "claimed_paths": list(assignment.task.claimed_paths or []),
        }

    def _report_batch_started(
        self,
        batch_id: str,
        workflow_id: str,
        result: BatchEvaluationResult,
    ) -> None:
        task_infos = [
            {"id": a.task.id, "title": a.task.title, "agent_name": a.agent_name or "pending"}
            for a in result.assignments
        ]
        self._owner.reporter.on_batch_started(batch_id, task_infos, workflow_id=workflow_id)

    def register_and_suggest_inner(
        self,
        task_dicts: List[Dict[str, Any]],
        workflow_id: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        task_refs = [TaskRef.model_validate(task) for task in task_dicts]
        self._owner._ensure_active_workflow(
            workflow_id,
            auto_process=kwargs.get("auto_process"),
            auto_start_agents=kwargs.get("auto_start_agents"),
            auto_dispatch=kwargs.get("auto_dispatch"),
            assignment_map=kwargs.get("assignment_map"),
        )
        self._store_workflow_meta(workflow_id, kwargs)
        for task in task_refs:
            self._owner.engine.register_task(task, workflow_id)
            self._owner._track_task_ref(workflow_id, task)

        suggestion = self._owner.ralph.suggest_ready_batch(
            task_refs,
            running_write_sets=self._owner._get_running_write_sets(),
            workflow_id=workflow_id,
        )
        ready_task_ids = [task.id for task in suggestion.tasks] if suggestion else []
        if suggestion and suggestion.tasks:
            self._submit_ready_suggestion(suggestion, kwargs)
        return {"registered": len(task_refs), "submitted": len(ready_task_ids), "ready_task_ids": ready_task_ids}

    def _submit_ready_suggestion(self, suggestion: ReadyBatchSuggestion, kwargs: Dict[str, Any]) -> None:
        if kwargs.get("suggestion_id"):
            suggestion.suggestion_id = str(kwargs["suggestion_id"])
        if kwargs.get("rationale"):
            suggestion.rationale = str(kwargs["rationale"])
        if kwargs.get("estimated_parallelism"):
            suggestion.estimated_parallelism = int(kwargs["estimated_parallelism"])
        if kwargs.get("assignments"):
            suggestion.assignments = dict(kwargs["assignments"])
        elif kwargs.get("assignment_map"):
            suggestion.assignments = self._assignments_for_tasks(
                suggestion.tasks,
                dict(kwargs["assignment_map"]),
            )
        if kwargs.get(PROMPT_ISSUES_KEY):
            suggestion.prompt_issues = dict(kwargs[PROMPT_ISSUES_KEY])
        if kwargs.get(RECOMMENDED_TESTS_KEY):
            suggestion.recommended_tests = dict(kwargs[RECOMMENDED_TESTS_KEY])
        if kwargs.get(FORBIDDEN_FLOWS_KEY):
            suggestion.forbidden_flows = list(kwargs[FORBIDDEN_FLOWS_KEY])
        suggestion.fallback_allowed = bool(kwargs.get("fallback_allowed", False))
        self._owner.process_batch_suggestion(
            suggestion,
            auto_start_agents=bool(kwargs.get("auto_start_agents", True)),
        )

    def _store_workflow_meta(self, workflow_id: str, kwargs: Dict[str, Any]) -> None:
        raw_plan_path = str(kwargs.get("plan_path") or "").strip()
        plan_path = str(Path(raw_plan_path).resolve()) if raw_plan_path else ""
        plan_digest = self._owner._compute_structural_digest(Path(plan_path)) if plan_path else ""
        self._owner.engine.set_workflow_meta(
            workflow_id,
            plan_path=plan_path,
            plan_digest=plan_digest,
            auto_dispatch=kwargs.get("auto_dispatch"),
            assignment_map=kwargs.get("assignment_map"),
        )

    @staticmethod
    def _assignments_for_tasks(
        tasks: List[TaskRef],
        assignment_map: Dict[str, str],
    ) -> Dict[str, str]:
        normalized = {
            str(task_id or "").strip(): str(agent_id or "").strip()
            for task_id, agent_id in assignment_map.items()
            if str(task_id or "").strip() and str(agent_id or "").strip()
        }
        return {
            task.id: normalized[task.id]
            for task in tasks
            if task.id in normalized
        }

    def handle_restart(
        self,
        restart_suggestion: RestartSuggestion,
        *,
        auto_start_agents: bool = True,
    ) -> BatchEvaluationResult:
        rationale = restart_suggestion.reason.strip()
        rationale = f"Restart suggested: {rationale}" if rationale else "Restart suggested by Ralph"
        suggestion = ReadyBatchSuggestion(
            suggestion_id=restart_suggestion.suggestion_id,
            workflow_id=restart_suggestion.workflow_id,
            tasks=[restart_suggestion.task],
            rationale=rationale,
            estimated_parallelism=1,
        )
        return self._owner.process_batch_suggestion(suggestion, auto_start_agents=auto_start_agents)
