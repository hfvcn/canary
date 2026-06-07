# T7 Discipline Rule Registration Completeness

## Goal

Implement RV-12 by adding a meta-validation check that scans discipline rule modules for registerable rule functions and reports any unregistered ones.

## Scope

- `src/cccc/ralph/validation_rules/discipline.py`
- `src/cccc/ralph/validation_rules/discipline_registration.py`
- `src/cccc/ralph/validation_rules/__init__.py`
- `src/cccc/ralph/validator.py`
- `tests/test_aegis_discipline_rules.py`

## Validation

- `python -m pytest tests/test_aegis_discipline_rules.py -v`
