# T16 Sync State CLI

## Goal

Implement `T16` from `plans/fix-remaining-issues.yaml`.

## Scope

- `src/cccc/ralph/plan_io.py`
- `src/cccc/ralph/cli.py`

## Acceptance

- `sync_plan_state(plan_path, ledger_path)` syncs verification-complete task IDs from a ledger into `plan.yaml`.
- `ralph sync-state` supports `--ledger` and `--group`.
- Requested import checks pass.
