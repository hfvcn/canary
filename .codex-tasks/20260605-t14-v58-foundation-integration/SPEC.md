# T14 基础修复 + AF 改进集成测试

## Goal

新增 `tests/test_v58_foundation_integration.py`，以 fixture-driven 方式对以下行为做精确断言：

- FL-67: `workflow.foreman_override` 可被 `sync_plan_state` / `_syncable_task_id_from_ledger_line` 识别为可同步任务
- FL-69: 同目录 `__init__.py` 变更免于 scope warning，越界文件仍触发 warning
- FL-70: `workflow.task_failed` 被纳入 friction events，空账本通过 workflow evaluation 文案显示无摩擦
- RV-AF-05: 空 task id 被 `_build_task_ref` 显式拒绝
- RV-AF-06: `compile` 将 `execution_engine` 正确传播到 `ExecutionBundle.engine_preference`

## Scope

- 新增 `tests/test_v58_foundation_integration.py`
- 运行 `pytest tests/test_v58_foundation_integration.py -v`

## Non-goals

- 不修改生产代码行为
- 不引入 fallback 或弱化断言
