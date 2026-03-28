# task-008: 验证器实现

实现验证器模块 [REMEMBER] 验证分三层：构建/测试（必选）、任务状态（推荐）、反馈生成（辅助）。BuildTestValidator 并行执行 build/test/lint 命令，TaskStateChecker 检查 .cccc/actors/{id}/state.json，FeedbackGenerator 跟踪重试次数并生成 retry/escalation 消息 [DECISION] 使用 asyncio.create_subprocess_shell 执行命令支持 shell 语法；验证结果通过现有的 VerificationResult IPC 消息发送给 CCCC Daemon [ARCHITECTURE] GitCommit -> parse METADATA -> BuildTestValidator.validate() -> TaskStateChecker.check() -> FeedbackGenerator.generate() -> send VerificationResult via IPC
