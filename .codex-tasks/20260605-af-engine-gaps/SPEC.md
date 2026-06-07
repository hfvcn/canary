# Task Specification

> Scope anchor for the task. Update only when goals or constraints change, and log the reason in PROGRESS.md.

## Task Shape

- **Shape**: `single-full`

## Goals

- Fix GAP-5 so AF runtime readiness recognizes production daemon transport and does not skip AF when `send_message_fn` is absent but `daemon_request_fn` is live.
- Fix GAP-6 so `AFExecutionEngine.execute_bundle()` schedules independent DAG nodes concurrently by dependency tier instead of serial topological iteration.

## Non-Goals

- No test-file changes.
- No new fallback paths or mock success behavior.
- No broader refactor outside the three user-specified source files.

## Constraints

- Modify only `src/cccc/daemon/foreman/af_gateway_bridge.py`, `src/cccc/daemon/foreman/workflow_orchestrator.py`, and `src/cccc/agentflow/af_engine.py`.
- Keep `workflow_orchestrator.py` under 2700 lines.
- Final verification must use the exact pytest command from the task.

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: `Python 3`
- **Package manager**: `setuptools / python -m`
- **Test framework**: `pytest`
- **Build command**: `python -m pytest ...`

## Risk Assessment

- [x] Breaking changes to existing code — impact assessed around engine-tag tests and daemon send bridge behavior.
- [x] Long-running tests — timeout will be enforced with `timeout 60`.
- [ ] External dependencies (APIs, services) — not required for target unit/integration tests.
- [ ] Large file generation — not relevant.

## Deliverables

- Runtime readiness guard accepts either `send_message_fn` or `daemon_request_fn` plus agent-pool availability.
- AF gateway bridge can dispatch through daemon `send` when direct send callback is absent.
- AF execution engine runs same-tier DAG nodes concurrently and preserves deterministic result ordering.

## Done-When

- [ ] Requested pytest suite passes without modifying tests.
- [ ] `workflow_orchestrator.py` remains under 2700 lines.
- [ ] AF execution tag reports `af` only when engine is enabled and runtime-ready on initialized orchestrators.

## Final Validation Command

```bash
python -m pytest tests/test_foreman_workflow.py tests/agentflow/ tests/e2e/test_auto_dispatch.py tests/test_v5_integration_remaining.py tests/test_module_split.py -x -q --tb=short
```
