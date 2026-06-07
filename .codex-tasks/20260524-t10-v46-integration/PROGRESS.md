# Progress

- Identified the real integration entrypoints:
  - `cccc.ralph.flow_engine.FlowEngine`
  - `cccc.daemon.ops.agent_ops.select_model_for_task`
  - `cccc.daemon.foreman.workflow_monitor.WORKER_EXCEEDED_SCOPE_CODE`
  - `cccc.daemon.foreman.ralph_service._build_scope_warnings`
- Added `tests/e2e/test_v46_integration.py` with five focused integration tests.
- First pytest run exposed a live T6 regression: `select_model_for_task()` sorted by numeric score only, so `best_for` beat a direct `strengths` match.
- Patched `src/cccc/daemon/ops/agent_ops.py` to sort by source priority first (`strengths` > `best_for` > `description`), then by score within the same tier.
- Re-ran `pytest tests/e2e/test_v46_integration.py -v` successfully: `5 passed`.
