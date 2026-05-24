# Progress Log

## Session Start

- **Date**: 2026-05-24
- **Task name**: `20260524-fl28-assignment-startup-runtime`
- **Task dir**: `.codex-tasks/20260524-fl28-assignment-startup-runtime/`
- **Spec**: `SPEC.md`
- **Plan**: `TODO.csv`

## Context Recovery Block

- **Current milestone**: `#4 — Run requested pytest selection`
- **Current status**: `DONE`
- **Last completed**: `#4 — Run requested pytest selection`
- **Current artifact**: `tests/test_assignment_startup.py`
- **Key context**: `startup 现在会在 actor_add 后检查 desired/runtime state，stall 时先 actor_restart，再按需回退 legacy start。`
- **Known issues**: `none`
- **Next action**: `Report results to user.`

## Milestone 1: Inspect assignment startup and actor add/start flow

- **Status**: DONE
- **Completed**: 16:32
- **What was done**:
  - Confirmed `actor_add` returns `running` / `start_error`
  - Confirmed restart requests must use `_daemon_request_fn`, not nonexistent `_handle_request_fn`
- **Validation**: `rg -n "_start_actor_for_assignment|add_actor_via_daemon|actor_restart|runtime_state" src/cccc/daemon/foreman src/cccc/daemon/actors tests`

## Milestone 2: Implement runtime stall detection and restart path

- **Status**: DONE
- **Completed**: 16:32
- **What was done**:
  - Added `_check_actor_actually_running`
  - Added `_restart_stalled_actor`
  - Updated `_start_actor_for_assignment` to prefer restart before legacy start
  - Extracted actor registration helpers into `assignment_actor_registration.py`
- **Validation**: `python -m compileall src/cccc/daemon/foreman/assignment_startup.py src/cccc/daemon/foreman/assignment_actor_registration.py src/cccc/daemon/foreman/assignment_controller.py`

## Milestone 3: Add focused unit tests

- **Status**: DONE
- **Completed**: 16:32
- **What was done**:
  - Added stall, running, and restart-fallback coverage in `tests/test_assignment_startup.py`
- **Validation**: `python -m pytest tests/test_assignment_startup.py -q` → `3 passed`

## Milestone 4: Run requested pytest selection

- **Status**: DONE
- **Completed**: 16:32
- **What was done**:
  - Ran the exact requested selection command under a 60s subprocess timeout wrapper
- **Validation**: `python -m pytest tests/test_assignment_startup.py -v -k "runtime_stall or verify_actor"` → `2 passed`

## Final Summary

- **Total milestones**: 4
- **Completed**: 4
- **Files created**: 2
- **Files modified**: 4
- **Key learnings**:
  - `actor_add` success does not guarantee runtime is actually up; runtime state verification is required.
