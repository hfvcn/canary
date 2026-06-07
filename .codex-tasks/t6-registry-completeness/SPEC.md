# T6 Registry Completeness Validation

## Goal

Implement `validate_registry_completeness(registry_path)` in `model_ops.py` and add focused tests for enabled model registry completeness warnings.

## Scope

- Add completeness validation for enabled models.
- Check missing `description`, `best_for`, `strengths`, `cost_tier`.
- Check insufficient Foreman sample counts and ratings without samples.
- Disabled models must be ignored.

## Validation

Run:

```bash
python -m pytest tests/test_registry_completeness.py -v
```
