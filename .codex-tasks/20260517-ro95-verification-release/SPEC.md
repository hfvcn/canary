# RO-95 Verification Release

## Goal

Fix verification-failure paths in `workflow_orchestrator.py` so failed tasks release their assigned agent and do not permanently pollute `_active_assignments`.

## Scope

- Update `on_verification_result()` failure handling.
- Update `_update_shadow_blocked()` failure handling.
- Update `tests/test_deferred_recovery.py` with regressions for agent release and post-failure batch dispatch.

## Acceptance

- `on_verification_result()` sets failed and releases the agent.
- `_update_shadow_blocked()` sets failed and releases the agent.
- After verification failure, `_active_assignments` no longer contains the failed agent.
- A new batch dispatch succeeds after a task verification failure.
