# T3 RV-34 Integration Tests

## Goal

Add integration coverage for the RV-34 signoff validation enhancements through
`cccc.ralph.validator.validate`.

## Scope

- Add `tests/ralph/test_rv34_integration.py`.
- Cover security/auth signoff structure behavior, suppression behavior, and
  non-security flow behavior.
- Do not change validator behavior.

## Validation

Run:

```bash
python -m pytest tests/ralph/test_rv34_integration.py -v
```
