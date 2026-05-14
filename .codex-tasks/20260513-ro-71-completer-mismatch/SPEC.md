# RO-71 Completer Mismatch Verification

## Goal

Implement T5 from `plans/fix-v5-v27-remaining.yaml`: when a `force_complete`
completion has a completer mismatch, verification must be enforced instead of
skipped.

## Scope

- Update `src/cccc/daemon/foreman/verification_gate.py`.
- Add focused tests in `tests/test_completer_mismatch_verification.py`.
- Verify with `python -m pytest tests/test_completer_mismatch_verification.py -v`.

## Constraints

- Compute mismatch directly in `process_completed_event()` because RUNNING
  state completions do not go through auto-start propagation.
- Do not add fallback behavior or silent degradation.
