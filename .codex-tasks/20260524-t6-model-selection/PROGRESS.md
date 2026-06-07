# Progress

- Read `plan.yaml` T6, `agent_ops.py`, `agent_pool.py`, and `tests/test_agent_pool_scoring.py`.
- Confirmed `ModelCapability.best_for` is currently stored as `str`, so helper must accept both current string data and requested list-like semantics.
- Added `src/cccc/daemon/ops/model_selection.py` to centralize `strengths -> best_for -> description` matching.
- Updated `select_model_for_task` to return `None` when no layer matches instead of silently picking a zero-strength candidate.
- Updated `AgentPoolManager._score_model_for_task` to reuse the same matcher while preserving weakness penalty, context bonus, and foreman rating logic.
- Verified with `pytest tests/test_agent_pool_scoring.py -v` (`17 passed`).
