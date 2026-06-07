# Task Specification

> Scope anchor for the task. Update only when goals or constraints change, and log the reason in PROGRESS.md.

## Task Shape

- **Shape**: `single-full`

## Goals

- Fix `LegacyExecutionEngine._execute_node` so orchestrator-backed execution returns completed legacy-engine metadata.
- Preserve the existing dry-run stub behavior when no orchestrator is configured.
- Add focused tests for dry run, orchestrator-backed execution, and bundle aggregation.

## Non-Goals

- Do not change topological sorting behavior.
- Do not add real orchestrator integration beyond the required return payload.
- Do not expand test coverage outside `legacy_engine`.

## Constraints

- Keep the no-orchestrator branch behavior unchanged.
- Follow existing `ExecutionBundle` and `CCCCNodeMeta` contracts.
- Verify with a targeted pytest run.

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: `Python 3.11.7`
- **Package manager**: `pyproject.toml` / local environment
- **Test framework**: `pytest`
- **Build command**: `python -m pytest -n0 tests/agentflow/test_legacy_engine.py`
- **Existing test count**: `1482`

## Risk Assessment

- [x] External dependencies (APIs, services) — availability confirmed?
- [x] Breaking changes to existing code — impact assessed?
- [x] Large file generation — disk space sufficient?
- [x] Long-running tests — timeout configured?

## Deliverables

- Update [src/cccc/agentflow/legacy_engine.py](/Users/vfch/Documents/project/canary/cccc-main-git/src/cccc/agentflow/legacy_engine.py)
- Update [tests/agentflow/test_legacy_engine.py](/Users/vfch/Documents/project/canary/cccc-main-git/tests/agentflow/test_legacy_engine.py)
- Record validation in `.codex-tasks/20260604-legacy-engine-t2/PROGRESS.md`

## Done-When

- [x] `_execute_node` returns the required payload when `self._orchestrator` is present.
- [x] `_execute_node` still returns the existing dry-run stub payload when `self._orchestrator` is `None`.
- [x] `tests/agentflow/test_legacy_engine.py` covers both branches and bundle aggregation.
- [x] `python -m pytest -n0 tests/agentflow/test_legacy_engine.py` passes.

## Final Validation Command

```bash
python -m pytest -n0 tests/agentflow/test_legacy_engine.py
```
