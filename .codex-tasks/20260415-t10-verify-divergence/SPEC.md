# T10 Verify Divergence

目标：实现 worker 自报成功但验证失败时的显式分歧处理。

约束：
- 不新增 `WorkflowTaskStatus` 枚举。
- 使用现有 `FAILED` 状态。
- 通过 `blocked_reason="verification_divergence"` 与分歧事件元数据表达差异。
- 保持现有重试路径可用。

范围：
- `src/cccc/daemon/foreman/workflow_orchestrator.py`
- `src/cccc/daemon/foreman/ralph_service.py`
- `src/cccc/kernel/workflow_state_engine.py`
- `src/cccc/kernel/workflow_state_types.py`
- `src/cccc/contracts/v1/ralph_ipc.py`
- `tests/test_ralph_verification.py`
