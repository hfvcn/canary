from __future__ import annotations

import importlib
import inspect


FUNCTION_SIGNATURES = {
    "complete_task": [
        "group_id",
        "task_id",
        "agent_id",
        "changed_files",
        "evidence",
        "workflow_id",
        "project_root",
        "daemon_request_fn",
        "assignment_id",
        "actor_run_id",
        "override_stale_digest",
        "force_complete",
        "attempt_id",
    ],
    "fail_task": [
        "group_id",
        "task_id",
        "agent_id",
        "message",
        "workflow_id",
        "project_root",
        "daemon_request_fn",
        "assignment_id",
        "actor_run_id",
    ],
    "retry_task": [
        "group_id",
        "task_id",
        "workflow_id",
        "project_root",
        "daemon_request_fn",
        "assign_agent_id",
    ],
    "block_task": [
        "group_id",
        "task_id",
        "reason",
        "workflow_id",
        "project_root",
        "daemon_request_fn",
    ],
    "start_task": [
        "group_id",
        "task_id",
        "agent_id",
        "workflow_id",
        "project_root",
        "daemon_request_fn",
    ],
    "verify_task": [
        "group_id",
        "task_id",
        "workflow_id",
        "project_root",
        "daemon_request_fn",
    ],
}


def test_workflow_task_ops_imports() -> None:
    module = importlib.import_module("cccc.daemon.ops.workflow_task_ops")
    assert module is not None


def test_workflow_task_ops_exports_callable_functions() -> None:
    module = importlib.import_module("cccc.daemon.ops.workflow_task_ops")

    for name, expected_params in FUNCTION_SIGNATURES.items():
        fn = getattr(module, name, None)
        assert fn is not None, f"missing function: {name}"
        assert callable(fn), f"not callable: {name}"
        assert list(inspect.signature(fn).parameters) == expected_params
