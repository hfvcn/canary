# T16 E2E Compile Check

## Goal

Add `W_E2E_MISSING_COMPILE_CHECK` to Ralph structural validation so e2e,
integration, and api verification tasks require at least one compile/import
check in `verification.checks`.

## Scope

- `src/cccc/ralph/validation_rules/structural.py`
- `src/cccc/ralph/validation_rules/__init__.py`
- `src/cccc/ralph/validator.py`
- `tests/test_e2e_compile_check.py`

## Validation

`python -m pytest tests/test_e2e_compile_check.py -v`
