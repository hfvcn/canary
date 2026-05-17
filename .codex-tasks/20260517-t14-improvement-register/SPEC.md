# T14 Improvement Register Check

## Goal

Execute `T14` from `plans/fix-v38-all-issues.yaml`: flow improvement-register checks must distinguish current-session tracker additions from pre-existing uncommitted tracker changes.

## Scope

- Update the active `_check_improvement_register()` implementation used by E2E flow step checks.
- Add `tests/test_flow_improvement_check.py` with focused unit coverage.
- Do not revert unrelated dirty worktree changes.

## Acceptance

- Diff additions containing the current version marker pass.
- Diff additions without the current version marker fail.
- No tracker diff fails.

