# T18 Workflow Override And Deferred Recovery

## Goal

Implement FL-11/12 from `plans/fix-v38-all-issues.yaml`: add the `cccc workflow override` CLI/daemon path and make deferred workflow tasks recoverable.

## Scope

- Add CLI override command and workflow subcommand registration.
- Add daemon IPC handling for `workflow_override`, including state update and ledger event.
- Add `completed_by_override` workflow status if absent.
- Add state transitions from `deferred` to retry, override, and cancel outcomes.
- Treat `completed_by_override` as satisfying downstream dependencies.
- Add focused tests for override and deferred recovery.

## Validation

- Run focused tests with a 60 second timeout.
- Run broader related workflow tests if focused tests expose integration risk.

