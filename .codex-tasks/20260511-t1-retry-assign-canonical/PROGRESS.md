# Progress

- Started 2026-05-11.
- Loaded task requirements from `plans/fix-v5-v22-new.yaml` T1.
- Confirmed current retry call chain: CLI parser -> `cmd_workflow_retry()` -> `handle_ralph_task_retry()` -> `workflow_task_ops.retry_task()` -> `WorkflowOrchestrator.retry_task()`.
- Confirmed bug root cause: retry clears tracked task fields, but `_auto_dispatch_ready_tasks()` reads canonical `assignment_map` from active workflow data.
- Confirmed engine persistence API exists: `WorkflowEngine.set_workflow_meta(..., assignment_map=...)`.
- Implemented `--assign` on `cccc workflow retry` and threaded `assign_agent_id` through CLI, IPC handler, task ops, and orchestrator.
- Added orchestrator helpers to reset retry shadow task state and persist canonical retry assignment into both active workflow data and engine workflow metadata.
- Added `tests/test_retry_assign.py` covering assignment-map overwrite, no-assign stability, and `assigned_to` return payload.
- Verification passed:
  - `python -m pytest tests/test_retry_assign.py tests/test_retry_running_task.py -v`
  - `python -m pytest tests/test_workflow_task_ops.py tests/test_canonical_task_ops_integration.py -q`
