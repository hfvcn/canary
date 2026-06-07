# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- 实现 `plan.yaml` 的 T4，仅落地 BPA-4 / BP-2 liveness 强制约束。
- 在 `workflow_monitor.py` 增加硬 liveness 截止检测和 `MonitorConfig.liveness`。
- 在 `workflow_orchestrator.py` 真实 stall patrol 主路径接入 liveness，并在 `BLOCK` 模式下强制升级，避免任务永久卡在原 stuck 状态。
- 新增和更新测试，覆盖 warn/enforce、未超时不误报、reachability，以及既有 stall 行为不回归。

## Non-Goals

- 不实现 BP-5。
- 不引入非 ledger-backed 的 plan-version stamp。
- 不改变既有 stall/silent_agent/auto_reassign 的语义，除非是为 liveness enforce 增加独立路径。

## Constraints

- 必须建立在 T2 已有 `fresh_self_test` 和 monitor hook 改动之上，不回滚它们。
- 只修改用户限定的源文件与测试文件。
- 最终验证命令必须是用户指定的 pytest 集合。

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: Python
- **Package manager**: repo local environment
- **Test framework**: pytest
- **Build command**: `python -m pytest`

## Deliverables

- `src/cccc/daemon/foreman/workflow_monitor.py`
- `src/cccc/daemon/foreman/workflow_orchestrator.py`
- `tests/test_workflow_monitor.py`
- `tests/ralph/test_bclass_bpa4_liveness.py`

## Done-When

- [ ] T4 acceptance criteria satisfied for BP-2 only, with BP-5 untouched.
- [ ] 指定 pytest 集合实际通过。

## Final Validation Command

```bash
python -m pytest tests/ralph/test_bclass_bpa4_liveness.py tests/test_workflow_monitor.py tests/test_stall_actor_idle.py tests/test_stall_auto_reassign.py -v
```
