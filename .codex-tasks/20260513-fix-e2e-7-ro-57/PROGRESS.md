# Progress

## 2026-05-13

- T1 reopened under the newer v27 remaining plan: the target behavior changed
  from reusing an existing workflow id to rejecting any submit containing an
  already-existing task id.
- Current milestone: #2 — implement existing-task rejection guard.
- The earlier `fast-context` lookup was cancelled by the environment; precise
  `rg`/file reads identified the active implementation in
  `assignment_batches.py` and the existing helper in `workflow_id_resolution.py`.
- Implemented the rejection guard through `workflow_id_resolution.py`.
  `process_batch_suggestion()` now rejects external submit attempts containing
  existing task ids, and `register_and_suggest_inner()` raises the same
  `tasks_already_exist` error before creating workflow metadata or registering
  tasks.
- Preserved the valid all-new plan-submit transaction by explicitly allowing
  task ids registered earlier in the same `register_and_suggest_inner()` call
  when its ready suggestion is processed.
- Added `tests/test_resubmit_reject.py` and updated
  `tests/test_resubmit_workflow_id.py` away from workflow-id reuse semantics.
- Validation:
  - `python -m pytest tests/test_resubmit_reject.py -v`: 4 passed.
  - `python -m pytest tests/test_resubmit_workflow_id.py -v`: 8 passed.
  - `python -m py_compile src/cccc/daemon/foreman/assignment_batches.py src/cccc/daemon/foreman/workflow_id_resolution.py tests/test_resubmit_reject.py tests/test_resubmit_workflow_id.py`: passed.
- Current milestone: #4 — completed.

## Prior work

- Started FIX-E2E-7 / RO-57 as a Single Task.
- fast-context search was attempted twice and returned a cancelled tool call.
- Located the divergent paths: `process_batch_suggestion` resolves resubmit ids
  before registration, while `register_and_suggest_inner` registers under the
  submitted workflow id first.
- Added shared workflow id resolution helpers and wired them into both batch
  suggestion processing and `register_and_suggest_inner`.
- Added register path tests for existing workflow reuse, new workflow use, and
  mixed workflow rejection.
- Verification:
  - `tests/test_resubmit_workflow_id.py`: 8 passed.
  - Related subset: 20 passed, 10 skipped.
  - Full `pytest`: timed out at 60 seconds while running the 2695-test suite.
  - `ruff`: unavailable in the environment.
  - `py_compile` on changed Python files: passed.
