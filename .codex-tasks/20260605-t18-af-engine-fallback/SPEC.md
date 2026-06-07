# T18 AF 引擎两段式 fallback + 环境变量开关

## Goal

在 `WorkflowOrchestrator` 中引入 AF 两段式 fallback 入口，确保：

- pre-dispatch 失败可明确回退到 legacy；
- mid-execution 失败必须显式抛错，不允许静默继续；
- workflow evaluation 持续记录 `execution_engine`；
- 新增定向测试覆盖 fallback 和 engine tag。

## Scope

- 修改 `src/cccc/daemon/foreman/workflow_orchestrator.py`
- 新增 `tests/agentflow/test_engine_fallback.py`
- 修正仓内对旧 `_compile_af_bundle` 方法名的测试引用
- 运行 `python -m pytest tests/agentflow/test_engine_fallback.py -v`

## Non-goals

- 不新增静默降级路径
- 不伪造 AF 成功执行结果
