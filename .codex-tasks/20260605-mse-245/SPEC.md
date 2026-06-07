# MSE-2 / MSE-4 / MSE-5

## Goal
实现模型选择与评估闭环中的三项缺口：
- MSE-2: 补齐并验证 `cost_tier` 选择逻辑
- MSE-4: 在任务终态时写入模型 trace
- MSE-5: 将模型使用记录和 review 请求接到真实完成链路

## Constraints
- 不修改测试文件
- `workflow_orchestrator.py` 保持在 2700 行以内
- 运行指定测试命令并确保通过

## Validation
`python -m pytest tests/test_foreman_workflow.py tests/test_agent_pool_scoring.py tests/ralph/ -x -q --tb=short`
