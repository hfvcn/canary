# T8 Aegis Discipline Infrastructure

## Goal

Complete AD-2 from `plans/fix-v38-all-issues.yaml`: keep `effective_intent()`
usable for `TaskSpec` and `TaskRef`, expose an empty discipline rule
collector, register it, and cover the intent inference behavior.

## Scope

- `src/cccc/ralph/aegis.py`
- `src/cccc/ralph/validation_rules/discipline.py`
- `src/cccc/ralph/validation_rules/__init__.py`
- `src/cccc/ralph/validator.py`
- `tests/test_aegis_discipline_infra.py`

## Validation

- `python -m pytest tests/test_aegis_discipline_infra.py -v`
