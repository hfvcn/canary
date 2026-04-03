# Ralph Block Fixes

## Goal

Fix 4 review-blocking issues plus the workspace index path traversal flag in Ralph-related code, validating after each sequential fix and ending with the required regression suite.

## Scope

- `src/cccc/daemon/foreman/ralph_service.py`
- `src/cccc/ralph/cli.py`
- `src/cccc/ralph/plan_io.py`
- `src/cccc/ralph/filesystem_validator.py`
- `src/cccc/ralph/workspace_index.py`
- Relevant Ralph/foreman tests

## Constraints

- Follow the user-specified order for BLOCK 1..4.
- Run tests after each fix.
- Keep failures explicit; do not add silent fallbacks.
