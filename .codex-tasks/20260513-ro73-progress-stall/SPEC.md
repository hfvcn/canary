# RO-73 Progress Stall Detection

## Goal

Implement T6 from `plans/fix-v5-v27-remaining.yaml`: add progress-based stall detection for running tasks that keep sending heartbeats but do not advance `progress_pct`.

## Scope

- Add `check_progress_stall()` in `src/cccc/daemon/foreman/workflow_monitor.py`.
- Integrate the alert into `check_stalled_tasks()` in `src/cccc/daemon/foreman/workflow_orchestrator.py`.
- Add focused tests in `tests/test_file_write_stall.py`.

## Validation

Run:

```bash
python -m pytest tests/test_file_write_stall.py -v
```
