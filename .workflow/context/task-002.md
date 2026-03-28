# task-002: Daemon IPC 协议

实现 Ralph-Daemon IPC 协议 [REMEMBER] 复用现有 daemon Unix socket + JSON line 协议架构，通过 try_handle_ralph_op 模式集成到 request_dispatch_ops [DECISION] 使用 Pydantic 模型定义消息格式（ReadyBatchSuggestion, VerificationResult, RestartSuggestion, BatchDecision, ActorStatus），内存存储 IPC 状态
