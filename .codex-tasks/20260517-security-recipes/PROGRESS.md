# Progress

## 2026-05-17

- Read T5 from `plans/fix-v38-all-issues.yaml`.
- Located `CriticalFlow`, `ValidationIssue`, `validation_rules`, and `_collect_structural_issues`.
- fast-context semantic search was attempted first per repo policy but was cancelled by the tool/user path; local `rg`/file reads continued with visible failure.
- Added `surface_type` and `temporal_pattern` metadata to `CriticalFlow`.
- Added `security_recipes.py`, the validation rule wrapper, validator wiring, and focused gate tests.
- Verification passed:
  - `python -m pytest tests/test_security_recipes.py -v`
  - `python -m pytest tests/test_module_split.py tests/test_completeness_rules.py -q`
