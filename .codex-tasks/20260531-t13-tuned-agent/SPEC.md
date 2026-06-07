# T13 TunedAgentVersion Contract And Candidate Generation

## Goal

Implement plan.yaml T13 by adding the `TunedAgentVersion` contract, candidate
generation in `agent_ops.py`, and focused unit coverage.

## Scope

- `src/cccc/contracts/v1/tuned_agent.py`
- `src/cccc/daemon/ops/agent_ops.py`
- `tests/test_tuned_agent.py`

## Validation

`python -m pytest tests/test_tuned_agent.py -v`
