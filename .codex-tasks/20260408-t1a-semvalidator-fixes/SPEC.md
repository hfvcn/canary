# T1a Semvalidator Fixes

Implement `plans/phase4-remediation.yaml` task `T1a-semvalidator-fixes`.

Scope:
- `src/cccc/ralph/semantic_validator.py`
- `src/cccc/ralph/models.py`
- minimal test updates required by the task acceptance criteria

Validation:
- signature check from the plan
- scope-direction check from the plan
- dead-field removal check from the plan
- `python -m pytest tests/test_ralph_semantic.py -v --tb=short -x`
