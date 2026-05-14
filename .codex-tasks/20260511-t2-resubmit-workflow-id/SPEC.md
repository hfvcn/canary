# Resubmit Workflow ID Fix

## Goal

Implement T2 from `plans/fix-v5-v22-new.yaml` so resubmitted ready-batch suggestions resolve a canonical `workflow_id` from already-registered tasks, and `WorkflowStateEngine.register_task()` becomes idempotent only for the same workflow.

## Scope

In scope:
- `src/cccc/daemon/foreman/assignment_batches.py`
- `src/cccc/kernel/workflow_state_engine.py`
- `tests/test_resubmit_workflow_id.py`

Out of scope:
- Broader workflow reconciliation behavior
- Changes to unrelated batch admission or restart flows

## Validation

Run:

```bash
python -m pytest tests/test_resubmit_workflow_id.py -v
```
