# T6 Plan Path Persist

## Goal

Implement `T6-plan-path-persist` from `plans/fix-remaining-issues.yaml`.

## Scope

- `src/cccc/kernel/workflow_state_types.py`
- `src/cccc/kernel/workflow_state_engine.py`
- `src/cccc/daemon/foreman/workflow_orchestrator.py`
- `tests/test_workflow_state.py`
- `tests/test_foreman_workflow.py`

## Acceptance

- `plan_path` is stored in workflow registration ledger events.
- Engine replay restores `plan_path`.
- Orchestrator reads `plan_path` from engine, not `_active_workflows`.
- Ralph plan context is restored after daemon restart.
- Requested pytest commands pass.
