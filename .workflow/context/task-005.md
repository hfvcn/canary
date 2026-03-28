# task-005: Ready-Batch 调度器

实现 Ready-Batch 调度器 [REMEMBER] 拓扑排序+DFS 检测环路，防止死锁；使用 set 收集下游任务避免重复计数 [DECISION] 支持 critical_path/shortest_first/fifo 三种优先级策略，默认 critical_path [ARCHITECTURE] DependencyGraph 管理任务依赖 -> compute_ready_batch 计算优先级排序的批次 -> IPC 发送建议给 Daemon；IPC 支持 Unix socket 和 HTTP 双通道
