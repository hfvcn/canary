# Progress

- Identified required code paths:
  - `validate_semantic` return contract
  - `_compute_task_scope` downstream closure semantics
  - `ValidationReport.consistency_reports` dead-field removal
- Affected direct consumers:
  - `src/cccc/ralph/validator.py`
  - `tests/test_ralph_semantic.py`
- Completed implementation:
  - `validate_semantic` now returns `(issues, suggested_deps, effective_tasks)`
  - `validate_with_project` fingerprints the effective task list, not the raw plan
  - downstream scope now uses transitive dependents, with inline helper + TODO
  - `ValidationReport.consistency_reports` removed
- Validation:
  - plan signature check passed
  - plan scope-direction check passed
  - dead-field removal check passed
  - `python -m pytest tests/test_ralph_semantic.py -v --tb=short -x` passed
