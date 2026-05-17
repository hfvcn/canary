# T14 Foreman Override

## Goal

Add a formal Foreman override path that marks a task as completed by override, records ledger evidence, releases any assigned agent, and unblocks downstream dependency gates.

## Scope

- `src/cccc/daemon/foreman/workflow_orchestrator.py`
- `src/cccc/daemon/ralph_ipc_handler.py`
- Existing verification: `python -m pytest tests/test_workflow_override.py -v`

