# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- Add advisory mtime-lag detection for step-5 Codex JSON outputs.
- Integrate the advisory details into `_check_execute_and_verify`.
- Add focused tests for normal and suspicious overwrite cases.

## Non-Goals

- Do not change existing blocking behavior of Codex JSON validation.
- Do not modify unrelated tests or flow steps.

## Constraints

- Advisory only: suspicious lag must not fail the check.
- Keep the helper focused and simple.
- Preserve existing test behavior.

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: Python
- **Test framework**: pytest

## Deliverables

- Updated `src/cccc/ralph/flow_engine.py`
- Updated `tests/ralph/test_flow_engine.py`

## Done-When

- [ ] Constant, helper, and step-5 integration are implemented.
- [ ] New tests cover normal and overwrite advisory cases.
- [ ] Targeted pytest passes.

## Final Validation Command

```bash
pytest tests/ralph/test_flow_engine.py
```
