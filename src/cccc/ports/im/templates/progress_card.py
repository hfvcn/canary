"""Feishu card message templates for progress reporting.

This module provides card message builders for workflow progress events.
Templates are designed to be platform-agnostic where possible, with
Feishu-specific formatting handled separately.

Card types:
- batch_started: 批次开始执行
- task_completed: 单个任务完成
- batch_completed: 批次全部完成
- task_failed: 任务失败
- intervention_needed: 需要人工介入
- workflow_completed: 整个工作流完成
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Literal, Optional


class EventType(str, Enum):
    """Progress event types."""

    BATCH_STARTED = "batch_started"
    TASK_COMPLETED = "task_completed"
    BATCH_COMPLETED = "batch_completed"
    TASK_FAILED = "task_failed"
    TASK_STALLED = "task_stalled"
    TASK_OFFLINE = "task_offline"
    INTERVENTION_NEEDED = "intervention_needed"
    WORKFLOW_COMPLETED = "workflow_completed"


class ProgressStatus(str, Enum):
    """Task/batch progress status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STALLED = "stalled"
    OFFLINE = "offline"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


# Card header templates (Feishu color scheme)
HEADER_TEMPLATES = {
    EventType.BATCH_STARTED: {"template": "blue", "icon": "📋"},
    EventType.TASK_COMPLETED: {"template": "green", "icon": "✅"},
    EventType.BATCH_COMPLETED: {"template": "green", "icon": "🎉"},
    EventType.TASK_FAILED: {"template": "red", "icon": "❌"},
    EventType.INTERVENTION_NEEDED: {"template": "orange", "icon": "⚠️"},
    EventType.WORKFLOW_COMPLETED: {"template": "turquoise", "icon": "🏁"},
}


def _escape_lark_md(text: str) -> str:
    """Escape special characters for Lark Markdown."""
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _format_duration(seconds: int) -> str:
    """Format duration in human-readable form."""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes}m {secs}s" if secs else f"{minutes}m"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"


@dataclass
class TaskInfo:
    """Task information for card display."""

    id: str
    title: str
    status: ProgressStatus = ProgressStatus.PENDING
    agent_name: str = ""
    duration_seconds: int = 0
    changed_files: List[str] = field(default_factory=list)
    error_message: str = ""


@dataclass
class BatchInfo:
    """Batch information for card display."""

    batch_id: str
    workflow_id: str = ""
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    skipped_tasks: int = 0
    duration_seconds: int = 0
    tasks: List[TaskInfo] = field(default_factory=list)


class ProgressCardBuilder:
    """Builder for Feishu progress card messages.

    Generates interactive card payloads that can be sent via Feishu API.
    Cards follow the Feishu Message Card v2 format.
    """

    def __init__(self, title: str = "CCCC 工作流"):
        """Initialize card builder.

        Args:
            title: Default card title prefix
        """
        self.title_prefix = title

    def build_card(
        self,
        event_type: EventType,
        title: str,
        elements: List[Dict[str, Any]],
        *,
        note: str = "",
    ) -> Dict[str, Any]:
        """Build a complete Feishu card payload.

        Args:
            event_type: Type of progress event
            title: Card title
            elements: List of card elements
            note: Optional footer note

        Returns:
            Complete card payload dict
        """
        header_config = HEADER_TEMPLATES.get(
            event_type,
            {"template": "blue", "icon": "📋"},
        )

        card: Dict[str, Any] = {
            "config": {
                "wide_screen_mode": True,
                "enable_forward": True,
            },
            "header": {
                "template": header_config["template"],
                "title": {
                    "tag": "plain_text",
                    "content": f"{header_config['icon']} {title}",
                },
            },
            "elements": elements,
        }

        if note:
            card["elements"].append(
                {
                    "tag": "note",
                    "elements": [
                        {"tag": "plain_text", "content": note},
                    ],
                }
            )

        return card

    def build_text_element(self, content: str, *, is_markdown: bool = True) -> Dict[str, Any]:
        """Build a text element.

        Args:
            content: Text content
            is_markdown: Whether content is Lark Markdown

        Returns:
            Text element dict
        """
        return {
            "tag": "div",
            "text": {
                "tag": "lark_md" if is_markdown else "plain_text",
                "content": _escape_lark_md(content) if is_markdown else content,
            },
        }

    def build_fields(self, fields: List[tuple[str, str]]) -> Dict[str, Any]:
        """Build a fields element (key-value grid).

        Args:
            fields: List of (label, value) tuples

        Returns:
            Fields element dict
        """
        field_elements = []
        for label, value in fields:
            field_elements.append(
                {
                    "is_short": True,
                    "text": {
                        "tag": "lark_md",
                        "content": f"**{_escape_lark_md(label)}**\n{_escape_lark_md(value)}",
                    },
                }
            )
        return {"tag": "div", "fields": field_elements}

    def build_divider(self) -> Dict[str, Any]:
        """Build a horizontal divider element."""
        return {"tag": "hr"}

    def build_task_list(
        self,
        tasks: List[TaskInfo],
        *,
        show_status: bool = True,
        show_agent: bool = True,
    ) -> List[Dict[str, Any]]:
        """Build task list elements.

        Args:
            tasks: List of tasks to display
            show_status: Whether to show status icons
            show_agent: Whether to show agent names

        Returns:
            List of element dicts
        """
        elements: List[Dict[str, Any]] = []

        for task in tasks:
            # Status icon
            status_icons = {
                ProgressStatus.PENDING: "⏳",
                ProgressStatus.RUNNING: "🔄",
                ProgressStatus.COMPLETED: "✅",
                ProgressStatus.FAILED: "❌",
                ProgressStatus.STALLED: "⏸️",
                ProgressStatus.OFFLINE: "📴",
                ProgressStatus.BLOCKED: "🚫",
                ProgressStatus.SKIPPED: "⏭️",
            }
            icon = status_icons.get(task.status, "•") if show_status else "•"

            # Build task line
            parts = [f"{icon} **{task.id}**: {task.title}"]

            if show_agent and task.agent_name:
                parts.append(f" → {task.agent_name}")

            if task.duration_seconds > 0:
                parts.append(f" ({_format_duration(task.duration_seconds)})")

            elements.append(self.build_text_element("".join(parts)))

        return elements

    def build_progress_bar(
        self,
        completed: int,
        total: int,
        *,
        label: str = "进度",
    ) -> Dict[str, Any]:
        """Build a text-based progress bar.

        Args:
            completed: Number of completed items
            total: Total number of items
            label: Progress label

        Returns:
            Text element with progress bar
        """
        if total <= 0:
            percentage = 0
        else:
            percentage = int((completed / total) * 100)

        # Build ASCII progress bar
        bar_width = 10
        filled = int(bar_width * completed / total) if total > 0 else 0
        bar = "█" * filled + "░" * (bar_width - filled)

        content = f"**{label}**: [{bar}] {completed}/{total} ({percentage}%)"
        return self.build_text_element(content)

    def build_action_buttons(
        self,
        buttons: List[tuple[str, str, str]],
    ) -> Dict[str, Any]:
        """Build action buttons element.

        Args:
            buttons: List of (text, value, type) tuples
                     type can be: primary, danger, default

        Returns:
            Actions element dict
        """
        actions = []
        for text, value, btn_type in buttons:
            actions.append(
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": text},
                    "type": btn_type,
                    "value": {"action": value},
                }
            )
        return {"tag": "action", "actions": actions}


# Convenience functions for common card types


def build_batch_started_card(
    batch: BatchInfo,
    tasks: List[TaskInfo],
    *,
    builder: Optional[ProgressCardBuilder] = None,
) -> Dict[str, Any]:
    """Build a batch started notification card.

    Args:
        batch: Batch information
        tasks: List of tasks in the batch
        builder: Optional card builder instance

    Returns:
        Complete card payload
    """
    builder = builder or ProgressCardBuilder()

    elements = [
        builder.build_fields(
            [
                ("批次 ID", batch.batch_id[:12]),
                ("任务数", str(batch.total_tasks)),
            ]
        ),
        builder.build_divider(),
    ]

    # Task list
    if tasks:
        elements.append(builder.build_text_element("**任务列表**"))
        elements.extend(builder.build_task_list(tasks, show_status=False))

    return builder.build_card(
        EventType.BATCH_STARTED,
        f"批次 #{batch.batch_id[:8]} 开始执行",
        elements,
        note="任务执行中，完成后将自动通知",
    )


def build_task_completed_card(
    task: TaskInfo,
    *,
    batch: Optional[BatchInfo] = None,
    builder: Optional[ProgressCardBuilder] = None,
) -> Dict[str, Any]:
    """Build a task completed notification card.

    Args:
        task: Completed task information
        batch: Optional batch context
        builder: Optional card builder instance

    Returns:
        Complete card payload
    """
    builder = builder or ProgressCardBuilder()

    fields = [
        ("任务", task.title),
        ("执行者", task.agent_name or "自动分配"),
        ("耗时", _format_duration(task.duration_seconds)),
    ]

    elements = [builder.build_fields(fields)]

    # Changed files
    if task.changed_files:
        elements.append(builder.build_divider())
        files_text = "**变更文件**\n"
        for f in task.changed_files[:5]:
            files_text += f"• `{f}`\n"
        if len(task.changed_files) > 5:
            files_text += f"• _...及其他 {len(task.changed_files) - 5} 个文件_"
        elements.append(builder.build_text_element(files_text))

    # Batch progress if available
    if batch:
        elements.append(builder.build_divider())
        elements.append(
            builder.build_progress_bar(
                batch.completed_tasks,
                batch.total_tasks,
                label="批次进度",
            )
        )

    if task.status == ProgressStatus.SKIPPED:
        card_title = f"任务 {task.id} 已完成（未验证）"
        card_event = EventType.TASK_COMPLETED
    else:
        card_title = f"任务 {task.id} 已完成"
        card_event = EventType.TASK_COMPLETED

    return builder.build_card(
        card_event,
        card_title,
        elements,
    )


def build_batch_completed_card(
    batch: BatchInfo,
    tasks: List[TaskInfo],
    *,
    builder: Optional[ProgressCardBuilder] = None,
) -> Dict[str, Any]:
    """Build a batch completed notification card.

    Args:
        batch: Completed batch information
        tasks: List of tasks in the batch
        builder: Optional card builder instance

    Returns:
        Complete card payload
    """
    builder = builder or ProgressCardBuilder()

    # Summary stats
    fields = [
        ("总任务数", str(batch.total_tasks)),
        ("已完成", str(batch.completed_tasks)),
    ]

    if batch.failed_tasks > 0:
        fields.append(("失败", str(batch.failed_tasks)))
    if batch.skipped_tasks > 0:
        fields.append(("跳过", str(batch.skipped_tasks)))

    fields.append(("总耗时", _format_duration(batch.duration_seconds)))

    elements = [builder.build_fields(fields)]

    # Task summary
    if tasks:
        elements.append(builder.build_divider())
        elements.append(builder.build_text_element("**任务执行情况**"))
        elements.extend(builder.build_task_list(tasks, show_status=True, show_agent=False))

    return builder.build_card(
        EventType.BATCH_COMPLETED,
        f"批次 #{batch.batch_id[:8]} 执行完成",
        elements,
        note="下一批次将在验证通过后开始",
    )


def build_task_failed_card(
    task: TaskInfo,
    *,
    batch: Optional[BatchInfo] = None,
    suggestion: str = "",
    builder: Optional[ProgressCardBuilder] = None,
) -> Dict[str, Any]:
    """Build a task failed notification card.

    Args:
        task: Failed task information
        batch: Optional batch context
        suggestion: Optional remediation suggestion
        builder: Optional card builder instance

    Returns:
        Complete card payload
    """
    builder = builder or ProgressCardBuilder()

    fields = [
        ("任务", task.title),
        ("执行者", task.agent_name or "自动分配"),
    ]

    if task.duration_seconds > 0:
        fields.append(("执行时长", _format_duration(task.duration_seconds)))

    elements = [builder.build_fields(fields)]

    # Error message
    if task.error_message:
        elements.append(builder.build_divider())
        elements.append(
            builder.build_text_element(f"**错误信息**\n```\n{task.error_message[:500]}\n```")
        )

    # Suggestion
    if suggestion:
        elements.append(builder.build_text_element(f"**建议操作**\n{suggestion}"))

    # Action buttons
    elements.append(
        builder.build_action_buttons(
            [
                ("重试", "retry", "primary"),
                ("跳过", "skip", "default"),
                ("查看详情", "details", "default"),
            ]
        )
    )

    return builder.build_card(
        EventType.TASK_FAILED,
        f"任务 {task.id} 执行失败",
        elements,
    )


def build_intervention_card(
    task: TaskInfo,
    reason: str,
    *,
    options: Optional[List[str]] = None,
    builder: Optional[ProgressCardBuilder] = None,
) -> Dict[str, Any]:
    """Build an intervention needed notification card.

    Args:
        task: Task needing intervention
        reason: Reason for intervention
        options: Optional list of suggested actions
        builder: Optional card builder instance

    Returns:
        Complete card payload
    """
    builder = builder or ProgressCardBuilder()

    elements = [
        builder.build_fields(
            [
                ("任务", task.title),
                ("执行者", task.agent_name or "自动分配"),
            ]
        ),
        builder.build_divider(),
        builder.build_text_element(f"**需要协助原因**\n{reason}"),
    ]

    # Suggested options
    if options:
        options_text = "**可选操作**\n"
        for i, opt in enumerate(options, 1):
            options_text += f"{i}. {opt}\n"
        elements.append(builder.build_text_element(options_text))

    # Action buttons
    elements.append(
        builder.build_action_buttons(
            [
                ("继续执行", "continue", "primary"),
                ("暂停任务", "pause", "default"),
                ("分配人工", "manual", "danger"),
            ]
        )
    )

    return builder.build_card(
        EventType.INTERVENTION_NEEDED,
        f"任务 {task.id} 需要人工介入",
        elements,
        note="请回复指示后续处理方式",
    )


def build_workflow_completed_card(
    workflow_id: str,
    batches_completed: int,
    total_tasks: int,
    duration_seconds: int,
    *,
    summary: str = "",
    builder: Optional[ProgressCardBuilder] = None,
) -> Dict[str, Any]:
    """Build a workflow completed notification card.

    Args:
        workflow_id: Workflow identifier
        batches_completed: Number of batches completed
        total_tasks: Total tasks completed
        duration_seconds: Total workflow duration
        summary: Optional summary text
        builder: Optional card builder instance

    Returns:
        Complete card payload
    """
    builder = builder or ProgressCardBuilder()

    fields = [
        ("工作流", workflow_id[:12]),
        ("批次数", str(batches_completed)),
        ("任务数", str(total_tasks)),
        ("总耗时", _format_duration(duration_seconds)),
    ]

    elements = [builder.build_fields(fields)]

    if summary:
        elements.append(builder.build_divider())
        elements.append(builder.build_text_element(f"**执行摘要**\n{summary}"))

    return builder.build_card(
        EventType.WORKFLOW_COMPLETED,
        "工作流执行完成",
        elements,
        note="所有任务已完成，验证通过",
    )
