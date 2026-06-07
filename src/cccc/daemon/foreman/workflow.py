"""Foreman workflow implementation.

This module implements the core Foreman workflow:
1. receive_ready_batch(): Receive Ralph's batch suggestion
2. evaluate_agent_pool(): Evaluate existing agents for tasks
3. assign_tasks(): Assign tasks to agents
4. make_batch_decision(): Generate batch decision response

The workflow follows the design in docs/superpowers/specs/2026-03-19-ralph-foreman-workflow-design.md
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from ...contracts.v1.ralph_ipc import (
    ReadyBatchSuggestion,
    BatchDecision,
    BatchDecisionType,
    TaskRef,
)
from ...util.time import utc_now_iso

from .agent_pool import AgentPoolManager, TaskAssignment


# Default paths relative to project root
DEFAULT_AGENTS_DIR = Path(".cccc/agents")
DEFAULT_MODELS_REGISTRY_PATH = Path(".cccc/models/registry.yaml")
DEFAULT_CAPABILITIES_DIR = Path(".cccc/capabilities")


@dataclass
class BatchEvaluationResult:
    """Result of evaluating a ready batch suggestion.

    Attributes:
        suggestion: Original suggestion from Ralph
        approved_tasks: Tasks approved for execution
        rejected_tasks: Tasks rejected from the batch
        skipped_task_ids: Tasks skipped before batch registration
        assignments: Task-to-agent assignments
        decision: Overall batch decision
        reason: Decision rationale
    """

    suggestion: ReadyBatchSuggestion
    approved_tasks: List[TaskRef] = field(default_factory=list)
    rejected_tasks: List[TaskRef] = field(default_factory=list)
    skipped_task_ids: List[str] = field(default_factory=list)
    assignments: List[TaskAssignment] = field(default_factory=list)
    decision: BatchDecisionType = "approved"
    reason: str = ""


def receive_ready_batch(
    suggestion: ReadyBatchSuggestion,
    *,
    validate: bool = True,
) -> ReadyBatchSuggestion:
    """Receive and validate a ready batch suggestion from Ralph.

    This is the entry point for Foreman's batch processing workflow.

    Args:
        suggestion: The batch suggestion from Ralph
        validate: Whether to perform validation

    Returns:
        The validated suggestion (potentially with corrections)

    Raises:
        ValueError: If suggestion is invalid and cannot be corrected
    """
    if validate:
        # Validate suggestion structure
        if not suggestion.suggestion_id:
            raise ValueError("Suggestion must have an ID")
        if not suggestion.workflow_id:
            raise ValueError("Suggestion must have a workflow ID")
        if not suggestion.tasks:
            raise ValueError("Suggestion must have at least one task")

        # Validate each task
        for task in suggestion.tasks:
            if not task.id:
                raise ValueError(f"Task must have an ID: {task}")

    return suggestion


def evaluate_agent_pool(
    tasks: List[TaskRef],
    pool_manager: AgentPoolManager,
    *,
    min_score: int = 50,
) -> Dict[str, List[Dict[str, Any]]]:
    """Evaluate the agent pool for a list of tasks.

    For each task, evaluates all available agents and returns
    scored candidates.

    Args:
        tasks: List of tasks to evaluate agents for
        pool_manager: The agent pool manager
        min_score: Minimum score threshold for candidate agents

    Returns:
        Dict mapping task_id to list of agent evaluation results
    """
    results: Dict[str, List[Dict[str, Any]]] = {}

    for task in tasks:
        evaluations = pool_manager.evaluate_for_task(task, min_score=0)

        task_results = []
        for eval_result in evaluations:
            task_results.append(
                {
                    "agent_id": eval_result.agent.id,
                    "agent_name": eval_result.agent.name,
                    "score": eval_result.score,
                    "is_suitable": eval_result.is_suitable(min_score),
                    "is_available": eval_result.is_available,
                    "reasons": eval_result.reasons,
                }
            )

        results[task.id] = task_results

    return results


def assign_tasks(
    tasks: List[TaskRef],
    pool_manager: AgentPoolManager,
    *,
    min_score: int = 50,
    prefer_reuse: bool = True,
    busy_agent_ids: Optional[set] = None,
    task_model_suggestions: Optional[Dict[str, str]] = None,
) -> List[TaskAssignment]:
    """Assign tasks to agents.

    For each task, finds or creates the best agent and assigns
    the task to it.

    Args:
        tasks: List of tasks to assign
        pool_manager: The agent pool manager
        min_score: Minimum score for agent reuse
        prefer_reuse: Whether to prefer reusing existing agents
        busy_agent_ids: Set of agent IDs currently busy (from engine/shadow state)
        task_model_suggestions: Per-task model suggestions from ralph (task_id -> model_key)

    Returns:
        List of task assignments
    """
    assignments: List[TaskAssignment] = []
    suggestions = task_model_suggestions or {}

    for task in tasks:
        assignment = pool_manager.create_or_reuse_agent(
            task,
            min_score=min_score,
            prefer_reuse=prefer_reuse,
            busy_agent_ids=busy_agent_ids,
            suggested_model_key=suggestions.get(task.id),
        )
        assignments.append(assignment)

    return assignments


def make_batch_decision(
    suggestion: ReadyBatchSuggestion,
    assignments: List[TaskAssignment],
    *,
    rejected_task_ids: Optional[List[str]] = None,
    decision_override: Optional[BatchDecisionType] = None,
    reason: str = "",
) -> BatchDecision:
    """Generate a batch decision based on task assignments.

    Args:
        suggestion: Original batch suggestion from Ralph
        assignments: Task-to-agent assignments
        rejected_task_ids: Optional list of task IDs to reject
        decision_override: Optional explicit decision type
        reason: Decision rationale

    Returns:
        BatchDecision to send back to Ralph/Daemon
    """
    rejected_task_ids = rejected_task_ids or []

    # Determine approved vs rejected tasks
    approved_tasks: List[str] = []
    rejected_tasks: List[str] = list(rejected_task_ids)

    for assignment in assignments:
        if assignment.agent_id:  # Valid assignment
            if assignment.task.id not in rejected_tasks:
                approved_tasks.append(assignment.task.id)
        else:  # Failed assignment
            if assignment.task.id not in rejected_tasks:
                rejected_tasks.append(assignment.task.id)

    # Determine decision type
    if decision_override:
        decision = decision_override
    elif not approved_tasks and rejected_tasks:
        decision = "rejected"
    elif approved_tasks and rejected_tasks:
        decision = "modified"
    elif approved_tasks:
        decision = "approved"
    else:
        decision = "deferred"

    # Generate reason if not provided
    if not reason:
        if decision == "approved":
            reason = f"Approved {len(approved_tasks)} tasks for execution"
        elif decision == "modified":
            reason = f"Approved {len(approved_tasks)} tasks, rejected {len(rejected_tasks)} tasks"
        elif decision == "rejected":
            reason = f"Rejected all {len(rejected_tasks)} tasks"
        else:
            reason = "Decision deferred pending additional evaluation"

    return BatchDecision(
        decision_id=f"dec-{uuid.uuid4().hex[:8]}",
        suggestion_id=suggestion.suggestion_id,
        workflow_id=suggestion.workflow_id,
        decision=decision,
        approved_tasks=approved_tasks,
        rejected_tasks=rejected_tasks,
        reason=reason,
        created_at=utc_now_iso(),
    )


class ForemanWorkflow:
    """Main workflow orchestrator for Foreman.

    This class ties together all the workflow steps and provides
    a high-level interface for batch processing.
    """

    def __init__(
        self,
        project_root: Path,
        *,
        agents_dir: Optional[Path] = None,
        models_registry_path: Optional[Path] = None,
        capabilities_dir: Optional[Path] = None,
        feishu_chat_id: Optional[str] = None,
        group_loader: Optional[callable] = None,
    ):
        """Initialize the Foreman workflow.

        Args:
            project_root: Root directory of the project
            agents_dir: Directory for agent YAML files
            models_registry_path: Path to models registry
            capabilities_dir: Directory for capability files
            feishu_chat_id: Optional Feishu chat ID for notifications
            group_loader: Optional callback returning list of enabled peer actor dicts
        """
        self.project_root = project_root
        self.agents_dir = agents_dir or (project_root / DEFAULT_AGENTS_DIR)
        self.models_registry_path = models_registry_path or (
            project_root / DEFAULT_MODELS_REGISTRY_PATH
        )
        self.capabilities_dir = capabilities_dir or (
            project_root / DEFAULT_CAPABILITIES_DIR
        )
        self.feishu_chat_id = feishu_chat_id

        # Initialize pool manager
        self.pool_manager = AgentPoolManager(
            agents_dir=self.agents_dir,
            models_registry_path=self.models_registry_path,
            capabilities_dir=self.capabilities_dir,
            group_loader=group_loader,
        )

        # Optional Feishu adapter (lazy-loaded)
        self._feishu_adapter: Optional[Any] = None

    def process_batch_suggestion(
        self,
        suggestion: ReadyBatchSuggestion,
        *,
        auto_approve: bool = True,
        notify_feishu: bool = True,
    ) -> BatchEvaluationResult:
        """Process a complete batch suggestion through the workflow.

        This is the main entry point for batch processing. It:
        1. Receives and validates the suggestion
        2. Evaluates the agent pool
        3. Assigns tasks to agents
        4. Generates a batch decision
        5. Optionally notifies via Feishu

        Args:
            suggestion: Batch suggestion from Ralph
            auto_approve: Whether to auto-approve valid batches
            notify_feishu: Whether to send Feishu notifications

        Returns:
            BatchEvaluationResult with all processing details
        """
        result = BatchEvaluationResult(suggestion=suggestion)

        try:
            # Step 1: Receive and validate
            validated = receive_ready_batch(suggestion)
            result.suggestion = validated

            # Step 2: Evaluate agent pool
            _evaluations = evaluate_agent_pool(
                validated.tasks,
                self.pool_manager,
            )

            # Step 3: Assign tasks
            assignments = assign_tasks(
                validated.tasks,
                self.pool_manager,
                prefer_reuse=True,
                task_model_suggestions=getattr(suggestion, "task_model_suggestions", None),
            )
            result.assignments = assignments

            # Step 4: Determine approved/rejected
            for assignment in assignments:
                if assignment.agent_id:
                    result.approved_tasks.append(assignment.task)
                else:
                    result.rejected_tasks.append(assignment.task)

            # Step 5: Set decision
            if not result.approved_tasks:
                result.decision = "rejected"
                result.reason = "No suitable agents found for any task"
            elif result.rejected_tasks:
                result.decision = "modified"
                result.reason = (
                    f"Approved {len(result.approved_tasks)} tasks, "
                    f"rejected {len(result.rejected_tasks)} tasks"
                )
            else:
                result.decision = "approved"
                result.reason = f"Approved all {len(result.approved_tasks)} tasks"

            # Step 6: Notify via Feishu if enabled
            if notify_feishu and self.feishu_chat_id:
                self._notify_batch_start(result)

        except ValueError as e:
            result.decision = "rejected"
            result.reason = f"Validation error: {e}"

        return result

    def _notify_batch_start(self, result: BatchEvaluationResult) -> None:
        """Send Feishu notification about batch start."""
        if not self.feishu_chat_id:
            return

        # Build message
        lines = [f"[任务进度] 批次 #{result.suggestion.suggestion_id[:8]} 开始执行", ""]

        if result.approved_tasks:
            lines.append("任务列表：")
            for assignment in result.assignments:
                if assignment.agent_id:
                    lines.append(
                        f"- {assignment.task.id}: {assignment.task.title} -> {assignment.agent_name}"
                    )
            lines.append("")

        if result.rejected_tasks:
            lines.append("已跳过的任务：")
            for task in result.rejected_tasks:
                lines.append(f"- {task.id}: {task.title}")
            lines.append("")

        lines.append(f"决策：{result.decision}")
        lines.append(f"原因：{result.reason}")

        message = "\n".join(lines)
        self._send_feishu_message(message)

    def _send_feishu_message(self, text: str) -> bool:
        """Send a message via Feishu.

        This is a placeholder for Feishu integration.
        In production, this would use the FeishuAdapter.
        """
        if not self.feishu_chat_id:
            return False

        # Lazy load Feishu adapter
        # In production, this would be injected or configured
        # For now, just log the message
        # TODO: Integrate with actual FeishuAdapter when available
        print(f"[Feishu -> {self.feishu_chat_id}] {text}")
        return True

    def get_batch_decision(
        self,
        result: BatchEvaluationResult,
    ) -> BatchDecision:
        """Generate a BatchDecision from an evaluation result.

        Args:
            result: The batch evaluation result

        Returns:
            BatchDecision to send back to Ralph/Daemon
        """
        return make_batch_decision(
            result.suggestion,
            result.assignments,
            rejected_task_ids=[t.id for t in result.rejected_tasks],
            decision_override=result.decision,
            reason=result.reason,
        )

    def release_completed_task(self, task_id: str, agent_id: str) -> bool:
        """Release an agent after task completion.

        Args:
            task_id: Completed task ID
            agent_id: Agent that completed the task

        Returns:
            True if release successful
        """
        return self.pool_manager.release_agent(agent_id)

    def notify_task_completed(
        self,
        task_id: str,
        agent_name: str,
        duration_seconds: int,
        changed_files: List[str],
    ) -> None:
        """Send Feishu notification about task completion."""
        if not self.feishu_chat_id:
            return

        # Format duration
        if duration_seconds < 60:
            duration_str = f"{duration_seconds}s"
        else:
            minutes = duration_seconds // 60
            seconds = duration_seconds % 60
            duration_str = f"{minutes}m {seconds}s"

        # Build message
        lines = [
            f"[任务进度] {task_id} 已完成",
            "",
            f"执行者：{agent_name}",
            f"耗时：{duration_str}",
        ]

        if changed_files:
            lines.append(f"变更文件：{', '.join(changed_files[:5])}")
            if len(changed_files) > 5:
                lines.append(f"  ... 及其他 {len(changed_files) - 5} 个文件")

        lines.append("")
        lines.append("下一批次将在验证通过后开始。")

        message = "\n".join(lines)
        self._send_feishu_message(message)

    def notify_task_blocked(
        self,
        task_id: str,
        reason: str,
        suggestion: str,
    ) -> None:
        """Send Feishu notification about blocked task."""
        if not self.feishu_chat_id:
            return

        lines = [
            f"[需要协助] {task_id} 执行受阻",
            "",
            f"原因：{reason}",
            f"建议操作：{suggestion}",
            "",
            "请回复指示后续处理方式。",
        ]

        message = "\n".join(lines)
        self._send_feishu_message(message)
