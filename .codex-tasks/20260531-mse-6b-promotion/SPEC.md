# MSE-6b Promotion Workflow

## Goal

Implement T14 from `plan.yaml`: add promotion and rejection operations for tuned agent candidates, and cover the workflow with focused tests.

## Scope

- Modify `src/cccc/daemon/ops/agent_ops.py`.
- Add `tests/test_agent_promotion.py`.
- Verify with `python -m pytest tests/test_agent_promotion.py -v`.

## Constraints

- Keep failures visible and avoid silent fallback behavior.
- Follow existing YAML and contract patterns.
- Keep changes scoped to the requested workflow.
