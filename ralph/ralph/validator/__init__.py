"""
Validator - Verification layer for Ralph daemon.

Provides validators for:
- Build/Test/Lint execution (required)
- Task file state checking (recommended)
- Failure feedback generation

Validators observe git commits, execute verification commands,
and send results to CCCC Daemon via IPC.
"""

from .config import ValidatorConfig, CommandConfig
from .build_test import (
    BuildTestValidator,
    BuildTestResult,
    run_build,
    run_tests,
    run_lint,
)
from .task_file import (
    TaskStateChecker,
    TaskStateResult,
    TaskState,
    check_task_state,
)
from .feedback import (
    FeedbackGenerator,
    generate_retry_message,
    generate_escalation_message,
)

__all__ = [
    # config
    "ValidatorConfig",
    "CommandConfig",
    # build_test
    "BuildTestValidator",
    "BuildTestResult",
    "run_build",
    "run_tests",
    "run_lint",
    # task_file
    "TaskStateChecker",
    "TaskStateResult",
    "TaskState",
    "check_task_state",
    # feedback
    "FeedbackGenerator",
    "generate_retry_message",
    "generate_escalation_message",
]
