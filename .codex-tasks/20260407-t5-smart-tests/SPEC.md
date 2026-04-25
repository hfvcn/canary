# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- Implement `T5-smart-tests` from `plans/phase4-deep-integration.yaml`.
- Upgrade `recommend_tests()` to return structured `TestRecommendation`.
- Update `format_semantic_context()` and `_cmd_verify()` for the new contract.
- Preserve the plan's gate rule: only allow `full_suite_recommended=False` when confidence is high and the gate is ready.

## Non-Goals

- No changes outside `src/cccc/ralph/semantic_validator.py`, `src/cccc/ralph/cli.py`, and directly affected tests.

## Constraints

- `TestRecommendation.test_files` must preserve the old file list content.
- `pytest_selector` must be derived from `test_files`.
- `full_suite_recommended` must stay `True` unless both confidence and gate readiness allow selective-only execution.
- Pass the user-provided import, functional, and pytest verification commands.

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: Python 3.9+

## Deliverables

- `src/cccc/ralph/semantic_validator.py`
- `src/cccc/ralph/cli.py`
- `tests/test_ralph_semantic.py`
- `tests/ralph/test_ralph_standalone.py`

## Done-When

- [ ] `recommend_tests()` returns `TestRecommendation`.
- [ ] `format_semantic_context()` consumes `result.test_files`.
- [ ] `_cmd_verify()` serializes `TestRecommendation` into JSON safely.
- [ ] User-provided verification commands pass.
