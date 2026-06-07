# Task Specification

> Scope anchor for the task. Update only when goals or constraints change, and log the reason in PROGRESS.md.

## Task Shape

- **Shape**: `single-full`

## Goals

- 运行 `python -m pytest --timeout=120 -x -q` 做全量回归验证。
- 若出现失败，定位根因并修复到测试重新通过。
- 最终确认全量结果为 `0 failed`。

## Non-Goals

- 不处理与当前失败无关的历史脏改动。
- 不主动做额外重构或非必要测试扩展。

## Constraints

- 遵守仓库 `AGENTS.md` 与 Debug-First 策略。
- 只修改与失败根因直接相关的代码或测试。
- 最终验证命令必须使用用户指定的 pytest 命令。

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: `Python 3.11.7`
- **Package manager**: `pip/pyproject`
- **Test framework**: `pytest`
- **Build command**: `python -m pytest --timeout=120 -x -q`
- **Existing test count**: `508 test files`

## Risk Assessment

- [x] Breaking changes to existing code — impact assessed via full regression.
- [x] Long-running tests — timeout configured in command.
- [ ] Hidden environment dependencies may affect unrelated suites.
- [ ] Existing dirty worktree may overlap touched files.

## Deliverables

- 必要的代码或测试修复。
- 成功的全量 pytest 验证结果。
- T15 运行摘要。

## Done-When

- [ ] `python -m pytest --timeout=120 -x -q` 结果为 `0 failed`。
- [ ] 如有失败，根因已分析并修复。

## Final Validation Command

```bash
python -m pytest --timeout=120 -x -q
```
