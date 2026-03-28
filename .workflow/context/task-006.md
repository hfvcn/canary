# task-006: Actor Controller

实现 Actor Controller，处理 Ralph 的重启建议和批次决策 [REMEMBER] Daemon 保持 Authority，可拒绝 Ralph 建议（如资源不足、超过重启次数）[DECISION] 采用建议-决策模式，非强制执行；ActorController 通过依赖注入集成现有 Actor 生命周期管理 [ARCHITECTURE] Ralph 发送建议 -> ActorController 评估（检查重启次数、系统资源、并行度限制）-> 决定是否执行 -> 返回状态
