# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- 为 forbidden flow 测试文件扫描增加“出现但未做负向断言”的三态检测。
- 在 `coverage.py` 中新增 `W_FORBIDDEN_FLOW_FIELD_ASSERTION_MISSING` 告警码。
- 新增定向测试覆盖 asserted / seen / unseen / mutually-exclusive / fallback 场景。

## Non-Goals

- 不改动 forbidden flow 字段提取规则。
- 不重构其他 validation rule 或 unrelated warning 逻辑。

## Constraints

- 保留 `W_FORBIDDEN_FLOW_FIELD_UNCOVERED` 现有语义。
- `W_FORBIDDEN_FLOW_FIELD_UNTESTED` 仅表示测试文件里字段完全未出现。
- `project_root` 不可用时保持回退，不引入新的 silent fallback 语义。

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Test framework**: `pytest`

## Deliverables

- `src/cccc/ralph/validation_rules/coverage.py`
- `tests/ralph/test_forbidden_flow_assertion.py`

## Done-When

- [ ] `_has_field_negative_assertion` 实现负向断言上下文检测
- [ ] `_untested_forbidden_flow_fields` 输出 unseen / seen_without_negative_assert / asserted 三态结果
- [ ] `pytest tests/ralph/test_forbidden_flow_assertion.py -v` 通过
