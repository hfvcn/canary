# v62 Defect Fixes

## Goal

Fix four verified defects on the main path:

1. DG-3/DG-4 `plan_scope` blindness in `coverage.py`
2. DG-3 self-violation in `workflow_evaluation_io.py`
3. M2-C heading rename bypass in `workflow_evaluation.py`
4. M2-B pool-path audit gap in `assignment_batches.py`

## Scope

- Modify only the source files named by the defects.
- Update only the relevant tests that prove the bypasses are closed.
- Keep unrelated behavior unchanged.

## Validation

Run:

```bash
python -m pytest tests/ralph/test_observable_fallback.py tests/ralph/test_guard_ordering.py tests/test_workflow_evaluation_substantive.py tests/test_model_selection_main_path.py tests/test_v62_batch_integration.py tests/test_foreman_workflow.py -v
```
