# Task Specification

> Scope anchor for the task. Update only when goals or constraints change, and log the reason in PROGRESS.md.

## Task Shape

- **Shape**: `single-full`

## Goals

- Repair failing tests caused by stale references to removed APIs.
- Restore minimal production compatibility for schema version constants if still part of the runtime contract.
- Skip tests that target features explicitly removed from the codebase.

## Non-Goals

- Reintroduce removed Phase4/semantic subsystems.
- Refactor unrelated production code or clean up the broader dirty worktree.

## Constraints

- Limit edits to the named failing tests and the smallest necessary source compatibility shims.
- Keep removed-feature failures visible by explicit `pytest.skip` markers instead of fake fallback implementations.
- Preserve existing user changes outside this task scope.

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: Python
- **Package manager**: project-local Python environment
- **Test framework**: pytest
- **Build command**: `pytest`
- **Existing test count**: unknown

## Risk Assessment

- [x] External dependencies (APIs, services) — availability confirmed?
- [x] Breaking changes to existing code — impact assessed?
- [x] Large file generation — disk space sufficient?
- [x] Long-running tests — timeout configured?

## Deliverables

- Updated source/test files covering the named stale API failures.
- Explicit skips for tests that exercise removed functionality.

## Done-When

- [ ] `pytest tests/ -q --tb=short -k 'not t5_phase4 and not test_space_ingest_invalid'` reports zero failures.

## Final Validation Command

```bash
pytest tests/ -q --tb=short -k 'not t5_phase4 and not test_space_ingest_invalid'
```
