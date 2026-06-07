# T17 LegacyExecutionEngine

Implement `src/cccc/agentflow/legacy_engine.py` and tests for AF-M2 legacy
execution wrapper.

Acceptance:
- Engine imports from `cccc.agentflow.legacy_engine`.
- Empty bundle returns `{}` and completes.
- Dependency order is topological.
- Missing orchestrator produces dry-run node results.
- Status starts idle and becomes completed or failed.
- Failed node exceptions are visible in results and engine status.

