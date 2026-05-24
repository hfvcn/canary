# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- 为 E2E flow 的 step-2 增加失败恢复路径提示，明确鼓励设计一次可恢复的验证失败场景。
- 为 `WorkflowOrchestrator.retry_task()` 与 `override_task()` 补一条覆盖“验证失败 -> 重试 -> override 完成”的测试。
- 为剩余集成测试补一条断言，确保 E2E flow 文案持续包含失败恢复指引。

## Non-Goals

- 不修改 orchestrator 恢复逻辑实现本身。
- 不调整现有 E2E flow 的步骤顺序或其它验收语义。

## Constraints

- 仅修改用户指定的 3 个文件。
- 不回退仓库中的其他未提交变更。
- 以现有测试模式为准，避免引入新的测试基建。

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: Python
- **Test framework**: pytest

## Deliverables

- 更新后的 E2E step-2 指令文案
- `tests/test_deferred_recovery.py` 新增失败恢复链路测试
- `tests/test_v5_integration_remaining.py` 新增文案约束测试

## Done-When

- [ ] 3 个目标文件改动完成
- [ ] 目标 pytest 用例通过

## Final Validation Command

```bash
pytest tests/test_deferred_recovery.py tests/test_v5_integration_remaining.py tests/ralph/test_flow_e2e.py -q
```
