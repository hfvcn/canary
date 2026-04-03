# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- Expand `TaskEvent.event_type` to include `assigned`, `started`, and `heartbeat`.
- Preserve existing `completed` and `failed` behavior.
- Add targeted tests for task event contract coverage and stalled/offline sweep behavior.

## Non-Goals

- Do not change orchestrator semantics for non-terminal task events.
- Do not add fallback behavior or silent degradation.

## Constraints

- Limit code changes to the Wave 4 scope.
- Avoid breaking existing completed/failed event handling.
- Validate with the exact pytest command requested by the user.

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: `Python`
- **Package manager**: `unknown`
- **Test framework**: `pytest`
- **Build command**: `pytest`
- **Existing test count**: `not checked`

## Risk Assessment

- [x] External dependencies (APIs, services) — availability confirmed?
- [x] Breaking changes to existing code — impact assessed?
- [x] Large file generation — disk space sufficient?
- [x] Long-running tests — timeout configured?

## Deliverables

- Updated `TaskEvent` contract in `src/cccc/contracts/v1/ralph_ipc.py`
- Added task event tests in `tests/test_ralph_ipc.py`
- Added stalled/offline sweep tests in `tests/test_foreman_workflow.py`

## Done-When

- [ ] `TaskEvent` accepts the five required lifecycle values.
- [ ] Existing `completed` and `failed` tests still pass.
- [ ] `sweep_stalled_tasks()` is covered for offline, stalled, completed ignore, and custom thresholds.
- [ ] Requested pytest command passes.

## Final Validation Command

```bash
pytest tests/test_ralph_ipc.py tests/test_foreman_workflow.py -q -k 'task_event or stalled or sweep'
```
