1. [backend] Ralph Daemon 骨架 (Python)
   创建 ralph/ 项目结构：pyproject.toml, ralph/main.py (CLI 入口), ralph/git_watcher.py (Git 提交监控), ralph/message_bus.py (事件总线)。参考 gitcortex 的 git_watcher 实现。

2. [backend] Daemon IPC 协议
   在 CCCC Daemon 侧实现 IPC 端点。定义消息格式：ready_batch_suggestion, verification_result, restart_suggestion, batch_decision, actor_status。使用 Unix socket 或 HTTP。

3. [backend] Capability 改造
   修改 src/cccc/contracts/v1/capability.py，添加 prompt_fragments 字段。修改 capability_ops.py 实现 Prompt 模板组装逻辑。移除 CCCC MCP Server 自动启用逻辑。

4. [backend] 动态 Agent 系统 (deps: 3)
   创建 src/cccc/contracts/v1/agent.py 和 daemon/ops/agent_ops.py。实现模型能力注册表 (.cccc/models/registry.yaml)，Agent 定义存储/加载，Agent CRUD API，Prompt 动态组装。

5. [backend] Ready-Batch 调度器 (deps: 1, 2)
   在 ralph/scheduler/ 实现：dep_graph.py (依赖图分析), ready_batch.py (批次计算)。通过 IPC 发送 ready_batch_suggestion 给 Daemon。支持优先级策略配置。

6. [backend] Actor Controller (deps: 1, 2)
   在 src/cccc/daemon/ 创建 actor_controller.py。处理 Ralph 的建议（restart_suggestion 等），执行 Actor 控制（启动/停止/重启）。集成到现有 Actor 生命周期管理。

7. [backend] Foreman 角色实现 (deps: 4, 5)
   编写 .cccc/roles/foreman.md Prompt。实现 Foreman 工作流：接收 ready_batch、评估 Agent Pool、创建/复用 Agent、分配任务。集成 Feishu 通信能力。

8. [backend] 验证器实现 (deps: 1, 6)
   在 ralph/validator/ 实现：build_test.py (构建/测试验证), task_file.py (任务状态检查), feedback.py (失败消息反馈)。通过 IPC 发送 verification_result。

9. [backend] Feishu 进度上报 (deps: 7)
   创建 src/cccc/daemon/foreman/progress_report.py。实现阶段性进度汇总、Feishu 卡片消息模板、关键事件通知（完成、失败、需要介入）。

10. [general] 端到端测试与文档 (deps: 7, 8, 9)
    编写 tests/e2e/test_ralph_workflow.py 集成测试。编写 docs/operating_playbook.md 操作手册（启动、配置、故障排查）。试运行并修复问题。
