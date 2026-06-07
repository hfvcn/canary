# Task T21: AF 引擎端到端集成测试

## Goal
创建 `tests/agentflow/test_af_e2e_integration.py`，覆盖 AF 引擎从编译到执行的完整链路、workflow 隔离、verification covers 保留、状态回调、缺失依赖报错、legacy 委派和 AF 安全回退。

## Acceptance
- 新增测试文件覆盖用户列出的 7 个场景。
- 定向运行 `python -m pytest tests/agentflow/test_af_e2e_integration.py -v` 通过。
- 不修改与本任务无关的业务逻辑。
