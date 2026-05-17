# T20 Validate Ledger Event

## Goal

Modify `src/cccc/ralph/cli.py` so `ralph validate` emits a `workflow.plan_validated` daemon ledger event after validation completes on both success and failure.

## Scope

- Add event payload with `errors`, `warnings`, and `plan_digest`.
- Compute `plan_digest` as SHA-256 of the plan file content.
- Use the existing daemon IPC mechanism.
- Skip daemon-unavailable errors without blocking validation.
- Add focused tests in `tests/test_validate_ledger_event.py`.

## Validation

Run:

```bash
python -m pytest tests/test_validate_ledger_event.py -v
```
