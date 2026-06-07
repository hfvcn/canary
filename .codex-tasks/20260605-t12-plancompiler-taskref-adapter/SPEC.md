# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- 为 `ExecutionBundle` 契约补充 verification covers 字段与 `CCCCNodeMeta.task_id`
- 为 `PlanCompiler` 增加 task dict -> 属性访问对象适配，并保真传递关键任务语义字段
- 补充并通过 `tests/agentflow/test_plan_compiler.py`

## Non-Goals

- 不修改无关 agentflow/foreman 行为
- 不引入静默 fallback 或兼容分支

## Constraints

- 仅改动本任务相关文件
- 保持 `ExecutionBundle.to_dict()` 序列化行为可用
- 使用 `python -m pytest tests/agentflow/test_plan_compiler.py -v` 验证

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: `Python`
- **Package manager**: `n/a`
- **Test framework**: `pytest`
- **Build command**: `n/a`
- **Existing test count**: `n/a`

## Risk Assessment

- [x] External dependencies (APIs, services) — availability confirmed?
- [x] Breaking changes to existing code — impact assessed?
- [x] Large file generation — disk space sufficient?
- [x] Long-running tests — timeout configured?

## Deliverables

- `src/cccc/contracts/v1/execution_bundle.py`
- `src/cccc/agentflow/plan_compiler.py`
- `tests/agentflow/test_plan_compiler.py`
- 如有必要，更新受影响的 `tests/test_execution_bundle.py`

## Done-When

- [ ] 新字段在契约与 PlanCompiler 中可用，且指定 pytest 通过

## Final Validation Command

```bash
python -m pytest tests/agentflow/test_plan_compiler.py -v
```
