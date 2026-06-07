"""Workflow assignment, admission, and agent start controller facade."""

from __future__ import annotations

from typing import Any

from .assignment_batches import AssignmentBatchMixin
from .assignment_completion import AssignmentCompletionMixin
from .assignment_constants import (
    EXTERNAL_PRESSURE_REASON,
    ORCHESTRATOR_SERVICE_ACTOR,
    SINGLE_WRITER_REASON,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_DEFERRED,
    TASK_STATUS_PENDING,
    TASK_STATUS_RUNNING,
)
from .assignment_control_plane import AssignmentControlPlaneMixin
from .assignment_deferrals import AssignmentDeferralMixin
from .assignment_fallbacks import AssignmentFallbackMixin
from .assignment_actor_registration import ActorAddResult, AssignmentActorRegistrationMixin
from .assignment_startup import AssignmentStartContext, AssignmentStartupMixin


class AssignmentController(
    AssignmentBatchMixin,
    AssignmentFallbackMixin,
    AssignmentCompletionMixin,
    AssignmentDeferralMixin,
    AssignmentActorRegistrationMixin,
    AssignmentStartupMixin,
    AssignmentControlPlaneMixin,
):
    """Coordinates Ralph batch assignments and agent startup."""

    def __init__(self, owner: Any):
        self._owner = owner


__all__ = [
    "ActorAddResult",
    "AssignmentController",
    "AssignmentStartContext",
    "EXTERNAL_PRESSURE_REASON",
    "ORCHESTRATOR_SERVICE_ACTOR",
    "SINGLE_WRITER_REASON",
    "TASK_STATUS_COMPLETED",
    "TASK_STATUS_DEFERRED",
    "TASK_STATUS_PENDING",
    "TASK_STATUS_RUNNING",
]
