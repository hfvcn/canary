# T4 Input Robustness Gate

## Goal

Execute `T4` from `plans/fix-v38-all-issues.yaml`: enhance the daemon verification gate so input-related critical flows surface a non-blocking warning when verification lacks NUL/control-character robustness coverage.

## Scope

- `src/cccc/daemon/foreman/verification_gate.py`
- `tests/test_input_robustness_gate.py`

## Validation

`python -m pytest tests/test_input_robustness_gate.py -v`
