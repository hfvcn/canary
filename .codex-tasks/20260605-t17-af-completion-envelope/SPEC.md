# Task Specification

> Scope anchor for the task. Update only when goals or constraints change, and log the reason in PROGRESS.md.

## Task Shape

- **Shape**: `single-full`

## Goals

- 在 `src/cccc/daemon/foreman/workflow_orchestrator.py` 增加 AF 结果到 completion envelope 的转换方法。
- 让 `apply_task_event` 流程兼容 `af.node_completed` 风格输入，并继续走现有 verification gate。
- 在 `tests/test_foreman_workflow.py` 增加对应 AF 事件测试并通过目标 pytest 选择器。

## Non-Goals

- 不改动 AF engine 的调度顺序或执行策略。
- 不引入新的静默 fallback 或 mock 成功路径。

## Constraints

- 保持现有 `TaskEvent`/verification gate 语义兼容。
- 手工代码编辑使用 `apply_patch`。
- 测试命令限定为 `python -m pytest tests/test_foreman_workflow.py -v -k af_event`。

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: Python
- **Package manager**: N/A
- **Test framework**: pytest
- **Build command**: N/A
- **Existing test count**: 未统计

## Risk Assessment

- [x] External dependencies (APIs, services) — availability confirmed?
- [x] Breaking changes to existing code — impact assessed?
- [x] Large file generation — disk space sufficient?
- [x] Long-running tests — timeout configured?

## Deliverables

- `workflow_orchestrator.py` 中的 AF completion envelope helper 与事件兼容逻辑
- `tests/test_foreman_workflow.py` 中新增 `test_af_event_*` 测试

## Done-When

- [ ] AF 结果可以被转换成 CCCC completion envelope
- [ ] `af.node_completed` 输入可触发原有 completed/verification 流程
- [ ] 指定 pytest 选择器通过

## Final Validation Command

```bash
python -m pytest tests/test_foreman_workflow.py -v -k af_event
```
