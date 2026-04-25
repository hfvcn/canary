# T7 Sync State Output

## Goal

Implement `T7-sync-state-output` from `plans/fix-remaining-issues.yaml`.

## Scope

- `src/cccc/ralph/plan_io.py`
- `src/cccc/ralph/cli.py`
- `tests/ralph/test_ralph_standalone.py`

## Acceptance

- `sync_plan_state()` returns structured sync counts.
- `ralph sync-state` prints accurate output for synced vs already-current tasks.
- `python -m pytest tests/ralph/test_ralph_standalone.py -k sync -v --tb=short` passes.
