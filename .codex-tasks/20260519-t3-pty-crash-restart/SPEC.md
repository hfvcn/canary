# T3 PTY Crash Restart

## Goal

Implement UX-16 + UX-17 for PTY actors: crash exit warning logs, last-output persistence, crash-aware actor state transitions, restart backoff, and crash-limit signaling.

## Scope

- `src/cccc/runners/pty.py`
- `src/cccc/daemon/server.py`
- `src/cccc/daemon/actors/actor_lifecycle_ops.py`
- `tests/test_v5_integration_remaining.py`

## Verification

- `python -m pytest tests/test_v5_integration_remaining.py -v -k 'crash or restart or exit or scrollback or last_output'`
