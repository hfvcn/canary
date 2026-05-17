# T13 Guide Advisory

## Goal

Execute T13 from `plans/fix-v38-all-issues.yaml`: make flow step-7 treat guide update warnings about affected changes as advisory, while still blocking on real guide generation failures.

## Scope

- Modify `src/cccc/ralph/flow_engine.py`.
- Add `tests/test_flow_guide_advisory.py`.
- Verify with focused automated tests.

## Acceptance Criteria

- Guide generation command failure blocks the flow.
- Warnings like `affected by changes -- review manually` do not block.
- Tests cover both cases.
