# T24 Workflow Verify Refresh Spec

## Goal

Implement `cccc workflow verify --refresh-spec` so on-demand verification can
reload the latest `verification` commands from `plan.yaml` instead of using the
stale cached task spec.

## Scope

- `src/cccc/cli/workflow_cmds.py`
- `src/cccc/daemon/ralph_ipc_handler.py`
- `tests/test_verify_refresh_spec.py`

## Validation

`python -m pytest tests/test_verify_refresh_spec.py -v`
