# FL-42a Auto-Trigger Foreman Evaluation

## Goal

Implement T1 from `plan.yaml`: automatically request a foreman model review after assignment completion once enough samples exist, without blocking completion if the review request fails.

## Scope

- Update `src/cccc/daemon/foreman/assignment_completion.py`.
- Update `src/cccc/daemon/ops/model_ops.py`.
- Add `tests/test_evaluation_auto_trigger.py`.
- Verify with `python -m pytest tests/test_evaluation_auto_trigger.py -v`.

## Constraints

- Keep failures visible except the explicitly requested non-blocking review request failure path.
- Preserve existing registry structure and code style.
