# T18 FL-6 Flow Step-4 Current Session Changes

## Goal

Modify `_check_improvement_register()` in `flow_improvement_check.py` so step-4 distinguishes current-session additions from pre-existing tracker additions.

## Acceptance Criteria

1. Tracker with only pre-existing additions and no current session marker fails step-4.
2. Tracker with current version marker passes step-4.
3. Existing flow behavior is preserved when `state.version` is set.

## Validation

Run:

```bash
python -m pytest tests/test_flow_improvement_check.py -v
```
