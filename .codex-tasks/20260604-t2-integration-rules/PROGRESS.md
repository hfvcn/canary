# Progress

- 2026-06-04: 建立任务目录并完成首轮静态核对。三条规则已在 `validation_rules/__init__.py` 的导入、`get_all_rules()`、`__all__` 中注册，也已在 `validator.py::_collect_structural_issues()` 被调用。
- 2026-06-04: 在 `tests/test_integration_call_evidence.py`、`tests/test_forbidden_flow_field.py`、`tests/test_status_code_drift.py` 中补充 `validate()` 集成断言；其中 `test_integration_call_evidence.py` 额外显式校验了三条规则在 `get_all_rules()`、`__all__` 以及 `_collect_structural_issues()` 中的接线。
- 2026-06-04: 定向测试 `python -m pytest tests/test_integration_call_evidence.py tests/test_forbidden_flow_field.py tests/test_status_code_drift.py -v` 通过，结果为 `18 passed in 1.06s`。
- 2026-06-04: 回归测试 `python -m pytest tests/ralph/ -q` 在 60 秒限制内完成，结果为 `763 passed in 11.77s`。
