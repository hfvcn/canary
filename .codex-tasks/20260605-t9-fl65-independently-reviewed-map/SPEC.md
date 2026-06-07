# T9 FL-65 independently_reviewed 任务级映射审计

## Objective

在 `workflow_evaluation` 的测试统计输出中补充 `independently_reviewed` 对应的任务 ID 列表，并保持 `task_map=None` 的兼容行为。

## Scope

- 修改 `src/cccc/daemon/foreman/workflow_evaluation.py`
- 更新 `src/cccc/daemon/foreman/workflow_orchestrator.py` 的透传调用
- 新增 `tests/test_workflow_evaluation_task_map.py`
- 运行 `python -m pytest tests/test_workflow_evaluation_task_map.py -v`
