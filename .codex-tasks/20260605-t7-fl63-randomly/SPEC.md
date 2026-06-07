# T7 FL-63 pytest-randomly 自动检测

## Objective

在 `workflow_evaluation` 中自动检测项目是否声明安装了 `pytest-randomly`，并据此收紧 `test_stats_reliable` 的判定。

## Scope

- 更新 `src/cccc/daemon/foreman/workflow_evaluation.py`
- 新增 `tests/test_workflow_evaluation_randomly.py`
- 运行 `python -m pytest tests/test_workflow_evaluation_randomly.py -v`
