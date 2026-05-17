# T16 RO-84 Ralph Validate Ledger Event

## Goal
Emit a compact `ralph.validate_result` daemon event after `ralph validate` completes.

## Scope
- Locate the validate command flow and existing daemon IPC helpers.
- Emit counts, plan path digest, and pass/fail outcome after `validate()` returns.
- Silently skip when the daemon is unavailable.
- Run the requested pytest files.

## Out of Scope
- Full plan text in ledger payloads.
- New fallback or mock event paths.
