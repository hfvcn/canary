# RO-68 verification cleanup

## Goal

Implement T4 from `plans/fix-v5-v27-remaining.yaml`: before worker verification retries, remove configured side-effect artifacts inside each task's claimed paths.

## Scope

- Add `cleanup_patterns` to IPC and plan verification schemas.
- Preserve propagation through `TaskSpec.to_task_ref()`.
- Add cleanup in `ralph_service.py` without overwriting existing T3 challenge verification changes.
- Add focused tests in `tests/test_verification_cleanup.py`.

## Validation

Run:

```bash
python -m pytest tests/test_verification_cleanup.py -v
```
