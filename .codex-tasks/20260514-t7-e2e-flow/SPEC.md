# T7 E2E Flow CLI

## Goal

Execute `T7` from `plans/v33-ux-and-ro-fixes.yaml`: add the E2E flow step definitions and wire `ralph flow` CLI subcommands.

## Scope

- `src/cccc/ralph/flow_steps_e2e.py`
- `src/cccc/ralph/flow_engine.py`
- `src/cccc/ralph/cli.py`
- `tests/ralph/test_flow_e2e.py`

## Acceptance

- `FlowEngine.start("e2e")` persists E2E state and creates step directories.
- E2E flow exposes seven steps numbered `0` through `6`.
- E2E step 4 requires at least two valid Codex JSON outputs plus `WORKFLOW_EVALUATION.md`.
- `ralph flow start|next|status` parse and dispatch.
- Requested verification commands pass or surface failures directly.
