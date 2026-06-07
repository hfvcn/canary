# T2 BPA-3 INV-7

目标：按 `plan.yaml` 的 T2 精确实现 self-test producer 链路与 `INV-7 = NO_COMPLETE_WITHOUT_FRESH_SELF_TEST` monitor-style guard，保持 `TransitionRejected` 语义，并通过用户指定 pytest 集合。

范围：
- `src/cccc/ports/web/routes/workflow.py`
- `src/cccc/daemon/foreman/af_gateway_bridge.py`
- `src/cccc/daemon/foreman/verification_gate.py`
- `src/cccc/daemon/foreman/workflow_monitor.py`
- `src/cccc/daemon/foreman/workflow_orchestrator.py`
- `tests/ralph/test_bclass_bpa3_inv7.py`
- `tests/test_workflow_monitor.py`
- `tests/test_workflow_orchestrator_apply_event.py`
- `tests/test_verification_gate.py`

约束：
- 先建 producer，再开 guard。
- `self_test` 证据必须来自 worker 原生 completion 上报，不得反查 `verification_id`。
- BLOCK 模式必须抛 `TransitionRejected`，不能改成 `PreTransitionVetoed`。
