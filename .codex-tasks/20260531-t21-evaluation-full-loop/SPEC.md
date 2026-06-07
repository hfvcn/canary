# Task Specification

## Task Shape

- **Shape**: single-full

## Goals

- Implement plan.yaml T21 by adding the AF-M6 evaluation loop integration test for trace, scoring, candidate generation, and promotion.

## Non-Goals

- Do not change production behavior unless the new integration test exposes a real failure.

## Constraints

- Follow existing pytest style.
- Keep failures visible; do not add silent fallbacks or mock success paths.
- Final validation must use the user-specified command.

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: Python
- **Test framework**: pytest

## Deliverables

- `tests/test_evaluation_full_loop.py`

## Done-When

- [ ] The new integration test file exists.
- [ ] `python -m pytest tests/test_evaluation_full_loop.py -v` passes.

## Final Validation Command

```bash
python -m pytest tests/test_evaluation_full_loop.py -v
```
