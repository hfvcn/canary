# T23 Guide Generator Coverage

## Goal

Verify and enhance `src/cccc/ralph/guide_generator.py` so `ralph guide`
outputs a comprehensive reference for Plan schema fields, validation rule codes,
and CLI commands.

## Scope

- `src/cccc/ralph/guide_generator.py`
- `tests/test_guide_generator_coverage.py`

## Validation

`python -m pytest tests/test_guide_generator_coverage.py -v`
