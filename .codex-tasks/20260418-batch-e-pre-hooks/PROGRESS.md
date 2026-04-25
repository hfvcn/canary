# Progress

- Inspected `workflow_state_types.py`, `workflow_state_engine.py`, and related orchestrator usage.
- Confirmed existing engine already has pre-transition support with older naming; patch will preserve behavior while adding the requested Batch E API surface.
- Updated `workflow_state_types.py` to expose the requested `TransitionRejected` constructor signature and `PreTransitionHook` alias.
- Updated `workflow_state_engine.py` to add canonical `_pre_hooks` / `_pending_alerts` state, explicit replay handlers, and requested monitor-alert methods.
- Synced `workflow_snapshot.py` with the canonical pending-alert field so snapshot restore does not desynchronize aliases.
- Validation passed:
  - `python -c "from cccc.kernel.workflow_state_types import TransitionRejected, KIND_TRANSITION_REJECTED, PreTransitionHook; print('OK')"`
  - `python -m pytest tests/test_workflow_state.py -q --tb=short`
