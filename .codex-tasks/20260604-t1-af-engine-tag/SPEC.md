# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- Add AF engine tag detection helpers to `src/cccc/daemon/foreman/workflow_orchestrator.py`.
- Record an `execution_engine` metric row in `WORKFLOW_EVALUATION.md`.
- Add targeted tests for default, enabled, and import-failure engine tag behavior.

## Non-Goals

- Do not change workflow execution, dispatch, or scheduling logic.
- Do not alter existing AF or legacy engine implementations.

## Constraints

- Use a lazy import for `AFExecutionEngine`.
- Gate AF tagging with `CCCC_AF_ENGINE_ENABLED`.
- Preserve legacy tagging when AF is disabled or unavailable.

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: Python
- **Package manager**: `uv`
- **Test framework**: `pytest`
- **Build command**: not required
- **Existing test count**: not collected for task setup

## Risk Assessment

- [x] Breaking changes to existing code — impact limited to evaluation metadata.
- [x] Long-running tests — targeted pytest only.

## Deliverables

- Updated orchestrator helpers and evaluation metric output.
- New `tests/agentflow/test_engine_tag.py`.

## Done-When

- [x] `_af_engine_enabled()` returns `True` only when env flag is set and AF engine is importable and available.
- [x] `_execution_engine_tag` returns `af` or `legacy`.
- [x] `WORKFLOW_EVALUATION.md` includes an `execution_engine` metric row.
- [x] Targeted tests pass.

## Final Validation Command

```bash
pytest tests/agentflow/test_engine_tag.py tests/test_workflow_eval_detail.py tests/test_workflow_test_stats_reliability.py -q
```
