# Batch E Pre-Transition Hooks

## Goal

Implement Batch E Task T6 and T7 for workflow engine pre-transition hooks.

## Scope

- Add `TransitionRejected`, event kind constants, and `PreTransitionHook` to `src/cccc/kernel/workflow_state_types.py`
- Add pre-hook bookkeeping fields, API methods, replay handlers, and event registrations to `src/cccc/kernel/workflow_state_engine.py`
- Validate with the exact import check and pytest command provided by the user

## Out of Scope

- Any orchestrator wiring beyond the engine surface requested here
- New fallback logic or silent compatibility shims
