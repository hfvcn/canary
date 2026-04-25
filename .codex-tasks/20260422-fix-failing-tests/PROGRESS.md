# Progress Log

> Auto-maintained by Taskmaster. Each entry records what happened, why, and what's next.
> This file serves as both decision audit trail and context-recovery anchor.

---

## Session Start

- **Date**: 2026-04-22
- **Task name**: `20260422-fix-failing-tests`
- **Task dir**: `.codex-tasks/20260422-fix-failing-tests/`
- **Spec**: See `SPEC.md`
- **Plan**: See `TODO.csv` (4 milestones)
- **Environment**: Python / pytest

---

## Context Recovery Block

- **Current milestone**: #4 — Run scoped suite and confirm zero failures
- **Current status**: DONE
- **Last completed**: #4 — Run scoped suite and confirm zero failures
- **Current artifact**: `.codex-tasks/20260422-fix-failing-tests/TODO.csv`
- **Key context**: Compatibility shims were restored only where the runtime contract still exists; stale Phase4 semantic tests were explicitly skipped; all target and scoped suite validations passed.
- **Known issues**: Worktree remains otherwise dirty outside this task scope.
- **Next action**: None.

## Milestone 1: Inspect affected tests and current APIs

- **Status**: DONE
- **What was done**:
  - Read the named failing tests and matched them against current source APIs.
  - Confirmed removed CLI and Phase4 semantic surfaces versus still-supported runtime contracts.
- **Key decisions**:
  - Decision: restore only small compatibility shims in production code.
  - Reasoning: `deserialize_event` and schema-version metadata are still useful ledger/runtime contracts; removed CLI and Phase4 flows should not be reintroduced.
- **Problems encountered**:
  - Problem: `fast_context_search` did not return usable results in this environment.
  - Resolution: fell back to local ripgrep/source inspection.
- **Validation**: `python -m pytest ...12 target files... -q --tb=short` → identified 45 failures across the intended buckets
- **Files changed**:
  - `none`
- **Next step**: Milestone 2 — Apply compatibility fixes for still-supported APIs

## Milestone 2: Apply compatibility fixes for still-supported APIs

- **Status**: DONE
- **What was done**:
  - Added `schema_version`, `SCHEMA_VERSIONS`, and `deserialize_event` back to the event contract.
  - Updated workflow ledger replay to consume `deserialize_event`.
  - Fixed `WorkspaceIndex.path_exists()` cache invalidation on file mutations/deletes.
  - Updated tests for current workflow snapshot metadata and reporter/task-op signatures.
- **Validation**: `python -m pytest tests/test_ledger_migration.py tests/test_ledger_versioning.py tests/test_prompt_forbidden_flows.py tests/test_prompt_recommended_tests.py tests/test_ralph_advisory_rules.py tests/test_ralph_cache_invalidation.py tests/test_ralph_error_envelope.py tests/test_ralph_semantic.py tests/test_ralph_wave3_integration.py tests/test_worker_collaboration_integration.py tests/test_workflow_snapshot.py tests/test_workflow_task_ops.py -q --tb=short` → reduced to 3 failures, then 0 failures after follow-up test alignment
- **Files changed**:
  - `src/cccc/contracts/v1/event.py` — restored schema-version compatibility helpers
  - `src/cccc/kernel/workflow_state_engine.py` — replay now deserializes ledger events via contract helper
  - `src/cccc/ralph/workspace_index.py` — fixed stale path-existence cache reuse
  - `tests/test_ledger_migration.py`
  - `tests/test_ralph_advisory_rules.py`
  - `tests/test_ralph_error_envelope.py`
  - `tests/test_worker_collaboration_integration.py`
  - `tests/test_workflow_snapshot.py`
  - `tests/test_workflow_task_ops.py`
- **Next step**: Milestone 3 — Skip tests for removed features

## Milestone 3: Skip tests for removed features

- **Status**: DONE
- **What was done**:
  - Module-skipped the stale Phase4 semantic suite.
  - Marked removed ledger-migrate CLI tests as skipped.
  - Raised prompt-budget values in surviving prompt tests so they match current mandatory-minima enforcement.
- **Validation**: `python -m pytest tests/test_ledger_migration.py tests/test_ledger_versioning.py tests/test_prompt_forbidden_flows.py tests/test_prompt_recommended_tests.py tests/test_ralph_advisory_rules.py tests/test_ralph_cache_invalidation.py tests/test_ralph_error_envelope.py tests/test_ralph_semantic.py tests/test_ralph_wave3_integration.py tests/test_worker_collaboration_integration.py tests/test_workflow_snapshot.py tests/test_workflow_task_ops.py -q --tb=short` → `99 passed, 96 skipped`
- **Files changed**:
  - `tests/test_prompt_forbidden_flows.py`
  - `tests/test_prompt_recommended_tests.py`
  - `tests/test_ralph_semantic.py`
  - `tests/test_ralph_wave3_integration.py`
- **Next step**: Milestone 4 — Run scoped suite and confirm zero failures

## Milestone 4: Run scoped suite and confirm zero failures

- **Status**: DONE
- **What was done**:
  - Ran the user-requested scoped suite across all tests.
  - Fixed two additional failures found outside the original 12 files by updating tests to current cache semantics and sandbox-safe web bind preflight mocking.
- **Validation**: `pytest tests/ -q --tb=short -k 'not t5_phase4 and not test_space_ingest_invalid'` → `2146 passed, 120 skipped, 10 deselected in 92.35s`
- **Files changed**:
  - `tests/ralph/test_workspace_index.py`
  - `tests/test_web_bind_preflight.py`
- **Next step**: none

## Final Summary

- **Total milestones**: 4
- **Completed**: 4
- **Failed + recovered**: 0
- **External unblock events**: 0
- **Total retries**: 0
- **Files created**: 3
- **Files modified**: 15
- **Key learnings**:
  - The remaining runtime contract still expects event deserialization/version helpers even though older CLI and Phase4 semantic surfaces were removed.
  - `WorkspaceIndex.path_exists()` had a real stale-cache bug that broader test coverage exposed.
