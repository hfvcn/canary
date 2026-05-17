# RO-81 Cross-Task IO Contracts Multi-Upstream Fix

## Goal

Execute T2 from `plans/v33-ux-and-ro-fixes.yaml`.

`_check_cross_task_io_contracts()` must compare a task's expected input keys
against the union of all upstream dependencies' expected output keys, not
against each dependency individually.

## Scope

- `src/cccc/ralph/validation_rules/contracts.py`
- `tests/ralph/test_contract_schema_validation.py`

## Acceptance Criteria

- No `W_CROSS_TASK_IO_MISMATCH` when multiple upstream tasks collectively
  provide every expected input key.
- Emit one `W_CROSS_TASK_IO_MISMATCH` when keys are missing across all upstream
  outputs.
- Preserve single-upstream behavior.
- Warning evidence includes `missing_keys` and `consumer_task`.

## Verification

```bash
python -m pytest tests/ralph/test_contract_schema_validation.py -v -k 'cross_task_io'
```
