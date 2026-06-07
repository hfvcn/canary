# T1 FL-74 Runtime Default

## Goal
Unify the canonical `executor_runtime` default to `codex` by aligning:
- `src/cccc/contracts/v1/agent.py::Agent.model_runtime`
- `src/cccc/daemon/ops/agent_ops.py::_load_agent_yaml`
- `src/cccc/daemon/ops/agent_ops.py::_save_agent_yaml`

## Constraints
- Keep public signatures unchanged.
- Preserve explicit runtime round-trip behavior for `claude`, `gemini`, and `amp`.
- Update only tests that rely on fallback/default behavior.

## Verification
- `python -m pytest tests/ralph/test_bclass_fl74_runtime_default.py -v`
- Run affected existing tests touched by this change.
