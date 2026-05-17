# T5 Security Recipe Library

## Goal

Execute T5 from `plans/fix-v38-all-issues.yaml`: add a Ralph security recipe library, expose a three-gate hint rule, register it in structural validation, and cover gate behavior with tests.

## Scope

- `src/cccc/ralph/security_recipes.py`
- `src/cccc/ralph/validation_rules/security.py`
- `src/cccc/ralph/models.py`
- `src/cccc/ralph/validation_rules/__init__.py`
- `src/cccc/ralph/validator.py`
- `tests/test_security_recipes.py`

