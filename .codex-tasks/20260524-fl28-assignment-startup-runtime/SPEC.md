# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- 在 `assignment_startup` 中识别 `actor_add` 后的运行态停滞，并优先尝试 `actor_restart`
- 保持现有 legacy start 回退路径，仅在需要时触发
- 为 stall / 正常运行 / restart 失败回退补充单元测试

## Non-Goals

- 不重构 foreman 启动链路的其他模块
- 不改变 `actor_add` / `actor_restart` 协议定义

## Constraints

- 保持 Debug-First，不引入静默降级
- 使用现有 `DaemonRequest` / daemon request 流程
- 运行指定 pytest 用例验证

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: `Python`
- **Package manager**: `N/A`
- **Test framework**: `pytest`

## Deliverables

- `src/cccc/daemon/foreman/assignment_startup.py`
- `tests/test_assignment_startup.py`

## Done-When

- [ ] stall actor 会触发 restart
- [ ] running actor 不会触发 restart 或 legacy start
- [ ] restart 失败时回退到 legacy start

## Final Validation Command

```bash
python -m pytest tests/test_assignment_startup.py -v -k "runtime_stall or verify_actor"
```
