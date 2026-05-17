# T9 Aegis Discipline Rules

## Goal

Implement the first five high-signal Aegis discipline rules from `plans/fix-v38-all-issues.yaml` T9 in `src/cccc/ralph/validation_rules/discipline.py`, with focused tests in `tests/test_aegis_discipline_rules.py`.

## Scope

- Verify or adjust existing content-gap detection.
- Add/repair retirement, repair, TDD path, and baseline checks.
- Register all checks through the discipline rule registry used by validation.
- Add tests for each rule without using the sensitive content-gap token in task fixture outcome fields.

## Validation

- `python -m pytest tests/test_aegis_discipline_rules.py -v`
- Run nearby infra tests if changes touch shared behavior.
