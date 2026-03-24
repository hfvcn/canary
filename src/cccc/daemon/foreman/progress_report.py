"""Feishu progress reporting for Foreman.

This module provides the ProgressReporter class for:
- 阶段性进度汇总
- Feishu 卡片消息构建
- 关键事件通知（完成、失败、需要介入）

Architecture:
  ProgressReporter (收集状态)
    -> build_progress_card (构建卡片)
    -> Feishu adapter (发送)

Event types:
- batch_started: 批次开始执行
- task_completed: 单个任务完成
- batch_completed: 批次全部完成
- task_failed: 任务失败
- intervention_needed: 需要人工介入
- workflow_completed: 整个工作流完成
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol

from ...ports.im.templates.progress_card import (
    BatchInfo,
    EventType,
    ProgressCardBuilder,
    ProgressStatus,
    TaskInfo,
    build_batch_completed_card,
    build_batch_started_card,
    build_intervention_card,
    build_task_completed_card,
    build_task_failed_card,
    build_workflow_completed_card,
)


class FeishuSender(Protocol):
    """Protocol for Feishu message sending capability."""

    def send_card(self, chat_id: str, card: Dict[str, Any]) -> bool:
        """Send a card message to a chat."""
        ...


@dataclass
class ProgressState:
    """Current progress state for a workflow/batch.

    Tracks running state for progress summarization.
    """

    workflow_id: str
    current_batch_id: str = ""
    batch_start_time: float = 0.0
    workflow_start_time: float = 0.0
    total_batches: int = 0
    completed_batches: int = 0
    tasks: Dict[str, TaskInfo] = field(default_factory=dict)
    current_batch_task_ids: List[str] = field(default_factory=list)

    def get_batch_duration(self) -> int:
        """Get current batch duration in seconds."""
        if not self.batch_start_time:
            return 0
        return int(time.time() - self.batch_start_time)

    def get_workflow_duration(self) -> int:
        """Get total workflow duration in seconds."""
        if not self.workflow_start_time:
            return 0
        return int(time.time() - self.workflow_start_time)

    def count_by_status(self, status: ProgressStatus) -> int:
        """Count tasks with given status."""
        return sum(1 for t in self.tasks.values() if t.status == status)

    def get_current_batch_tasks(self) -> List[TaskInfo]:
        """Return task infos that belong to the active batch."""
        return [
            self.tasks[task_id]
            for task_id in self.current_batch_task_ids
            if task_id in self.tasks
        ]

    def count_current_batch_by_status(self, status: ProgressStatus) -> int:
        """Count tasks with a given status in the active batch only."""
        return sum(1 for task in self.get_current_batch_tasks() if task.status == status)


class ProgressReporter:
    """Feishu progress reporter for Foreman workflow.

    Responsible for:
    - Tracking workflow/batch/task progress state
    - Building appropriate card messages for events
    - Sending notifications via Feishu adapter

    Usage:
        reporter = ProgressReporter(
            chat_id="oc_xxx",
            sender=feishu_adapter,
        )

        # Start batch
        reporter.on_batch_started(batch_id, tasks)

        # Task events
        reporter.on_task_completed(task_id, agent, duration, files)
        reporter.on_task_failed(task_id, error, suggestion)

        # Batch complete
        reporter.on_batch_completed()

        # Workflow complete
        reporter.on_workflow_completed()
    """

    def __init__(
        self,
        chat_id: str,
        sender: Optional[FeishuSender] = None,
        *,
        card_builder: Optional[ProgressCardBuilder] = None,
        log_fn: Optional[Callable[[str], None]] = None,
    ):
        """Initialize progress reporter.

        Args:
            chat_id: Feishu chat ID for notifications
            sender: Feishu adapter for sending messages
            card_builder: Optional custom card builder
            log_fn: Optional logging function
        """
        self.chat_id = chat_id
        self.sender = sender
        self.card_builder = card_builder or ProgressCardBuilder()
        self._log = log_fn or (lambda msg: None)

        # Progress state
        self._state: Optional[ProgressState] = None
        self._event_history: List[Dict[str, Any]] = []

    # ========== State Management ==========

    def init_workflow(self, workflow_id: str) -> None:
        """Initialize a new workflow tracking state.

        Args:
            workflow_id: Workflow identifier
        """
        self._state = ProgressState(
            workflow_id=workflow_id,
            workflow_start_time=time.time(),
        )
        self._event_history.clear()
        self._log(f"[progress] Initialized workflow: {workflow_id}")

    def get_state(self) -> Optional[ProgressState]:
        """Get current progress state."""
        return self._state

    # ========== Progress Summarization ==========

    def summarize_progress(self) -> Dict[str, Any]:
        """Summarize current workflow progress.

        Returns:
            Dict with progress summary including:
            - workflow_id
            - current_batch
            - tasks_completed, tasks_failed, tasks_pending
            - duration
            - events (recent history)
        """
        if not self._state:
            return {"status": "idle", "message": "No active workflow"}

        return {
            "status": "running",
            "workflow_id": self._state.workflow_id,
            "current_batch": self._state.current_batch_id,
            "batches": {
                "total": self._state.total_batches,
                "completed": self._state.completed_batches,
            },
            "tasks": {
                "total": len(self._state.tasks),
                "completed": self._state.count_by_status(ProgressStatus.COMPLETED),
                "failed": self._state.count_by_status(ProgressStatus.FAILED),
                "running": self._state.count_by_status(ProgressStatus.RUNNING),
                "pending": self._state.count_by_status(ProgressStatus.PENDING),
            },
            "duration": {
                "workflow_seconds": self._state.get_workflow_duration(),
                "batch_seconds": self._state.get_batch_duration(),
            },
            "recent_events": self._event_history[-10:],
        }

    # ========== Event Handlers ==========

    def on_batch_started(
        self,
        batch_id: str,
        tasks: List[Dict[str, Any]],
        *,
        workflow_id: Optional[str] = None,
    ) -> bool:
        """Handle batch started event.

        Args:
            batch_id: Batch identifier
            tasks: List of task dicts with id, title, agent_name
            workflow_id: Optional workflow ID (auto-initialized if needed)

        Returns:
            True if notification sent successfully
        """
        # Auto-initialize workflow if needed
        if not self._state and workflow_id:
            self.init_workflow(workflow_id)
        if not self._state:
            self._log("[progress] No workflow state, initializing with batch ID")
            self.init_workflow(batch_id)

        # Update state
        self._state.current_batch_id = batch_id
        self._state.batch_start_time = time.time()
        self._state.total_batches += 1
        self._state.current_batch_task_ids = []

        # Track tasks
        task_infos: List[TaskInfo] = []
        for t in tasks:
            task_info = TaskInfo(
                id=t.get("id", ""),
                title=t.get("title", ""),
                agent_name=t.get("agent_name", ""),
                status=ProgressStatus.PENDING,
            )
            self._state.tasks[task_info.id] = task_info
            self._state.current_batch_task_ids.append(task_info.id)
            task_infos.append(task_info)

        # Record event
        self._record_event(EventType.BATCH_STARTED, {
            "batch_id": batch_id,
            "task_count": len(tasks),
        })

        # Build and send card
        batch_info = BatchInfo(
            batch_id=batch_id,
            workflow_id=self._state.workflow_id,
            total_tasks=len(tasks),
        )

        card = build_batch_started_card(
            batch_info,
            task_infos,
            builder=self.card_builder,
        )

        return self._send_card(card)

    def on_task_completed(
        self,
        task_id: str,
        agent_name: str,
        duration_seconds: int,
        changed_files: List[str],
        *,
        notify: bool = True,
    ) -> bool:
        """Handle task completed event.

        Args:
            task_id: Completed task ID
            agent_name: Name of agent that completed the task
            duration_seconds: Task duration
            changed_files: List of modified files
            notify: Whether to send notification

        Returns:
            True if notification sent (or notify=False)
        """
        if not self._state:
            self._log(f"[progress] No state for task completion: {task_id}")
            return False

        # Update task state
        if task_id in self._state.tasks:
            task_info = self._state.tasks[task_id]
            task_info.status = ProgressStatus.COMPLETED
            task_info.agent_name = agent_name
            task_info.duration_seconds = duration_seconds
            task_info.changed_files = changed_files
        else:
            # Task not tracked, create entry
            task_info = TaskInfo(
                id=task_id,
                title=task_id,
                status=ProgressStatus.COMPLETED,
                agent_name=agent_name,
                duration_seconds=duration_seconds,
                changed_files=changed_files,
            )
            self._state.tasks[task_id] = task_info

        # Record event
        self._record_event(EventType.TASK_COMPLETED, {
            "task_id": task_id,
            "agent": agent_name,
            "duration": duration_seconds,
            "files_changed": len(changed_files),
        })

        if not notify:
            return True

        # Build batch context
        batch_info = BatchInfo(
            batch_id=self._state.current_batch_id,
            workflow_id=self._state.workflow_id,
            total_tasks=len(self._state.current_batch_task_ids),
            completed_tasks=self._state.count_current_batch_by_status(ProgressStatus.COMPLETED),
        )

        card = build_task_completed_card(
            task_info,
            batch=batch_info,
            builder=self.card_builder,
        )

        return self._send_card(card)

    def on_task_failed(
        self,
        task_id: str,
        error_message: str,
        *,
        suggestion: str = "",
        agent_name: str = "",
    ) -> bool:
        """Handle task failed event.

        Args:
            task_id: Failed task ID
            error_message: Error description
            suggestion: Optional remediation suggestion
            agent_name: Name of agent that was executing

        Returns:
            True if notification sent successfully
        """
        if not self._state:
            self._log(f"[progress] No state for task failure: {task_id}")
            return False

        # Update task state
        if task_id in self._state.tasks:
            task_info = self._state.tasks[task_id]
            task_info.status = ProgressStatus.FAILED
            task_info.error_message = error_message
            if agent_name:
                task_info.agent_name = agent_name
        else:
            task_info = TaskInfo(
                id=task_id,
                title=task_id,
                status=ProgressStatus.FAILED,
                error_message=error_message,
                agent_name=agent_name,
            )
            self._state.tasks[task_id] = task_info

        # Record event
        self._record_event(EventType.TASK_FAILED, {
            "task_id": task_id,
            "error": error_message[:200],
        })

        # Build batch context
        batch_info = BatchInfo(
            batch_id=self._state.current_batch_id,
            workflow_id=self._state.workflow_id,
            total_tasks=len(self._state.current_batch_task_ids),
            failed_tasks=self._state.count_current_batch_by_status(ProgressStatus.FAILED),
        )

        card = build_task_failed_card(
            task_info,
            batch=batch_info,
            suggestion=suggestion,
            builder=self.card_builder,
        )

        return self._send_card(card)

    def on_intervention_needed(
        self,
        task_id: str,
        reason: str,
        *,
        options: Optional[List[str]] = None,
        agent_name: str = "",
    ) -> bool:
        """Handle intervention needed event.

        Args:
            task_id: Task requiring intervention
            reason: Reason for intervention
            options: Suggested action options
            agent_name: Name of agent requesting help

        Returns:
            True if notification sent successfully
        """
        if not self._state:
            self._log(f"[progress] No state for intervention: {task_id}")
            return False

        # Update task state
        if task_id in self._state.tasks:
            task_info = self._state.tasks[task_id]
            task_info.status = ProgressStatus.BLOCKED
            if agent_name:
                task_info.agent_name = agent_name
        else:
            task_info = TaskInfo(
                id=task_id,
                title=task_id,
                status=ProgressStatus.BLOCKED,
                agent_name=agent_name,
            )
            self._state.tasks[task_id] = task_info

        # Record event
        self._record_event(EventType.INTERVENTION_NEEDED, {
            "task_id": task_id,
            "reason": reason[:200],
        })

        card = build_intervention_card(
            task_info,
            reason,
            options=options,
            builder=self.card_builder,
        )

        return self._send_card(card)

    def on_batch_completed(self) -> bool:
        """Handle batch completed event.

        Returns:
            True if notification sent successfully
        """
        if not self._state:
            self._log("[progress] No state for batch completion")
            return False

        # Update state
        self._state.completed_batches += 1
        batch_duration = self._state.get_batch_duration()

        # Collect task infos
        task_infos = self._state.get_current_batch_tasks()

        # Build batch info
        batch_info = BatchInfo(
            batch_id=self._state.current_batch_id,
            workflow_id=self._state.workflow_id,
            total_tasks=len(task_infos),
            completed_tasks=self._state.count_current_batch_by_status(ProgressStatus.COMPLETED),
            failed_tasks=self._state.count_current_batch_by_status(ProgressStatus.FAILED),
            skipped_tasks=self._state.count_current_batch_by_status(ProgressStatus.SKIPPED),
            duration_seconds=batch_duration,
            tasks=task_infos,
        )

        # Record event
        self._record_event(EventType.BATCH_COMPLETED, {
            "batch_id": self._state.current_batch_id,
            "completed": batch_info.completed_tasks,
            "failed": batch_info.failed_tasks,
            "duration": batch_duration,
        })

        card = build_batch_completed_card(
            batch_info,
            task_infos,
            builder=self.card_builder,
        )

        return self._send_card(card)

    def on_workflow_completed(
        self,
        *,
        summary: str = "",
    ) -> bool:
        """Handle workflow completed event.

        Args:
            summary: Optional summary text

        Returns:
            True if notification sent successfully
        """
        if not self._state:
            self._log("[progress] No state for workflow completion")
            return False

        workflow_duration = self._state.get_workflow_duration()
        total_tasks = len(self._state.tasks)

        # Record event
        self._record_event(EventType.WORKFLOW_COMPLETED, {
            "workflow_id": self._state.workflow_id,
            "batches": self._state.completed_batches,
            "tasks": total_tasks,
            "duration": workflow_duration,
        })

        card = build_workflow_completed_card(
            self._state.workflow_id,
            self._state.completed_batches,
            total_tasks,
            workflow_duration,
            summary=summary,
            builder=self.card_builder,
        )

        result = self._send_card(card)

        # Clear state after workflow completion
        self._state = None

        return result

    # ========== Notification Helpers ==========

    def notify_completion(
        self,
        task_id: str,
        agent_name: str,
        duration_seconds: int,
        changed_files: List[str],
    ) -> bool:
        """Convenience method for task completion notification.

        Equivalent to on_task_completed with notify=True.
        """
        return self.on_task_completed(
            task_id,
            agent_name,
            duration_seconds,
            changed_files,
            notify=True,
        )

    def notify_failure(
        self,
        task_id: str,
        error_message: str,
        suggestion: str = "",
    ) -> bool:
        """Convenience method for task failure notification."""
        return self.on_task_failed(
            task_id,
            error_message,
            suggestion=suggestion,
        )

    def notify_intervention_needed(
        self,
        task_id: str,
        reason: str,
        options: Optional[List[str]] = None,
    ) -> bool:
        """Convenience method for intervention notification."""
        return self.on_intervention_needed(
            task_id,
            reason,
            options=options,
        )

    # ========== Internal Methods ==========

    def _send_card(self, card: Dict[str, Any]) -> bool:
        """Send a card message via Feishu adapter.

        Args:
            card: Card payload to send

        Returns:
            True if sent successfully
        """
        if not self.chat_id:
            self._log("[progress] No chat ID configured")
            return False

        if not self.sender:
            # Log the card for debugging when no sender
            self._log(f"[progress] Would send card: {json.dumps(card, ensure_ascii=False)[:200]}...")
            return True

        try:
            return self.sender.send_card(self.chat_id, card)
        except Exception as e:
            self._log(f"[progress] Failed to send card: {e}")
            return False

    def _record_event(self, event_type: EventType, data: Dict[str, Any]) -> None:
        """Record an event in history.

        Args:
            event_type: Type of event
            data: Event data
        """
        event = {
            "type": event_type.value,
            "timestamp": time.time(),
            **data,
        }
        self._event_history.append(event)

        # Limit history size
        if len(self._event_history) > 100:
            self._event_history = self._event_history[-50:]
