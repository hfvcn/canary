# Progress

## Recovery

- Active task: complete.
- Validation target: `python -m pytest tests/test_security_recipes.py -v -k "encoding"`
- Notes: user requirement needs a behavior change in `url_input` matching, because the current recipe suppresses the issue when any single hostname encoding entry appears in verification text.

## Result

- `url_input` now distinguishes named matrix coverage/full entry coverage from partial entry coverage through `_missing_encoding_entries()` and `_url_input_is_covered()`.
- `_build_issue()` now derives severity through `_resolve_recipe_severity()`, producing `warning` only when zero hostname encoding entries are present.
- `_issue_evidence()` now emits `missing_encodings` for `url_input`.
- `python -m pytest tests/test_security_recipes.py -v -k "encoding"` passed with 2 tests.
