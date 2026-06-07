# Task Specification

> Scope anchor for the task. Update only when goals or constraints change, and log the reason in PROGRESS.md.

## Task Shape

- **Shape**: `single-full`

## Goals

- 修复 `flow_engine.py` 与 `discipline.py` 中 T6 审查指出的 finding adoption、pytest launcher 识别和重复定义问题。
- 保持旧 `plan.yaml` 在 `finding_refs[].status` 为空时兼容，不因缺省字段触发 step-3 gate 失败。
- 通过用户指定的两组 Ralph 测试。

## Non-Goals

- 不修改与本次问题无关的 Ralph 流程行为。
- 不清理工作区内其他已存在改动。

## Constraints

- 仅做最小必要修复，不能引入静默降级。
- 保持 `flow_engine.py` 与 `discipline.py` 的 finding adoption 状态枚举一致。
- 验证命令使用用户指定的 pytest 目标集。

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: `Python`
- **Package manager**: `unknown`
- **Test framework**: `pytest`
- **Build command**: `n/a`
- **Existing test count**: `not scanned`

## Risk Assessment

- [x] Breaking changes to existing code — 仅修改目标函数，风险可控。
- [x] Long-running tests — 只跑两组定向测试。

## Deliverables

- `src/cccc/ralph/flow_engine.py`
- `src/cccc/ralph/validation_rules/discipline.py`
- 相关回归测试更新

## Done-When

- [ ] 四个问题都已修复，且指定 pytest 全绿。

## Final Validation Command

```bash
python -m pytest tests/ralph/test_flow_solve_gates.py tests/ralph/test_flow_engine.py -v --tb=short
```
