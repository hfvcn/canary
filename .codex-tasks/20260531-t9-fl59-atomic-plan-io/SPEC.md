# T9 FL-59 Atomic Plan IO

## Goal

Implement atomic YAML state writes in `src/cccc/ralph/plan_io.py` so plan state updates cannot corrupt `plan.yaml` on invalid surgical edits or interrupted writes.

## Scope

- Read T9 in `plan.yaml` as the source of truth.
- Update `save_plan_state` to write to a temporary file in the same directory, validate with `yaml.safe_load`, then atomically replace the original.
- Validate `_insert_completed_task_id` output and fall back to parse-modify-dump if surgical insertion creates invalid YAML.
- Add focused tests in `tests/ralph/test_plan_io_atomic.py`.

## Validation

- Run the focused new test file with a 60 second timeout.
