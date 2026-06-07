# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- 在 `src/cccc/daemon/foreman/workflow_evaluation.py` 增加基于 `test_output` 的 randomization 检测兜底逻辑。
- 保持未传 `test_output` 时的行为与当前实现完全一致。
- 新增 `tests/test_workflow_eval_randomization.py` 覆盖 T5 验收标准。

## Non-Goals

- 不修改其他调用点。
- 不改变 `_workflow_evaluation_test_stats` 的返回结构。

## Constraints

- 只改用户指定文件。
- 现有 randomized check 逻辑必须原样优先。

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: Python
- **Test framework**: pytest

## Deliverables

- `src/cccc/daemon/foreman/workflow_evaluation.py`
- `tests/test_workflow_eval_randomization.py`

## Done-When

- [ ] T5 指定的 4 个场景均有测试覆盖且通过。

## Final Validation Command

```bash
python -m pytest tests/test_workflow_eval_randomization.py -v
```
