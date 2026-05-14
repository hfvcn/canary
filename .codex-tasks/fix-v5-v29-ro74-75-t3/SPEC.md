# fix-v5-v29-ro74-75 T3

## Goal

Add structural validation that warns when one task addresses issues from
different address domains and hints when one issue is addressed by multiple
tasks.

## Scope

- `src/cccc/ralph/validation_rules/coverage.py`
- `src/cccc/ralph/validation_rules/__init__.py`
- `src/cccc/ralph/validator.py`
- `tests/test_task_addresses_disjoint.py`

## Validation

`python -m pytest tests/test_task_addresses_disjoint.py -v`
