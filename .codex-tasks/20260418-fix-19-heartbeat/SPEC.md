# Task Specification

> Scope anchor for the task. Update only when goals or constraints change, and log the reason in PROGRESS.md.

## Task Shape

- **Shape**: `single-full`

## Goals

- 修复 `workflow_orchestrator.check_stalled_tasks()` 在 `last_heartbeat` 为 `None` 时的停滞检测崩溃。
- 为 `AutomationManager._run_heartbeat_sweep()` 接入 orchestrator，并在周期扫描时触发停滞任务检测。

## Non-Goals

- 不改动心跳阈值策略以外的自动化规则。
- 不扩展新的 fallback 或静默降级路径。

## Constraints

- 只修改用户指定的两个文件。
- 保持现有行为不变，除了修复空心跳崩溃并补齐停滞检测调用。
- 验证命令使用用户指定的导入检查。

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: Python 3.9+
- **Package manager**: setuptools / pip
- **Test framework**: pytest
- **Build command**: N/A
- **Existing test count**: 未统计

## Risk Assessment

- [x] External dependencies (APIs, services) — availability confirmed?
- [x] Breaking changes to existing code — impact assessed?
- [x] Large file generation — disk space sufficient?
- [x] Long-running tests — timeout configured?

## Deliverables

- 修正 `src/cccc/daemon/foreman/workflow_orchestrator.py` 中的空心跳引用。
- 实现 `src/cccc/daemon/automation/engine.py` 中的 heartbeat sweep orchestrator 调用。
- 运行导入验证命令并记录结果。

## Done-When

- [ ] `check_stalled_tasks()` 不再直接对 `None` 的 `task.last_heartbeat` 做减法。
- [ ] `_run_heartbeat_sweep(group)` 能获取 orchestrator 并调用 `check_stalled_tasks(threshold_seconds=300)`。
- [ ] `python -c "from cccc.daemon.automation.engine import AutomationManager; print('OK')"` 成功输出 `OK`。

## Final Validation Command

```bash
python -c "from cccc.daemon.automation.engine import AutomationManager; print('OK')"
```

## Demo Flow (optional)

1. 导入 `AutomationManager`。
2. 确认命令输出 `OK`。
