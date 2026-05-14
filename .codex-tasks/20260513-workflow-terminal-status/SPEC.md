# workflow progress terminal status

## Goal

Update `ProgressReporter.summarize_progress()` so workflow status reflects terminal task states instead of always reporting `running`.

## Scope

- Modify `src/cccc/daemon/foreman/progress_report.py`.
- Add focused tests in `tests/test_workflow_terminal_status.py`.
- Validate with `python -m pytest tests/test_workflow_terminal_status.py -v`.

## Acceptance

- All tasks completed -> `completed`.
- Failed tasks with no running or pending tasks -> `failed`.
- Any running or pending task -> `running`.
- No workflow state -> `idle`.
