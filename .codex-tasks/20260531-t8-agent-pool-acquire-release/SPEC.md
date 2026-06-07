# T8 AgentPoolManager Acquire/Release

## Goal
Implement MSE-3b AgentPoolManager lease acquisition and release APIs.

## Scope
- Modify `src/cccc/daemon/foreman/agent_pool.py`.
- Add focused tests in `tests/test_agent_acquire_release.py`.
- Verify with `python -m pytest tests/test_agent_acquire_release.py -v`.

## Constraints
- Preserve existing `create_or_reuse_agent` behavior.
- Keep failures explicit; do not add fallback success paths.
