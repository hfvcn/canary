# Progress

## Recovery

任务: T18 FL-6 flow step-4 distinguishes new vs pre-existing changes
形态: single-full
进度: 0/4
当前: Locate implementation and tests
文件: `.codex-tasks/20260517-t18-flow-step4-current-session/TODO.csv`
下一步: Locate `_check_improvement_register()` and related tests.

## Log

- 2026-05-17: Created task record and started implementation discovery.
- 2026-05-17: Located existing marker check. It currently combines version, params.version, and started_at; no-version mode has no real pre-flow snapshot comparison.
- 2026-05-17: Implemented explicit version-marker mode and no-version pre-flow snapshot comparison. `py_compile` passes for source and focused test file.
- 2026-05-17: Final validation passed: `python -m pytest tests/test_flow_improvement_check.py -v` reported 6 passed in 1.13s under a 60s subprocess timeout. Related `tests/ralph/test_flow_e2e.py -k improvement_register -v` reported 3 passed in 1.25s.
- 2026-05-17: Supplemental archive prompt coverage passed: `python -m pytest tests/test_flow_archive_prompt.py -v` reported 2 passed in 0.98s.
