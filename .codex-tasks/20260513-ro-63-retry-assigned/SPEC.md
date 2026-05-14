# RO-63 Retry Assigned

## Goal

Implement T2 from `plans/fix-v5-v27-remaining.yaml`: allow `retry_after_verification()` to accept `ASSIGNED` tasks and reset them to `READY` while clearing assignment fields.

## Scope

- Update `src/cccc/kernel/workflow_state_engine.py`.
- Add `tests/test_retry_assigned.py`.
- Verify with `python -m pytest tests/test_retry_assigned.py -v`.

## Acceptance

- `ASSIGNED` retry succeeds and becomes `READY`.
- `VERIFYING` and `FAILED` retry still succeed.
- `RUNNING` and `COMPLETED` retry remain rejected.
- Ledger records `KIND_RETRY_REQUESTED`.
