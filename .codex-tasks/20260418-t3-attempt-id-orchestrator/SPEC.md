# T3 Orchestrator Attempt ID Passthrough

## Goal

Implement ARCH-8 continuation in the orchestrator and ops layers so assignment
attempt IDs are generated at approval time, cached in shadow state, cleared on
retry, and forwarded on completion events.

## Scope

- `src/cccc/daemon/foreman/workflow_orchestrator.py`
- `src/cccc/daemon/ops/workflow_task_ops.py`

## Validation

Run:

```bash
python -m pytest tests/test_foreman_workflow.py tests/test_workflow_state.py -q --tb=short
```
