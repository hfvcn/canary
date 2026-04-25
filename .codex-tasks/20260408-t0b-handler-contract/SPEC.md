# T0b Handler Contract

目标：按 `plans/phase4-remediation.yaml` 完整实现 `T0b-handler-contract`，补齐 Ralph IPC 注册响应的结构化校验错误契约，并保持现有调用方完全兼容。

范围：
- 修改 `src/cccc/contracts/v1/ralph_ipc.py`
- 修改 `src/cccc/contracts/v1/ipc.py`
- 新增 `tests/test_ralph_ipc_validation_errors.py`
- 补充 `tests/test_ralph_ipc.py`

完成条件：
- `IpcValidationError`、`WORKFLOW_PLAN_VALIDATION_FAILED`、`FATAL_IPC_VALIDATION_CODES`、`RalphRegisterResponse` 已定义
- 旧载荷不带新字段时仍可解析
- `DaemonResponse` schema 不变，但 `result` 契约说明已补齐
- 计划中的验证命令全部通过
