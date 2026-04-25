# T1: RO-20 Worker Scope Violation

目标：在 `verify_completion` 中检测 worker 是否修改了 `claimed_paths` 之外的文件，并以 warning 形式附加到 `VerificationResult`。

范围：
- `src/cccc/contracts/v1/ralph_ipc.py`
- `src/cccc/daemon/foreman/ralph_service.py`
- `src/cccc/daemon/ralph_ipc_handler.py`
- `tests/test_ralph_verification.py`

验收：
- 越界修改返回 `W_WORKER_EXCEEDED_SCOPE`
- 合法修改不告警
- `src/auth` 不误匹配 `src/authorization`
- IPC 转发 `warnings`
- `python -m pytest tests/test_ralph_verification.py -q` 通过
