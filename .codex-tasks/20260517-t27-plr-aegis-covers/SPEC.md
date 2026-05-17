# T27 PLR Aegis Covers

## Goal

Implement PLR-1 and PLR-2:

- Verify the Aegis placeholder-content rule ignores text inside triple-backtick and inline-backtick code sections.
- Auto-fill `covers.paths` from covered tasks' `claimed_paths` when `covers.tasks` exists and `covers.paths` is empty.
- Change `W_COVERS_NOT_EXERCISED` to a hint when auto-expanded paths are available.

## Validation

```bash
python -m pytest tests/test_covers_auto_expand.py tests/test_aegis_discipline_rules.py -k placeholder -v
```

