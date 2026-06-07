# PROGRESS

- 已创建任务骨架。
- 已确认 `coverage.py` 的 `_check_forbidden_flows`、`_covering_tasks_for_flow` 以及 `security.py` 的 token 匹配模式。
- 已新增 `_check_forbidden_flow_field_coverage`、`_extract_forbidden_flow_fields`、`_verification_text_surfaces`。
- 已将新规则接入 `validator.py` 与 `validation_rules/__init__.py`。
- 为 `_covering_tasks_for_flow` 增加 `entrypoints` 缺省兼容，支持 `ForbiddenFlow` 复用同一 helper。
- 已新增 4 个场景的回归测试并通过目标验证。
- 已补齐 `W_FORBIDDEN_FLOW_FIELD_UNCOVERED` 的 `covering_task_ids` evidence，并显式展开 `mock_tests` 文本 surface。
- 当前定向验证结果：`tests/test_forbidden_flow_field.py` 与 `tests/ralph/test_validation_test_creator_failed.py` 共 `10 passed`。
