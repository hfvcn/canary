# T1 Signoff Non Suppressible

## Goal

Add `W_SIGNOFF_STRUCTURE_WEAK` to the security-flow non-suppressible warning set and cover the behavior with focused tests.

## Scope

- Update `src/cccc/ralph/validation_rules/security.py`.
- Add `tests/ralph/test_signoff_non_suppressible.py`.
- Verify with `python -m pytest tests/ralph/test_signoff_non_suppressible.py -v`.

