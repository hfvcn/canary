# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- 在 Ralph 中新增 `failure_path` 字段与 `W_NO_FAILURE_PATH` 结构校验。
- 为指定测试文件补充 4 个覆盖用例并通过目标 `pytest` 命令。

## Non-Goals

- 不改动 Ralph IPC 合同。
- 不处理 T20 之外的剩余计划项。

## Constraints

- 仅编辑用户指定的 3 个文件。
- 保留工作树中既有未提交改动，不做回滚。

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: Python
- **Test framework**: pytest

## Deliverables

- `src/cccc/ralph/models.py`
- `src/cccc/ralph/validator.py`
- `tests/test_ralph_verification.py`

## Done-When

- [ ] `failure_path` 字段可被 `TaskSpec` 解析。
- [ ] `W_NO_FAILURE_PATH` 在指定场景触发/静默。
- [ ] `python -m pytest tests/test_ralph_verification.py -x -q` 通过。

## Final Validation Command

```bash
python -m pytest tests/test_ralph_verification.py -x -q
```
