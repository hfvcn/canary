# T5 AD-1 AegisDiscipline Infrastructure

## Goal

Add an optional `AegisDiscipline` sub-model to task specifications and pass it through task refs, plan validation, schema output, and guide references without breaking old plans.

## Scope

- `models.py`: add `AegisDiscipline`, add `TaskSpec.aegis`, pass it in `to_task_ref`.
- `ralph_ipc.py`: add dict-based `TaskRef.aegis`.
- `plan_io.py`: include nested strict field validation for `aegis`.
- `cli.py`: ensure Ralph schema output exposes `AegisDiscipline`.
- `guide_generator.py`: include `AegisDiscipline` in model references.

## Validation

Run `python -m pytest tests/test_aegis_discipline_infra.py -v`.
