# T22 Verification Infra Error

## Goal

Distinguish verification infrastructure failures from real task verification failures.

## Scope

- Add `infra_error` to the verification outcome contract.
- Keep `infra_error` non-terminal in workflow state.
- Retry verifier infrastructure failures up to two times in `verification_gate.py`.
- Classify RalphService verification infrastructure failures consistently.
- Cover transient infra, normal verification failure, and retry exhaustion.

## Validation

`python -m pytest tests/test_verification_infra_error.py -v`
