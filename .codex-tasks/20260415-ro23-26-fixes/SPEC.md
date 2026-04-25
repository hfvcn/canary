# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- 修复 Ralph 问题清单中 23/24 对应的 plan 加载与 schema 问题。
- 确认并保留 26 的依赖校验行为，避免回归。
- 对 25 仅采用仓库已存在的 `awareness_paths` 机制做显式验证，不引入猜测式读写推断。

## Non-Goals

- 不为 25 增加基于启发式的自动读写分类。
- 不重构 Ralph 调度模型或 IPC 契约。

## Constraints

- 遵守 Debug-First，不增加 silent fallback。
- 修改应尽量局部，优先复用现有 plan loader / validator / test 结构。

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: Python 3
- **Test framework**: pytest

## Deliverables

- `src/cccc/ralph/models.py`
- `src/cccc/ralph/plan_io.py`
- `tests/ralph/test_plan_loader_ux.py`
- `tests/ralph/test_ralph_standalone.py`
- `todo/问题清单-v5-ralph.md`

## Done-When

- [ ] malformed `critical_flows` / `forbidden_flows` 给出明确报错
- [ ] `ForbiddenFlow`/`CriticalFlow` 非法额外字段不再静默吞掉
- [ ] `ralph complete` 依赖检查仍有测试覆盖
- [ ] 问题清单 23/24/26 不再作为“无改进空间局限”保留，25 明确为建模约束

## Final Validation Command

```bash
pytest tests/ralph/test_plan_loader_ux.py tests/ralph/test_ralph_standalone.py -q
```
