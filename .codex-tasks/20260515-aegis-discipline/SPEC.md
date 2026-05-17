# T1 AegisDiscipline Schema

## Goal

Implement AD-1 from `plan.yaml`: add Aegis discipline schema models to Ralph task specs and pass the data through to IPC `TaskRef`.

## Scope

- `src/cccc/ralph/models.py`
- `src/cccc/contracts/v1/ralph_ipc.py`
- `tests/ralph/test_aegis_discipline.py`

## Validation

- `python -m pytest tests/ralph/test_aegis_discipline.py -v`
- `python -m pytest tests/ralph/test_contract_schema_validation.py -v`
