# T12 Score Aggregation

## Objective

Implement `aggregate_model_scores(registry_path, performance_dir)` in
`src/cccc/daemon/ops/model_ops.py` and cover it with focused unit tests.

## Scope

- Read attempt links through `TraceBridge`.
- Aggregate per known model key from trace records.
- Update `foreman_sample_count` and `last_rated_at` in the model registry.
- Preserve manually assigned `foreman_rating`.
- Skip unknown model keys and empty registries.

## Validation

Run:

```bash
python -m pytest tests/test_score_aggregation.py -v
```
