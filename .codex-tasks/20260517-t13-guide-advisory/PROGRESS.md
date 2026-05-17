# Progress

## Recovery

任务: 执行 T13，调整 guide update 警告阻塞逻辑
形态: single-full
进度: 4/4
当前: 完成
文件: `.codex-tasks/20260517-t13-guide-advisory/TODO.csv`
下一步: 使用 fast-context 和文本搜索定位实现与测试模式

## Log

- 2026-05-17: Created task tracking artifacts.
- 2026-05-17: Located T13 and `_check_guide`; warnings are details today, generation failures need explicit blocking result.
- 2026-05-17: Updated `_check_guide` to convert guide generation/update exceptions into a blocking check result and keep output-size/warning details advisory after success.
- 2026-05-17: Added `tests/test_flow_guide_advisory.py` for advisory warnings and generation failures. `py_compile` passed.
- 2026-05-17: Focused pytest passed: `tests/test_flow_guide_advisory.py` and `tests/ralph/test_flow_engine_guide.py` (5 passed in 0.83s).
