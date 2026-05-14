# SPEC: fix-v5-v29-ro74-75 T5

## Goal

Implement verify gate agent-mode `mock_tests` execution in Ralph verification, ensure adversarial mock test details do not leak to worker prompts or retry `last_error`, and cover the behavior with focused tests.

## Scope

- `src/cccc/daemon/foreman/ralph_service.py`
- `src/cccc/daemon/foreman/prompt_builder.py`
- `tests/test_mock_tests_execution.py`

## Validation

Run `python -m pytest tests/test_mock_tests_execution.py -v`.
