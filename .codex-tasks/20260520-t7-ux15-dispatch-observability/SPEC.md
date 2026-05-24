# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- Execute `T7` / `UX-15` from `plan.yaml`.
- Add dispatch observability logs to the workflow orchestrator for ready-task resuggestion and processed batches.
- Confirm `actor_controller` default concurrency is already above 1, then log the configured value at initialization.
- Add focused integration coverage for the new dispatch logging.

## Non-Goals

- Do not change batch admission, fallback, or scheduling behavior.
- Do not introduce silent fallbacks or mock-success paths.

## Constraints

- Preserve unrelated uncommitted edits in `workflow_orchestrator.py` and `tests/test_v5_integration_remaining.py`.
- Keep the change set limited to the files requested by T7 unless verification requires more.

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: Python
- **Test framework**: `pytest`

## Deliverables

- Dispatch batch logging in `src/cccc/daemon/foreman/workflow_orchestrator.py`.
- Init-time concurrency logging in `src/cccc/daemon/actor_controller.py`.
- Regression coverage in `tests/test_v5_integration_remaining.py`.

## Done-When

- [ ] Ready-task resuggestion logs include assignment-related dispatch context.
- [ ] Processed batch logs include task count and reported parallel count.
- [ ] `ActorController` logs configured concurrency at init without changing behavior when default is already `>= 2`.
- [ ] `python -m pytest tests/test_v5_integration_remaining.py -v -k 'dispatch_log_contains_batch_info'` passes.

## Final Validation Command

```bash
python -m pytest tests/test_v5_integration_remaining.py -v -k 'dispatch_log_contains_batch_info'
```
