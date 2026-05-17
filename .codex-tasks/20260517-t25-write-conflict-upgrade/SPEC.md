# T25 Write Conflict Upgrade

## Goal
Upgrade same-source-file leaf task write conflicts from
`W_SHARED_PATH_NO_DEPENDENCY` warnings to `E_WRITE_CONFLICT` errors.

## Scope
- Modify `src/cccc/ralph/validation_rules/structural.py`.
- Add `tests/test_write_conflict_upgrade.py`.

## Acceptance Criteria
- Two `role: leaf` tasks claiming the same source file emit `E_WRITE_CONFLICT`.
- Integration role overlap emits neither `E_WRITE_CONFLICT` nor
  `W_SHARED_PATH_NO_DEPENDENCY`.
- `suppress_instances` for `E_WRITE_CONFLICT` downgrades the error.
