# T2 Aegis Intent Helper

## Goal

Implement AD-2 from `plan.yaml`: add Aegis intent helper functions, add an empty discipline validation skeleton, register it in the validator, and cover helper behavior with focused tests.

## Scope

- `src/cccc/ralph/aegis.py`
- `src/cccc/ralph/validation_rules/discipline.py`
- `src/cccc/ralph/validation_rules/__init__.py`
- `src/cccc/ralph/validator.py`
- `tests/ralph/test_aegis_intent.py`

## Validation

- `python -m pytest tests/ralph/test_aegis_intent.py -v`
- `python -m pytest tests/ralph/test_ralph_standalone.py -v`
