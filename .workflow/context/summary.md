# 

## 关键决策

- 创建 Ralph Daemon Python 骨架 [REMEMBER] 使用 asyncio 事件循环 + gitpython 实现 Git 轮询监控 [DECISION] 采用 typer CLI 框架，事件通过 MessageBus pub/sub 模式分发 [ARCHITECTURE] GitWatcher 轮询检测新提交 -> MessageBus 发布 GitCommitEvent -> 订阅者异步处理
- 实现 Ralph-Daemon IPC 协议 [REMEMBER] 复用现有 daemon Unix socket + JSON line 协议架构，通过 try_handle_ralph_op 模式集成到 request_dispatch_ops [DECISION] 使用 Pydantic 模型定义消息格式（ReadyBatchSuggestion, VerificationResult, RestartSuggestion, BatchDecision, ActorStatus），内存存储 IPC 状态
- 完成 Capability 改造：添加 prompt_fragments 字段和 Prompt 模板组装逻辑，禁用 MCP Server 自动启用 [REMEMBER] Capability 使用 prompt_fragments 字典按角色(foreman/peer/common)存储 Prompt 片段，build_actor_prompt() 函数根据角色自动组装完整系统提示 [DECISION] prompt_fragments 采用角色分组设计（common+role-specific），保持向后兼容，新字段可选 [ARCHITECTURE] Capability 契约位于 contracts/v1/capability.py，Prompt 组装逻辑在 capability_ops/_prompt_builder.py
- 实现动态 Agent 系统：Agent 合约定义 (ModelCapability, Agent, ModelRegistry, AgentSet)、Agent CRUD 操作 (create/get/list/update/delete)、Prompt 动态组装 (build_agent_prompt 复用 capability_ops)、模型选择 (select_model_for_task)。[REMEMBER] Agent 由 Foreman 动态创建，定义存储为 YAML 在 .cccc/agents/；ModelRegistry 在 .cccc/models/registry.yaml 定义模型能力；Agent role_type (worker/reviewer/specialist) 映射到 capability prompt 的 peer 角色 [DECISION] Agent 定义存储为 YAML 文件在 .cccc/agents/，便于版本控制和复用；model 字段使用嵌套结构 {runtime, model_id} 保持 YAML 可读性 [ARCHITECTURE] Agent -> Capability -> Prompt 组装链：Agent.capabilities 列表 → 加载 Capability YAML → build_agent_prompt 调用 cap.get_prompt_for_role() 组装完整 Prompt
- 实现 Ready-Batch 调度器 [REMEMBER] 拓扑排序+DFS 检测环路，防止死锁；使用 set 收集下游任务避免重复计数 [DECISION] 支持 critical_path/shortest_first/fifo 三种优先级策略，默认 critical_path [ARCHITECTURE] DependencyGraph 管理任务依赖 -> compute_ready_batch 计算优先级排序的批次 -> IPC 发送建议给 Daemon；IPC 支持 Unix socket 和 HTTP 双通道
- 实现 Actor Controller，处理 Ralph 的重启建议和批次决策 [REMEMBER] Daemon 保持 Authority，可拒绝 Ralph 建议（如资源不足、超过重启次数）[DECISION] 采用建议-决策模式，非强制执行；ActorController 通过依赖注入集成现有 Actor 生命周期管理 [ARCHITECTURE] Ralph 发送建议 -> ActorController 评估（检查重启次数、系统资源、并行度限制）-> 决定是否执行 -> 返回状态
- 实现 Foreman 角色 [REMEMBER] Foreman 是唯一对外协调者，可动态创建 Agent，使用 receive_batch -> evalu

[...truncated 1688 chars...]

Ralph
- [backend] Foreman 角色实现: 实现 Foreman 角色 [REMEMBER] Foreman 是唯一对外协调者，可动态创建 Agent，使用 receive_batch -> evalua
- [backend] 验证器实现: 实现验证器模块 [REMEMBER] 验证分三层：构建/测试（必选）、任务状态（推荐）、反馈生成（辅助）。BuildTestValidator 并行执行 bui
- [backend] Feishu 进度上报: 实现 Feishu 进度上报模块 [REMEMBER] ProgressReporter 支持 6 种关键事件类型：batch_started、task_com
- [general] 端到端测试与文档: 完成端到端测试和操作手册 [REMEMBER] E2E 测试覆盖完整工作流周期，包含 6 个测试类、30+ 测试用例 [DECISION] 操作手册采用渐进式结
- [general] 修复工作流相关测试文件: 归属工作流相关的测试和配置文件变更 [REMEMBER] 这些文件在工作流执行期间被间接修改以兼容新架构
- [general] 更新 gitignore 以允许 .cccc/roles: 更新 .gitignore 添加 .cccc/roles 例外规则 [REMEMBER] 角色定义文件需要版本控制
