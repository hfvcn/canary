# Progress

## Recovery

- 任务: 修复 `flow_steps_e2e.py` 的 3 个 T7 审查问题
- 形态: `single-full`
- 进度: `3/3`
- 当前: 全部完成
- 文件: `.codex-tasks/20260607-t7-flow-steps-e2e-fixes/TODO.csv`
- 下一步: 无

## Log

- 已读取 `taskmaster` 技能说明。
- 已定位 `_extract_section_content`、`_check_cleanup`、`_global_assertions_detail` 及相关测试。
- 已实现 heading 优先级匹配、actor envelope 解析、group ledger JSONL 解析与 legacy fallback。
- 已新增针对 `评分摘要` 误命中、嵌套 actor envelope、group/legacy ledger 的测试覆盖。
- 已执行 `python -m pytest tests/ralph/test_flow_e2e_gates.py tests/ralph/test_flow_e2e.py tests/ralph/test_evaluation_placeholder.py -v --tb=short`。
- 首轮失败 2 个，原因为测试夹具仍写入 `groups/<id>/events.jsonl`；改为真实 `groups/<id>/ledger.jsonl` 后，37 项全部通过。
