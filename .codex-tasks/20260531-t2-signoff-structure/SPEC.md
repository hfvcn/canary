# T2 Signoff Structure Validation

## Goal

Enhance `src/cccc/ralph/validation_rules/security_signoff.py` so structured
sign-off checks must reference the sign-off artifact path, with grep commands
excluded from structured-field detection.

## Scope

- Update sign-off structure validation helpers.
- Add tests in `tests/ralph/test_signoff_structure.py`.
- Validate with `python -m pytest tests/ralph/test_signoff_structure.py -v`.

