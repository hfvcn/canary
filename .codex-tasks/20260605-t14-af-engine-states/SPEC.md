# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- Extend `src/cccc/agentflow/af_engine.py` so `AFExecutionEngine.execute_bundle` reports AF node interim statuses through an optional callback.
- Persist `interim_statuses` on successful and failed node results.
- Add `failure_category: "engine_error"` for AF execution failures.
- Add focused tests in `tests/agentflow/test_af_engine_states.py`.

## Non-Goals

- Do not change DAG ordering or dependency resolution behavior.
- Do not add fallback status semantics beyond the requested AF node states.

## Constraints

- Keep behavior silent when `status_callback` is not provided.
- Preserve existing successful result fields from `_execute_with_af`.
- Run only the user-requested pytest target for validation.

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: Python
- **Package manager**: `uv`
- **Test framework**: `pytest`
- **Build command**: not required
- **Existing test count**: not collected for task setup

## Risk Assessment

- [x] Breaking changes to existing code — impact limited to AF node result metadata and optional callback reporting.
- [x] Long-running tests — validation limited to a single targeted pytest file.

## Deliverables

- Updated `AFExecutionEngine.execute_bundle` state reporting behavior.
- New `tests/agentflow/test_af_engine_states.py`.

## Done-When

- [x] Successful AF node results include `interim_statuses` with `assigned`, `running`, and `verifying`.
- [x] Failed AF node results include `failure_category: "engine_error"` and `interim_statuses` ending in `failed`.
- [x] `status_callback` receives requested state transitions.
- [x] The engine still runs without a callback.

## Final Validation Command

```bash
python -m pytest tests/agentflow/test_af_engine_states.py -v
```
