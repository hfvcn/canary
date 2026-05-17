# T6 AD-2 Discipline Rule Infrastructure

## Goal

Implement intent inference helpers and wire `discipline.py` validation rules into the existing Ralph validator and agent rule registry.

## Scope

- Update `src/cccc/ralph/aegis.py` helpers only as needed.
- Match `discipline.py` to the existing validation rule pattern used by structural and coverage rules.
- Re-export discipline rules from `validation_rules`.
- Ensure validator structural issue collection invokes discipline rules.
- Register discipline docs and versions in the agent.

## Validation

```bash
python -m pytest tests/test_aegis_discipline_infra.py -v
```
