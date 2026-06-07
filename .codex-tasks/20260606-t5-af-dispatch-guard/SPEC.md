# T5 AF Dispatch Guard

## Goal

Implement `plan.yaml` task `T5` exactly:

- caller-thread AF registration before send/return
- background-thread `execute_bundle` only
- inflight dedupe by `(workflow_id, node_id, attempt_id)`
- per-task AF max-attempt circuit breaker
- strict fail-closed when AF is unavailable
- stronger runtime readiness checks
- explicit observability events

## Scope

- Modify `src/cccc/daemon/foreman/af_gateway_bridge.py`
- Modify minimal AF wiring in `src/cccc/daemon/foreman/workflow_orchestrator.py`
- Add `tests/agentflow/test_af_dispatch_guard.py`
- Preserve specified regressions

## Validation

Run:

```bash
python -m pytest tests/agentflow/test_af_dispatch_guard.py -v
python -m pytest tests/test_af_fallback_observability.py tests/agentflow/test_apply_event_terminal_bridge.py tests/test_foreman_workflow.py -q
```
