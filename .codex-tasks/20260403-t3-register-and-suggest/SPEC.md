# T3: Atomic register_and_suggest for phased plan submission

## Goal

Implement Task T3 from `plans/fix-v3-remaining.yaml`.

## Scope

- Add daemon IPC op `ralph_register_and_suggest`
- Add orchestrator method `register_and_suggest`
- Persist `task_ref` into `_active_workflows` so `_resuggest_ready_tasks` can rebuild candidates
- Switch `cmd_workflow_submit --plan` to use the new daemon op
- Verify with the requested pytest command

## Out of Scope

- Any behavioral change to the `--tasks` submission path
- Unrelated FIX-6/T1/T2/T10 work outside the files requested by the user
