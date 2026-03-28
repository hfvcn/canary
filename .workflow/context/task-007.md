# task-007: Foreman 角色实现

实现 Foreman 角色 [REMEMBER] Foreman 是唯一对外协调者，可动态创建 Agent，使用 receive_batch -> evaluate_pool -> assign_tasks 工作流 [DECISION] 采用 Prompt 层控制 Feishu 访问权，通过 ForemanWorkflow 类统一管理批次处理 [ARCHITECTURE] AgentPoolManager 负责 Agent 评估/创建/复用，workflow.py 实现完整批次处理流程包含 Feishu 通知
