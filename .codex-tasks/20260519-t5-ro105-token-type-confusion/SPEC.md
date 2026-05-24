# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- Execute `T5` from `plan.yaml` to add the `token_type_confusion` security recipe.
- Extend deterministic security check generation so auth flows with multiple token types emit a token-type-confusion behavior check.
- Add focused regression coverage in `tests/test_ralph_verification.py`.

## Non-Goals

- Do not change unrelated security recipe behavior.
- Do not add fallback or heuristic-only suppression behavior outside the T5 scope.

## Constraints

- Keep changes limited to `src/cccc/ralph/security_recipes.py`, `src/cccc/ralph/security_check_generator.py`, and `tests/test_ralph_verification.py`.
- Preserve unrelated uncommitted edits, especially in `tests/test_ralph_verification.py`.
- Final verification command is the T5 command from `plan.yaml`.

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: Python
- **Test framework**: `pytest`

## Deliverables

- `token_type_confusion` recipe metadata and matcher wiring.
- Generator support for token-type-confusion category and emitted pytest check.
- Two targeted regression tests for positive and negative generation cases.

## Done-When

- [ ] Auth critical flows with multi-token-type context generate a token-type-confusion check.
- [ ] Flows without auth context do not generate the new check.
- [ ] `python -m pytest tests/test_ralph_verification.py -v -k 'token_type'` passes.

## Final Validation Command

```bash
python -m pytest tests/test_ralph_verification.py -v -k 'token_type'
```
