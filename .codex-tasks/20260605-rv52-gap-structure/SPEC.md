# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- 更新 `src/cccc/ralph/flow_engine.py` 的 step-4 gap check，支持结构化字段校验。
- 在 capability 关键词通过时输出结构建议，但不改变无关键词时的失败行为。
- 在 `tests/ralph/test_flow_engine.py` 增加 `test_gap_structure_` 回归测试并验证。

## Non-Goals

- 不调整 step-4 以外的 flow 步骤语义。
- 不回退当前工作区里与本任务无关的未提交改动。

## Constraints

- 保持现有 gap capability gate 为第一道检查。
- 仅在目标文件与任务记录目录内做增量修改。

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: Python
- **Test framework**: pytest

## Deliverables

- `src/cccc/ralph/flow_engine.py`
- `tests/ralph/test_flow_engine.py`
- `.codex-tasks/20260605-rv52-gap-structure/`

## Done-When

- [x] `_check_gap_record` 在 capability 通过后提供结构化建议但不阻塞通过。
- [x] `test_gap_structure_*` 覆盖完整结构、缺 `issue_id`、无关键词三种场景。
- [x] `pytest tests/ralph/test_flow_engine.py -v -k gap_structure` 通过。

## Final Validation Command

```bash
pytest tests/ralph/test_flow_engine.py -v -k gap_structure
```
