# T12 Guide Field Descriptions

## Goal
Ensure `ralph guide --output` populates the guide `Description` column from Pydantic `Field()` descriptions on `TaskSpec`.

## Scope
- Verify `TaskSpec` fields already define descriptions in `src/cccc/ralph/models.py`.
- Update `src/cccc/ralph/guide_generator.py` to read field descriptions from `model_fields`.
- Add `tests/test_guide_description.py` covering `verification_mode`, `aegis`, `provides`, and `consumes`.

## Validation
- Run the focused guide description test.
- Run any nearby existing guide-generator tests if present.
