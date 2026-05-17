# Progress

## Recovery

任务: T20 FL-5 guide --update advisory warnings
形态: single-full
进度: 3/3
当前: Complete
文件: .codex-tasks/20260517-t20-fl5-guide-advisory/TODO.csv
下一步: None.

## Log

- 2026-05-17: Created task artifacts.
- 2026-05-17: Located warning origin in `guide_generator.update_guide` and flow-step rendering in `_check_guide`.
- 2026-05-17: Confirmed `_check_guide` treats guide warnings as advisory details and does not fail the step.
- 2026-05-17: Ran `python -m pytest tests/test_flow_guide_advisory.py -v`; result: 2 passed.
