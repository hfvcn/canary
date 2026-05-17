# RO-98 Verification Infra Error

## Goal

Distinguish worker task quality failures from verifier infrastructure failures in the verification gate.

## Scope

- Update `src/cccc/daemon/foreman/verification_gate.py` around `process_completed_event`.
- Update `src/cccc/contracts/v1/ralph_ipc.py` if the verifier status contract needs the new status.
- Preserve worker retry accounting for task quality failures while infra failures retry only the verifier.
- Escalate to foreman decision after verifier infra retries are exhausted.

## Validation

`python -m pytest tests/test_verification_infra_error.py -v`
