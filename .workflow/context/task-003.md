# task-003: Capability 改造

完成 Capability 改造：添加 prompt_fragments 字段和 Prompt 模板组装逻辑，禁用 MCP Server 自动启用 [REMEMBER] Capability 使用 prompt_fragments 字典按角色(foreman/peer/common)存储 Prompt 片段，build_actor_prompt() 函数根据角色自动组装完整系统提示 [DECISION] prompt_fragments 采用角色分组设计（common+role-specific），保持向后兼容，新字段可选 [ARCHITECTURE] Capability 契约位于 contracts/v1/capability.py，Prompt 组装逻辑在 capability_ops/_prompt_builder.py
