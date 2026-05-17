# Release Agent On Failure

## Goal

Fix RO-95: workflow task failure and deferral must release the assigned agent from the foreman pool.

## Scope

- Update failure handling in `workflow_orchestrator.py`.
- Update deferral handling in `assignment_deferrals.py`.
- Add `tests/test_release_on_fail.py`.

## Acceptance

- `on_task_failed()` clears the task agent from `_active_assignments`.
- Deferred tasks clear affected agent assignments.
- Completion release behavior remains intact.

