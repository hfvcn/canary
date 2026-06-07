# T7 Agent Lease Contracts

## Goal

Implement T7 from `plan.yaml`: add lightweight dataclass contracts for agent acquisition and leases.

## Scope

- Add `src/cccc/contracts/v1/agent_lease.py`.
- Add `tests/test_agent_lease_contracts.py`.
- Verify with `python -m pytest tests/test_agent_lease_contracts.py -v`.

## Constraints

- Use `dataclasses.dataclass(frozen=True)`.
- Keep contracts lightweight; do not add Pydantic models.
- Do not modify unrelated dirty worktree files.
