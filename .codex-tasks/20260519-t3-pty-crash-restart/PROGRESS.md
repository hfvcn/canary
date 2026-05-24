# Progress

- Started T3 and inspected `plan.yaml`, PTY exit handling, actor lifecycle state transitions, and current test coverage.
- Confirmed there is no existing automatic actor restart on PTY exit; the implementation must reconnect `server.py` exit hooks to the actor lifecycle restart path.
- Added PTY exit WARNING logging and `.last_output` persistence of the last 4KB before session cleanup.
- Added crash-aware `_mark_actor_stopped_on_exit()` behavior with `crash_count`, 1/2/4s restart backoff scheduling, and `actor.crash_limit` signaling on the third consecutive crash.
- Verified with `python -m pytest tests/test_v5_integration_remaining.py -v -k 'crash or restart or exit or scrollback or last_output'` and all 8 selected tests passed.
