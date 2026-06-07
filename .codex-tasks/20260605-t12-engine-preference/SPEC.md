# T12 ExecutionBundle 引擎偏好全链路传播

## Goal

在 Ralph plan、ExecutionBundle、Ralph IPC、PlanCompiler、AFExecutionEngine、
AgentFlow invariants 和 WorkflowOrchestrator 之间增加 execution engine
preference 传播，确保：

- `Plan.execution_engine` 可表达 `af | legacy | null`
- `ExecutionBundle.engine_preference` 与 `ReadyBatchSuggestion.engine_preference`
  统一承载 `af | legacy | auto`
- `PlanCompiler` 正确把 plan 偏好映射到 bundle
- AF 引擎拒绝执行 `legacy` 偏好 bundle
- Ralph 校验规则对未被 `agentflow/` 作用域支撑的 `execution_engine="af"`
  给出显式警告
- Orchestrator 从 suggestion 读取并传递偏好

## Scope

- 修改 `src/cccc/ralph/models.py`
- 修改 `src/cccc/contracts/v1/execution_bundle.py`
- 修改 `src/cccc/contracts/v1/ralph_ipc.py`
- 修改 `src/cccc/agentflow/plan_compiler.py`
- 修改 `src/cccc/agentflow/af_engine.py`
- 修改 `src/cccc/ralph/validation_rules/agentflow_invariants.py`
- 修改 `src/cccc/daemon/foreman/workflow_orchestrator.py`
- 新增 `tests/agentflow/test_engine_preference.py`

## Non-goals

- 不引入静默 fallback
- 不改动与本链路无关的执行策略
