# RO-74 Completion Reminder Prompt Fix

## Goal

Execute `plans/fix-v5-v29-ro74-75.yaml` task `T1`.

Add two mandatory completion reminder sections to
`src/cccc/daemon/foreman/prompt_builder.py`:

- `completion_reminder_top` immediately after `task_id`
- `completion_reminder_bottom` immediately after `completion_protocol`

Create `tests/test_prompt_completion_reminder.py` to verify output content,
relative order, and mandatory retention under a tight prompt budget.

## Validation

```bash
python -m pytest tests/test_prompt_completion_reminder.py -v
```
