# T19 FL-10 Plan State Writeback

## Goal

When a workflow task completes successfully, update the registered `plan.yaml`
`state.tasks[task_id]` value to `completed` without changing unrelated plan
content.

## Scope

- Add a focused plan state write helper in `src/cccc/ralph/plan_io.py`.
- Call the helper from the task completion success path in
  `src/cccc/daemon/foreman/workflow_orchestrator.py`.
- Add regression tests for successful writeback and write failure tolerance.

## Validation

Run `python -m pytest tests/test_plan_state_writeback.py -v`.
