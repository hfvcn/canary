# Task Specification

## Task Shape

- **Shape**: single-full

## Goals

- Upgrade security lint behavior in `src/cccc/daemon/foreman/verification_gate.py`.
- Make security lint and input robustness findings blocking in challenge mode.
- Keep ralph/agent mode mode-aware behavior as warning-only.
- Add requested security lint patterns and whitelist test files.

## Non-Goals

- Do not refactor unrelated verification gate behavior.
- Do not revert existing working tree changes.

## Constraints

- Preserve existing T2 mode-awareness semantics.
- Do not add silent fallback behavior or fake success paths.
- Run requested pytest target with a 60 second timeout.

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: Python
- **Test framework**: pytest

## Risk Assessment

- [x] Existing dirty worktree — only scoped edits are allowed.
- [x] Blocking behavior may affect tests — verify requested files directly.

## Deliverables

- Updated `verification_gate.py`.
- Passing requested security lint tests.

## Done-When

- [ ] SL-1 challenge-mode security lint findings block.
- [ ] SL-2 requested lint patterns exist and test files are whitelisted.
- [ ] SL-3 challenge-mode input robustness findings block.
- [ ] Requested pytest command passes.

## Final Validation Command

```bash
python -m pytest tests/test_security_lint_blocking.py tests/test_security_lint_extended.py -v
```
