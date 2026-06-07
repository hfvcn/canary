# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- 扩展 forbidden flow 字段提取规则，识别反引号外的隐式字段模式。
- 在 forbidden flow 字段覆盖校验中增加基于测试文件内容的第二层校验。
- 新增定向测试，覆盖字段提取与 `W_FORBIDDEN_FLOW_FIELD_UNTESTED` 告警分支。

## Non-Goals

- 不重构其他 validation rule。
- 不调整 forbidden flow 以外的 coverage 规则语义。

## Constraints

- 保留现有 `W_FORBIDDEN_FLOW_FIELD_UNCOVERED` 语义，用于 verification text 表层覆盖。
- 新增 `W_FORBIDDEN_FLOW_FIELD_UNTESTED`，用于测试文件内容层覆盖。
- 文件读取仅通过传入的 `project_root` 进行。

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: `Python 3.11.7`
- **Package manager**: `pip`
- **Test framework**: `pytest 8.4.2`
- **Existing test count**: `490`

## Deliverables

- `src/cccc/ralph/validation_rules/coverage.py`
- `tests/ralph/test_forbidden_flow_field_coverage.py`

## Done-When

- [ ] `_extract_forbidden_flow_fields` 支持 `role=admin`、`is_admin`、`MUST NOT accept|allow|permit X`
- [ ] `_check_forbidden_flow_field_coverage` 支持 `project_root` 下的测试文件内容扫描
- [ ] `python -m pytest tests/ralph/test_forbidden_flow_field_coverage.py -v` 通过

## Final Validation Command

```bash
python -m pytest tests/ralph/test_forbidden_flow_field_coverage.py -v
```
