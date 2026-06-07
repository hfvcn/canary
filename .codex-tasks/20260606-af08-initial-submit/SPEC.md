# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- Route plan-driven initial submit through `WorkflowOrchestrator.process_batch_suggestion` so AF executes on the main path when enabled and runtime-ready.
- Preserve legacy behavior when AF runtime is not ready.
- Add regression coverage for AF-ready and no-transport cases.

## Non-Goals

- No change to AF gate logic, fallback semantics, or non-initial submit paths.
- No new silent fallback behavior.

## Constraints

- Keep file/module guards intact, including `tests/test_module_split.py`.
- Do not change behavior when orchestrator lacks transport/pool readiness.
- Verify no recursion or double registration in the new route.

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: `Python`
- **Test framework**: `pytest`

## Deliverables

- Code changes in orchestrator/controller routing path.
- New regression file `tests/agentflow/test_af08_initial_submit_routing.py`.
- Targeted and full test results.

## Done-When

- [ ] Initial plan submit goes through AF wrapper when runtime-ready.
- [ ] Legacy behavior remains unchanged when runtime is not ready.
- [ ] Targeted and full pytest runs are completed and reported.

## Final Validation Command

```bash
python -m pytest tests/agentflow/test_af08_initial_submit_routing.py -v
python -m pytest tests/ -q
```
