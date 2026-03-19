"""Foreman module - the sole external coordinator in CCCC.

Foreman is responsible for:
1. Receiving and reviewing Ralph's ready_batch suggestions
2. Evaluating Agent Pool and creating/reusing agents
3. Assigning tasks to appropriate Workers
4. Communicating progress via Feishu

This module exposes the main workflow functions for Foreman operations.
"""

from __future__ import annotations

from .workflow import (
    receive_ready_batch,
    evaluate_agent_pool,
    assign_tasks,
    make_batch_decision,
    ForemanWorkflow,
    BatchEvaluationResult,
)

from .agent_pool import (
    AgentPoolManager,
    AgentEvaluation,
    TaskAssignment,
)

from .progress_report import (
    ProgressReporter,
    ProgressState,
)

__all__ = [
    # Workflow functions
    "receive_ready_batch",
    "evaluate_agent_pool",
    "assign_tasks",
    "make_batch_decision",
    "ForemanWorkflow",
    "BatchEvaluationResult",
    # Agent pool management
    "AgentPoolManager",
    "AgentEvaluation",
    "TaskAssignment",
    # Progress reporting
    "ProgressReporter",
    "ProgressState",
]
