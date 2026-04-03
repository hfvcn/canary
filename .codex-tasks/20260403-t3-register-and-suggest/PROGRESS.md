# Progress

- 2026-04-03: Read T3 plan entry and requested source files.
- 2026-04-03: Identified missing data path: `_resuggest_ready_tasks()` already expects `task_ref`, but `process_batch_suggestion()` only stores assignment metadata for approved tasks.
- 2026-04-03: Added `WorkflowOrchestrator.register_and_suggest()` and centralized task tracking so `_active_workflows[wf]["tasks"][tid]["task_ref"]` is persisted for both ready and deferred tasks.
- 2026-04-03: Added daemon op `ralph_register_and_suggest` and switched `cmd_workflow_submit --plan` to use it while leaving `--tasks` unchanged.
- 2026-04-03: Added regression coverage for phased resuggestion, CLI op selection, and the new daemon handler.
- 2026-04-03: Verified with `python -m pytest tests/test_workflow_e2e_closure.py tests/test_ralph_ipc.py -q --tb=short` -> `53 passed`.
