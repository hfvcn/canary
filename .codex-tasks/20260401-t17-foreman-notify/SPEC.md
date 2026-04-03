# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- 在 worker 完成、失败、停滞时，自动通过 daemon messaging 向 foreman 发送通知。
- 通知必须走 daemon 内部 `send` 路径，不能直接 `append_event()` 写 ledger。
- 仅在必要时修改 `src/cccc/daemon/messaging/delivery.py`。

## Non-Goals

- 不重构无关 workflow 或 messaging 逻辑。
- 不引入静默 fallback 或 mock 成功路径。

## Constraints

- 只修改 `src/cccc/daemon/foreman/workflow_orchestrator.py` 与 `src/cccc/daemon/messaging/delivery.py`，测试仅在确有必要时更新。
- 验证命令必须使用用户指定的 pytest 子集。

## Deliverables

- `workflow_orchestrator.py` 中新增 foreman 自动通知逻辑。
- 若确有必要，`delivery.py` 中补充支持代码。
- 通过指定 pytest 验证。

## Final Validation Command

```bash
pytest tests/test_foreman_workflow.py tests/test_progress_report.py tests/test_workflow_state.py tests/test_delivery_state_behavior.py tests/test_delivery_throttle.py -q
```
