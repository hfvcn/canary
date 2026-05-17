"""Batch assignment processing helpers for WorkflowOrchestrator."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List

from ...contracts.v1.ralph_ipc import ReadyBatchSuggestion, RestartSuggestion, TaskRef
from ...kernel.workflow_state_types import WorkflowTaskStatus
from .agent_pool import TaskAssignment
from .assignment_constants import (
    FORBIDDEN_FLOWS_KEY,
    PROMPT_ISSUES_KEY,
    RECOMMENDED_TESTS_KEY,
    TASK_STATUS_PENDING,
)
from .contract_signature_advisory import (
    SignatureAdvisoryContext,
    warn_on_contract_signature_source_mismatches,
)
from .workflow import BatchEvaluationResult
from .workflow_id_resolution import (
    ensure_tasks_are_new,
    reject_if_tasks_already_exist,
    resolve_suggestion_workflow_id_for_resubmit,
    resolve_workflow_id_for_tasks,
)

logger = logging.getLogger("cccc.daemon.foreman.assignment_batches")

_BATCHABLE_TASK_STATUSES = {
    WorkflowTaskStatus.PLANNED,
    WorkflowTaskStatus.READY,
    WorkflowTaskStatus.DEFERRED,
}


def _reject_incomplete_tasks(task_refs: List[TaskRef]) -> None:
    """Reject tasks missing claimed_paths or verification before they enter the engine."""
    errors: List[str] = []
    for task in task_refs:
        if not task.claimed_paths:
            errors.append(f"task '{task.id}' has no claimed_paths")
        if task.verification is None and not task.verification_command:
            errors.append(f"task '{task.id}' has no verification defined")
    if errors:
        raise ValueError(
            f"Workflow submit rejected — {len(errors)} task(s) incomplete: "
            + "; ".join(errors)
        )


class AssignmentBatchMixin:
    """Handles ready-batch registration, evaluation, and reporting."""

    def process_batch_suggestion(
        self,
        suggestion: ReadyBatchSuggestion,
        *,
        auto_start_agents: bool = True,
        allowed_existing_task_ids: set[str] | None = None,
    ) -> BatchEvaluationResult:
        rejected = self._reject_existing_tasks_for_submit(
            suggestion,
            allowed_task_ids=allowed_existing_task_ids,
        )
        if rejected is not None:
            return rejected
        suggestion, resolution_rejection = resolve_suggestion_workflow_id_for_resubmit(
            suggestion,
            self._owner.engine.get_task,
        )
        if resolution_rejection is not None:
            return resolution_rejection
        workflow_id = suggestion.workflow_id
        batch_id = suggestion.suggestion_id
        self._owner._log(f"[orchestrator] Processing batch {batch_id} for workflow {workflow_id}")
        original_suggestion = suggestion
        suggestion, workflow_data, skipped_task_ids = self._register_batch_inputs(suggestion)
        if suggestion is None:
            workflow_data["batches"].append(batch_id)
            return self._reject_batch(
                batch_id,
                BatchEvaluationResult(
                    suggestion=original_suggestion,
                    approved_tasks=[],
                    rejected_tasks=list(original_suggestion.tasks),
                    skipped_task_ids=skipped_task_ids,
                    decision="rejected",
                    reason="all_tasks_completed_or_non_batchable",
                ),
            )

        deferred_result = self.defer_batch_for_single_writer(suggestion)
        if deferred_result is not None:
            deferred_result.skipped_task_ids = list(skipped_task_ids)
            workflow_data["batches"].append(batch_id)
            return deferred_result

        pressure_result = self.defer_batch_for_cross_workflow_pressure(suggestion)
        if pressure_result is not None:
            pressure_result.skipped_task_ids = list(skipped_task_ids)
            workflow_data["batches"].append(batch_id)
            return pressure_result

        result = self._evaluate_batch(suggestion)
        workflow_data["batches"].append(batch_id)
        result = self._apply_authorized_fallback(suggestion, result)
        result.skipped_task_ids = list(skipped_task_ids)
        if result.decision == "rejected":
            return self._reject_batch(batch_id, result)

        self._record_assignment_details(workflow_id, batch_id, workflow_data, result)
        self.sync_batch_to_control_plane(result)
        self._report_batch_started(batch_id, workflow_id, result)
        if auto_start_agents and result.approved_tasks:
            self._warn_on_contract_signature_sources(result)
            self._owner._start_assigned_agents(result)
        return result

    def _reject_existing_tasks_for_submit(
        self,
        suggestion: ReadyBatchSuggestion,
        *,
        allowed_task_ids: set[str] | None = None,
    ) -> BatchEvaluationResult | None:
        return reject_if_tasks_already_exist(
            suggestion,
            self._owner.engine.get_task,
            allowed_task_ids=allowed_task_ids,
        )

    def _register_batch_inputs(
        self,
        suggestion: ReadyBatchSuggestion,
    ) -> tuple[ReadyBatchSuggestion | None, Dict[str, Any], List[str]]:
        workflow_id = suggestion.workflow_id
        batch_id = suggestion.suggestion_id
        _reject_incomplete_tasks(suggestion.tasks)
        for task in suggestion.tasks:
            self._owner.engine.register_task(task, workflow_id)
            self._owner._track_task_ref(workflow_id, task)
        states = {task.id: self._owner.engine.get_task(task.id) for task in suggestion.tasks}
        skipped_task_ids = self._non_batchable_task_ids(suggestion, states)
        if skipped_task_ids:
            suggestion = self._trim_non_batchable_tasks(suggestion, skipped_task_ids)
            logger.info("batch %s: skipping non-batchable tasks %s", batch_id, skipped_task_ids)
        states_to_register = [self._owner.engine.get_task(task.id) for task in suggestion.tasks]
        if suggestion.tasks and not all(state and state.batch_id == batch_id for state in states_to_register):
            self._owner.engine.register_batch(batch_id, [t.id for t in suggestion.tasks])
        workflow_data = self._owner._ensure_active_workflow(workflow_id, started_at=suggestion.created_at)
        self._record_prompt_projection_metadata(suggestion, workflow_data)
        if not suggestion.tasks:
            return None, workflow_data, skipped_task_ids
        return suggestion, workflow_data, skipped_task_ids

    @staticmethod
    def _non_batchable_task_ids(
        suggestion: ReadyBatchSuggestion,
        states: Dict[str, Any],
    ) -> List[str]:
        return [
            task.id
            for task in suggestion.tasks
            if states.get(task.id) and states[task.id].status not in _BATCHABLE_TASK_STATUSES
        ]

    @staticmethod
    def _trim_non_batchable_tasks(
        suggestion: ReadyBatchSuggestion,
        skipped_task_ids: List[str],
    ) -> ReadyBatchSuggestion:
        skipped = set(skipped_task_ids)
        batchable_tasks = [task for task in suggestion.tasks if task.id not in skipped]
        return suggestion.model_copy(update={"tasks": batchable_tasks})

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

    def _warn_on_contract_signature_sources(self, result: BatchEvaluationResult) -> None:
        context = SignatureAdvisoryContext(
            project_root=self._owner.project_root,
            all_tasks=self._known_signature_check_tasks(result),
            consumer_tasks=list(result.approved_tasks),
            log_fn=self._owner._log,
        )
        warn_on_contract_signature_source_mismatches(context)

    def _known_signature_check_tasks(self, result: BatchEvaluationResult) -> List[TaskRef]:
        tasks = {task.id: task for task in result.suggestion.tasks}
        workflow_id = result.suggestion.workflow_id
        for task in self._tracked_workflow_task_refs(workflow_id):
            tasks[task.id] = task
        for state in self._owner._list_engine_tasks(workflow_id):
            if state.task is not None:
                tasks[state.task.id] = state.task
        return list(tasks.values())

    def _tracked_workflow_task_refs(self, workflow_id: str) -> List[TaskRef]:
        workflow = self._owner._active_workflows.get(workflow_id, {})
        task_refs: List[TaskRef] = []
        for tracked in workflow.get("tasks", {}).values():
            task_ref = tracked.get("task_ref")
            if isinstance(task_ref, TaskRef):
                task_refs.append(task_ref)
        return task_refs

    def register_and_suggest_inner(
        self,
        task_dicts: List[Dict[str, Any]],
        workflow_id: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        task_refs = [TaskRef.model_validate(task) for task in task_dicts]
        _reject_incomplete_tasks(task_refs)
        ensure_tasks_are_new(
            task_refs,
            self._owner.engine.get_task,
        )
        workflow_id = resolve_workflow_id_for_tasks(
            task_refs, workflow_id, self._owner.engine.get_task,
        )
        self._owner._ensure_active_workflow(
            workflow_id,
            auto_process=kwargs.get("auto_process"),
            auto_start_agents=kwargs.get("auto_start_agents"),
            auto_dispatch=kwargs.get("auto_dispatch"),
            stall_auto_reassign=kwargs.get("stall_auto_reassign"),
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
            self._submit_ready_suggestion(
                suggestion,
                kwargs,
                allowed_existing_task_ids={task.id for task in task_refs},
            )
        return {"registered": len(task_refs), "submitted": len(ready_task_ids), "ready_task_ids": ready_task_ids}

    def _submit_ready_suggestion(
        self,
        suggestion: ReadyBatchSuggestion,
        kwargs: Dict[str, Any],
        *,
        allowed_existing_task_ids: set[str] | None = None,
    ) -> None:
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
        self.process_batch_suggestion(
            suggestion,
            auto_start_agents=bool(kwargs.get("auto_start_agents", True)),
            allowed_existing_task_ids=allowed_existing_task_ids,
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
            stall_auto_reassign=kwargs.get("stall_auto_reassign"),
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
