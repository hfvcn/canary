# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- 用真实写盘的 `plan.yaml` 验证 Ralph 近期改动是否在正确时机触发
- 覆盖用户最直接的操作链：`validate`、计划变更后的 completion guard、`validate --diff`

## Non-Goals

- 不扩展到与 `plan.yaml` 直驱无关的底层单元测试
- 不重写已有 Wave 1-10 测试

## Constraints

- 必须真实写出 `plan.yaml` 文件而不是只用内存对象
- 优先复用现有 CLI / orchestrator 路径，不新增仓库测试文件
- 验收范围保持小而完整

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: `Python 3.11`
- **Package manager**: `setuptools / pip`
- **Test framework**: `pytest`
- **Build command**: `pytest`
- **Existing test count**: `按目标 smoke 文件定向执行`

## Risk Assessment

- [x] Breaking changes to existing code — 需要复用已有接口而非再造逻辑
- [ ] External dependencies (APIs, services) — 无
- [ ] Large file generation — 无
- [ ] Long-running tests — 控制为单次脚本化验收

## Deliverables

- 一个真实写盘的 `plan.yaml` fixture 目录
- 一次 CLI / orchestrator 直驱验收记录

## Done-When

- [ ] 真实 `plan.yaml` 能证明新增检查只在计划变更后触发，且 stale digest 只在完成时阻断

## Final Validation Command

```bash
PYTHONPATH=src python -m cccc.ralph.cli validate .codex-tasks/20260417-ralph-plan-yaml-smoke/fixture/project/plan.yaml --project-root .codex-tasks/20260417-ralph-plan-yaml-smoke/fixture/project --format json
```
