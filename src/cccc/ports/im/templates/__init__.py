"""IM message templates.

This module provides message templates for various IM platforms,
with a focus on rich card messages for progress reporting.
"""

from .progress_card import (
    ProgressCardBuilder,
    EventType,
    ProgressStatus,
    build_batch_started_card,
    build_task_completed_card,
    build_batch_completed_card,
    build_task_failed_card,
    build_intervention_card,
    build_workflow_completed_card,
)

__all__ = [
    "ProgressCardBuilder",
    "EventType",
    "ProgressStatus",
    "build_batch_started_card",
    "build_task_completed_card",
    "build_batch_completed_card",
    "build_task_failed_card",
    "build_intervention_card",
    "build_workflow_completed_card",
]
