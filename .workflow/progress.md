# 

状态: finishing
当前: 无
开始: 2026-03-19T09:58:20.895Z

| ID | 标题 | 类型 | 依赖 | 状态 | 重试 | 摘要 | 描述 | 阶段 | 最近更新 | 阶段进展 |
|----|------|------|------|------|------|------|------|------|----------|----------|
| 001 | Ralph Daemon 骨架 (Python) | backend | - | done | 0 | 创建 Ralph Daemon Python 骨架 [REMEMBER] 使用 asyncio 事件循环 + gitpython 实现 Git 轮询监控 [DE | 创建 ralph/ 项目结构：pyproject.toml, ralph/main.py (CLI 入口), ralph/git_watcher.py (Git 提交监控), ralph/message_bus.py (事件总线)。参考 gitcortex 的 git_watcher 实现。 | - | - | - |
| 002 | Daemon IPC 协议 | backend | - | done | 0 | 实现 Ralph-Daemon IPC 协议 [REMEMBER] 复用现有 daemon Unix socket + JSON line 协议架构，通过 tr | 在 CCCC Daemon 侧实现 IPC 端点。定义消息格式：ready_batch_suggestion, verification_result, restart_suggestion, batch_decision, actor_status。使用 Unix socket 或 HTTP。 | - | - | - |
| 003 | Capability 改造 | backend | - | done | 0 | 完成 Capability 改造：添加 prompt_fragments 字段和 Prompt 模板组装逻辑，禁用 MCP Server 自动启用 [REMEM | 修改 src/cccc/contracts/v1/capability.py，添加 prompt_fragments 字段。修改 capability_ops.py 实现 Prompt 模板组装逻辑。移除 CCCC MCP Server 自动启用逻辑。 | - | - | - |
| 004 | 动态 Agent 系统 | backend | 003 | done | 0 | 实现动态 Agent 系统：Agent 合约定义 (ModelCapability, Agent, ModelRegistry, AgentSet)、Agent | 创建 src/cccc/contracts/v1/agent.py 和 daemon/ops/agent_ops.py。实现模型能力注册表 (.cccc/models/registry.yaml)，Agent 定义存储/加载，Agent CRUD API，Prompt 动态组装。 | - | - | - |
| 005 | Ready-Batch 调度器 | backend | 001,002 | done | 0 | 实现 Ready-Batch 调度器 [REMEMBER] 拓扑排序+DFS 检测环路，防止死锁；使用 set 收集下游任务避免重复计数 [DECISION] | 在 ralph/scheduler/ 实现：dep_graph.py (依赖图分析), ready_batch.py (批次计算)。通过 IPC 发送 ready_batch_suggestion 给 Daemon。支持优先级策略配置。 | - | - | - |
| 006 | Actor Controller | backend | 001,002 | done | 0 | 实现 Actor Controller，处理 Ralph 的重启建议和批次决策 [REMEMBER] Daemon 保持 Authority，可拒绝 Ralph | 在 src/cccc/daemon/ 创建 actor_controller.py。处理 Ralph 的建议（restart_suggestion 等），执行 Actor 控制（启动/停止/重启）。集成到现有 Actor 生命周期管理。 | - | - | - |
| 007 | Foreman 角色实现 | backend | 004,005 | done | 0 | 实现 Foreman 角色 [REMEMBER] Foreman 是唯一对外协调者，可动态创建 Agent，使用 receive_batch -> evalua | 编写 .cccc/roles/foreman.md Prompt。实现 Foreman 工作流：接收 ready_batch、评估 Agent Pool、创建/复用 Agent、分配任务。集成 Feishu 通信能力。 | - | - | - |
| 008 | 验证器实现 | backend | 001,006 | done | 0 | 实现验证器模块 [REMEMBER] 验证分三层：构建/测试（必选）、任务状态（推荐）、反馈生成（辅助）。BuildTestValidator 并行执行 bui | 在 ralph/validator/ 实现：build_test.py (构建/测试验证), task_file.py (任务状态检查), feedback.py (失败消息反馈)。通过 IPC 发送 verification_result。 | - | - | - |
| 009 | Feishu 进度上报 | backend | 007 | done | 0 | 实现 Feishu 进度上报模块 [REMEMBER] ProgressReporter 支持 6 种关键事件类型：batch_started、task_com | 创建 src/cccc/daemon/foreman/progress_report.py。实现阶段性进度汇总、Feishu 卡片消息模板、关键事件通知（完成、失败、需要介入）。 | - | - | - |
| 010 | 端到端测试与文档 | general | 007,008,009 | done | 0 | 完成端到端测试和操作手册 [REMEMBER] E2E 测试覆盖完整工作流周期，包含 6 个测试类、30+ 测试用例 [DECISION] 操作手册采用渐进式结 | 编写 tests/e2e/test_ralph_workflow.py 集成测试。编写 docs/operating_playbook.md 操作手册（启动、配置、故障排查）。试运行并修复问题。 | - | - | - |
| 011 | 修复工作流相关测试文件 | general | - | done | 0 | 归属工作流相关的测试和配置文件变更 [REMEMBER] 这些文件在工作流执行期间被间接修改以兼容新架构 | - | - | - | - |
| 012 | 更新 gitignore 以允许 .cccc/roles | general | - | done | 0 | 更新 .gitignore 添加 .cccc/roles 例外规则 [REMEMBER] 角色定义文件需要版本控制 | - | - | - | - |
