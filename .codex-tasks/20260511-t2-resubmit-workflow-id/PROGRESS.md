# Progress

## Recovery

任务: Resubmit canonical workflow_id 修复
形态: single-full
进度: 4/4
当前: Complete
文件: .codex-tasks/20260511-t2-resubmit-workflow-id/TODO.csv
下一步: 汇总变更与验证结果。

## Log

- Created task tracking artifacts for T2.
- Confirmed `AssignmentBatchMixin.process_batch_suggestion()` is the concrete entry point.
- Confirmed `WorkflowStateEngine.register_task()` currently ignores all duplicate registrations without checking `workflow_id`.
- Implemented resubmit-time canonical `workflow_id` resolution before batch registration.
- Added explicit rejection for mixed existing workflow ownership in one suggestion.
- Made `register_task()` idempotent only when the existing task belongs to the same workflow.
- Added focused regression coverage in `tests/test_resubmit_workflow_id.py`.
- Validation passed with `python -m pytest tests/test_resubmit_workflow_id.py -v` (`5 passed in 0.21s`).
