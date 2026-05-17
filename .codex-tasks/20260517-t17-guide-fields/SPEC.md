# T17 Guide Field Descriptions And Coverage

## Goal

Implement FL-4 and UX-5:

- Add Pydantic `Field(description=...)` metadata for key Plan fields:
  `verification_mode`, `aegis`, `mock_tests`, `provides`, `consumes`.
- Enhance `guide_generator.py` so `ralph guide` emits a complete capability guide
  from Pydantic schema, validation rules, and CLI help.
- Verify with:
  `python -m pytest tests/test_guide_description.py tests/test_guide_generator_coverage.py -v`

## Boundaries

- Keep changes scoped to schema metadata, guide generation, and directly relevant tests if needed.
- Do not introduce silent fallback behavior or fake success paths.
- Let validation failures surface clearly.
