# T10 RV-54 状态机并发安全校验

## Objective

在 Ralph 安全校验规则中新增状态机并发安全检测：识别状态机类任务，并要求其在验收标准、verification checks 或 mock_tests 中至少有一层体现并发安全证据。

## Scope

- 修改 `src/cccc/ralph/validation_rules/security.py`
- 新增 `src/cccc/ralph/validation_rules/security_state_machine.py`
- 接入 `src/cccc/ralph/validation_rules/__init__.py` 与 `src/cccc/ralph/validator.py`
- 新增 `tests/ralph/test_concurrency_safety.py`
- 运行 `pytest tests/ralph/test_concurrency_safety.py -v`
