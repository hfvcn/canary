# T2 (RO-109): Upgrade SSRF encoding matrix severity

## Goal

Update `src/cccc/ralph/security_recipes.py` so SSRF `url_input` recipe issues distinguish between zero encoding coverage and partial encoding coverage, and expose missing matrix entries in issue evidence.

## Scope

- Update `src/cccc/ralph/security_recipes.py`
- Update `tests/test_security_recipes.py`
- Run `python -m pytest tests/test_security_recipes.py -v -k "encoding"`

## Acceptance

1. `url_input` emits `warning` when no hostname encoding matrix entry appears in verification checks.
2. `url_input` emits `hint` when at least one encoding matrix entry appears but coverage remains incomplete.
3. `url_input` issue evidence includes `missing_encodings`.
4. Targeted encoding pytest cases pass.
