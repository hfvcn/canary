# T5 Cost Tier Scoring

## Goal

Implement MSE-2 `cost_tier` support for model capabilities and cost-aware scoring in the foreman agent pool.

## Scope

- Add `cost_tier` to `ModelCapability`.
- Add `cost_tier` to enabled model registry entries only.
- Add simple-task cost tier bonus in `_score_model_for_task`.
- Add focused tests for scoring and contract compatibility.

## Validation

```bash
python -m pytest tests/test_cost_tier_scoring.py -v
```
