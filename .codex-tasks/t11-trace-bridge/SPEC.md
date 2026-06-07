# T11 TraceBridge

## Objective

Implement `src/cccc/daemon/ops/trace_bridge.py` for MSE-4b and add focused unit tests in `tests/test_trace_bridge.py`.

## Scope

- Record task execution attempts as `AttemptLink` records.
- Append JSONL records to `.cccc/performance/model_usage.jsonl` under the provided performance directory.
- Store `_schema_version` on each persisted record.
- Read records for model/task filtering.
- Skip corrupt JSONL rows with warnings.
- Let write failures raise exceptions.

## Verification

```bash
python -m pytest tests/test_trace_bridge.py -v
```
