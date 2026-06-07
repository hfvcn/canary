# T7 flow_steps_e2e 修复

## 目标

修复 `src/cccc/ralph/flow_steps_e2e.py` 中 3 个已确认问题：

1. `评分` 章节提取误命中 `评分摘要`
2. `cccc actor list` 嵌套 envelope 未正确解析
3. `model.selection_decision` ledger 路径与解析方式错误

## 范围

- 修改 `src/cccc/ralph/flow_steps_e2e.py`
- 必要时同步 `tests/ralph/test_flow_e2e_gates.py`
- 必要时同步 `tests/ralph/test_flow_e2e.py`
- 必要时同步 `tests/ralph/test_evaluation_placeholder.py`

## 验证

执行：

```bash
python -m pytest tests/ralph/test_flow_e2e_gates.py tests/ralph/test_flow_e2e.py tests/ralph/test_evaluation_placeholder.py -v --tb=short
```
