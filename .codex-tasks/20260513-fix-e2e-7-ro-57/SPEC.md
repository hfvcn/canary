# RO-57 / T1

## Goal

Fix resubmit behavior for `cccc workflow submit` so any submitted task id that
already exists in the workflow engine is rejected with a clear instruction to
use `cccc workflow retry`.

## Scope

- Update `src/cccc/daemon/foreman/assignment_batches.py`.
- Update `src/cccc/daemon/foreman/workflow_id_resolution.py`.
- Update conflicting reuse tests in `tests/test_resubmit_workflow_id.py`.
- Add `tests/test_resubmit_reject.py`.
- Verify with `python -m pytest tests/test_resubmit_reject.py -v`.

## Acceptance Criteria

- Existing task ids are rejected before new workflow ids or batches are created.
- All-new task ids still register and submit normally.
- Mixed existing and new task ids are rejected.
- `register_and_suggest_inner()` applies the same existing-task guard.
