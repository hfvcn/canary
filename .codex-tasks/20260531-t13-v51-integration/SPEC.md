# T13 v51 Validate Integration

## Objective

Implement `tests/ralph/test_v51_integration.py` to verify v51 validation rules through the real `validate()` entry point.

## Scope

- Add v51 integration coverage for dirty, security, entrypoint, clean, and rule registration scenarios.
- If an expected v51 dependency is absent from current source, expose and fix the root implementation gap instead of weakening the test.

## Validation

`python -m pytest tests/ralph/test_v51_integration.py -v`
