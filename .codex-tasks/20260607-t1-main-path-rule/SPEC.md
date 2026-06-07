# T1 Main-Path Verification Rule

## Goal

Implement `plan.yaml` task `T1` exactly as specified: add validation rule
`W_VERIFICATION_NO_MAIN_PATH_COMMAND` so runtime-behavior tasks are warned when
their verification contains only pytest or other shallow commands and no
main-path CLI/log assertion.

## Scope

- `src/cccc/ralph/validation_rules/coverage.py`
- `src/cccc/ralph/validation_rules/__init__.py`
- `src/cccc/ralph/validator.py`
- `tests/ralph/test_verification_main_path.py`

## Validation

- `python -m pytest tests/ralph/test_verification_main_path.py -v`
- `python -m pytest tests/ralph/test_integration_call_evidence.py tests/test_module_split.py -v`
- `ralph validate plan.yaml --no-agent`
