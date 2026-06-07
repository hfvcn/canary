# Progress Log

## Session Start

- **Date**: 2026-06-06
- **Task name**: `af08-initial-submit`
- **Task dir**: `.codex-tasks/20260606-af08-initial-submit/`
- **Spec**: `SPEC.md`
- **Plan**: `TODO.csv`
- **Environment**: `Python / pytest`

## Context Recovery Block

- **Current milestone**: `#4 — Run targeted and full pytest validation`
- **Current status**: `DONE`
- **Last completed**: `#4 — Run targeted and full pytest validation`
- **Current artifact**: `tests/agentflow/test_af08_initial_submit_routing.py`
- **Key context**: `WorkflowOrchestrator.process_batch_suggestion` now accepts and forwards `allowed_existing_task_ids`, and `_submit_ready_suggestion` routes through the owner wrapper so AF gating executes on plan-driven initial submit. Runtime-not-ready orchestrators still fall back to the controller with unchanged legacy behavior.
- **Known issues**: `None`
- **Next action**: `None`

## Milestone 1: Trace AF-08 submit path and fixture requirements

- **Status**: `DONE`
- **What was done**:
  - Confirmed the bypass path from `register_and_suggest_inner` to `_submit_ready_suggestion`.
  - Verified the AF wrapper already lives in `WorkflowOrchestrator.process_batch_suggestion`.

## Milestone 2: Route initial submit through orchestrator AF wrapper

- **Status**: `DONE`
- **What was done**:
  - Added `allowed_existing_task_ids` to the orchestrator wrapper signature and forwarded it to the controller.
  - Switched `_submit_ready_suggestion` to call `self._owner.process_batch_suggestion(...)`.

## Milestone 3: Add AF-08 regression tests

- **Status**: `DONE`
- **What was done**:
  - Added `tests/agentflow/test_af08_initial_submit_routing.py`.
  - Covered AF-ready routing via `handle_ralph_register_and_suggest`.
  - Covered runtime-not-ready legacy pass-through without transport.

## Milestone 4: Run targeted and full pytest validation

- **Status**: `DONE`
- **What was done**:
  - Ran `python -m pytest tests/agentflow/test_af08_initial_submit_routing.py -v`.
  - Ran `python -m pytest tests/ -q`.
  - Updated four existing tests whose controller mocks needed the new `allowed_existing_task_ids` kw-only parameter.

## Final Summary

- **Total milestones**: `4`
- **Completed**: `4`
- **Files modified**: `7`
- **Key learnings**:
  - The production behavior change was correct on first pass; all full-suite failures came from stale test doubles that no longer matched the controller signature.
