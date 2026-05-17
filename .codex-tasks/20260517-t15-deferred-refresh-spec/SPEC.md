# T15 Deferred Recovery + Refresh Spec

## Goal

Implement FL-12 deferred-state recovery actions and UX-11 `cccc workflow verify --refresh-spec` behavior.

## Scope

- Add or verify deferred recovery paths:
  - `retry_worker`: re-dispatch worker execution.
  - `retry_verifier`: run verification only.
  - `foreman_accept`: accept via explicit override.
  - `cancel`: abandon deferred task.
- Add or verify `--refresh-spec` for `cccc workflow verify`, re-reading `plan.yaml` to refresh verification commands.
- Target files:
  - `src/cccc/daemon/foreman/workflow_orchestrator.py`
  - `src/cccc/daemon/foreman/assignment_deferrals.py`

## Validation

`python -m pytest tests/test_deferred_recovery.py tests/test_verify_refresh_spec.py -v`
