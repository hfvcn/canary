# T2 Integration Rules

## Goal

Implement T2 from `plan.yaml`: verify registration of three new validation rules, add integration coverage through `validate()`, run requested tests, and fix any failures.

## Scope

- `src/cccc/ralph/validation_rules/__init__.py`
- `src/cccc/ralph/validator.py`
- `tests/test_integration_call_evidence.py`
- `tests/test_forbidden_flow_field.py`
- `tests/test_status_code_drift.py`

## Validation

1. `python -m pytest tests/test_integration_call_evidence.py tests/test_forbidden_flow_field.py tests/test_status_code_drift.py -v`
2. `python -m pytest tests/ralph/ -q`
