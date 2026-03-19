"""
Scheduler - Task dependency analysis and ready-batch computation.

Provides dependency graph management and computes batches of tasks
that can be executed in parallel based on their dependencies.
"""

from .dep_graph import (
    TaskStatus,
    TaskNode,
    DependencyGraph,
    CycleDetectedError,
)
from .ready_batch import (
    PriorityStrategy,
    BatchSuggestion,
    compute_ready_batch,
    send_batch_suggestion,
)
from .config import SchedulerConfig

__all__ = [
    # dep_graph
    "TaskStatus",
    "TaskNode",
    "DependencyGraph",
    "CycleDetectedError",
    # ready_batch
    "PriorityStrategy",
    "BatchSuggestion",
    "compute_ready_batch",
    "send_batch_suggestion",
    # config
    "SchedulerConfig",
]
