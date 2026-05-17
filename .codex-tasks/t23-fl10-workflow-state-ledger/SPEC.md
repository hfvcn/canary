# T23 FL-10 Workflow State From Ledger

## Goal

Make `ralph suggest` read task status from the workflow ledger by default instead of relying on `plan.yaml`, so completed workflow tasks immediately produce the correct next batch without `ralph sync-state`.

## Scope

- Inspect `src/cccc/daemon/foreman/workflow_orchestrator.py` for ledger write behavior.
- Change `src/cccc/ralph/core.py` status reads to prefer the workflow ledger.
- Keep `plan.yaml` and ledger consistency expectations covered by `tests/test_plan_state_writeback.py`.
- Validate with `python -m pytest tests/test_plan_state_writeback.py -v`.

## Constraints

- Ledger is the single source of truth for workflow completion state.
- Do not add silent fallbacks or fake success paths.
- Keep changes scoped to the requested files unless tests require a small fixture update.
