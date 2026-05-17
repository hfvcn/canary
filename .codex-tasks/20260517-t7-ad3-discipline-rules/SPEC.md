# T7 AD-3 Discipline Rules

## Goal

Add or verify the first five high-signal Aegis discipline rules in
`src/cccc/ralph/validation_rules/discipline.py`.

## Scope

- `E_AEGIS_PLACEHOLDER_CONTENT`
- `E_AEGIS_RETIREMENT_TRACK_MISSING`
- `W_AEGIS_FIX_NO_REPAIR_TRACK`
- `W_AEGIS_TDD_NO_TEST_PATH`
- `W_AEGIS_COMPLEX_MISSING_BASELINE`

## Validation

```bash
python -m pytest tests/test_aegis_discipline_rules.py -v
```
