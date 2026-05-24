# FL-27 Shallow Check Gate

## Goal

Execute `T5 (FL-27)`: add a shallow verification rejection gate so import/compile-only verification checks fail completion when no behavioral verification is present.

## Scope

- `src/cccc/daemon/foreman/verification_gate.py`
- `tests/test_verification_gate.py`

## Validation

`python -m pytest tests/test_verification_gate.py -v -k "shallow_check"`
