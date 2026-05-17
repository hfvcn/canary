# T21 Verification Gate Debug Blocking

## Goal

Move security lint for `debug=True` into the verification decision path before `on_task_completed_fn` runs.

## Scope

- Update `src/cccc/daemon/foreman/verification_gate.py`.
- Add `tests/test_security_lint_blocking.py`.
- Preserve existing behavior for test files and clean source files.

## Acceptance

- Source file containing `debug=True` makes verification fail before task completion.
- Test file containing `debug=True` does not affect verification.
- Source file without `debug=True` passes normally.
- Existing warning recording remains explicit where applicable.
