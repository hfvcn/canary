# T9 Tests

目标：根据 `plans/phase4-deep-integration.yaml` 为 `tests/test_ralph_semantic.py` 补齐缺失的 Phase 4 测试，避免重复已有覆盖，重点覆盖 35-41 负向不变量。

范围：
- 只修改 `tests/test_ralph_semantic.py`
- 运行 `python -m pytest tests/test_ralph_semantic.py -v --tb=short`

完成条件：
- 缺失的 Phase 4 测试已补齐
- 指定 pytest 命令通过
