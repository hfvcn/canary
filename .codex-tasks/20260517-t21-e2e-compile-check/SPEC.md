# T21: E2E Compile Check Validation

## Goal

Add validation coverage so `api`, `e2e`, and `integration` verification levels require a structured compile/import check.

## Acceptance Criteria

- An `e2e` task without a compile/import check emits `W_E2E_MISSING_COMPILE_CHECK`.
- An `e2e` task with a compile/import check does not emit the warning.
- A `unit` task without a compile/import check does not emit the warning.
- `python -m pytest tests/test_e2e_compile_check.py -v` passes.

