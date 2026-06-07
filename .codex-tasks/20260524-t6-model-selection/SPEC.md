# T6 Model Selection Fallback

## Goal

Implement `plan.yaml` T6 so model selection uses consistent fallback order:
`strengths` -> `best_for` -> `description` -> `None`.

## Scope

- Update `src/cccc/daemon/ops/agent_ops.py`
- Update `src/cccc/daemon/foreman/agent_pool.py`
- Add or update `tests/test_agent_pool_scoring.py`

## Validation

- `pytest tests/test_agent_pool_scoring.py -v`
