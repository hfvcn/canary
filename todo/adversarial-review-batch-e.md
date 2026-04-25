**VERDICT**: `no-ship` → 修正后 `ship`

**SUMMARY**: Codex（GPT-5.4）对 Batch E plan 进行了静态审查，给出 6 个发现（1 critical + 4 high + 1 medium），原始 verdict 为 `no-ship`。所有 5 个可操作的发现已被采纳并修正到计划中。

**PRIMARY FINDINGS**:

- **[severity: critical, confidence: 0.98]** `unauthorized_subagent` hook 绑定 `_task_to_agent` volatile shadow state
  - **问题**: `_task_to_agent` 是 orchestrator 运行时影子映射，daemon 重启后为空。BLOCK 模式下会误拒合法 agent。
  - **修正 (C1)**: 改用 `self.group.doc["actors"]` 持久化 actor registry。Lambda 从 group 文档读取 actor 列表，重启后可用。

- **[severity: high, confidence: 0.99]** `block_task(cascade=True)` 只返回 `List[str]`，无法区分 RUNNING 任务
  - **问题**: Engine cascade 后所有 task 已变 BLOCKED，orchestrator 无法知道谁原来在 RUNNING（需发取消通知）。
  - **修正 (C2)**: 返回 `List[Dict]`，每项含 `{task_id, previous_status, blocked_reason}`。Orchestrator 据 `previous_status == "running"` 发通知。

- **[severity: high, confidence: 0.96]** Hook fail-open：unexpected exception 被 `logger.debug` 静默吞掉
  - **问题**: Hook 自身 bug 会静默放行非法转换，最危险的失败模式。
  - **修正 (C5)**: 改为 `logger.warning`（非 debug），提高可观测性。不阻塞转换（仍 fail-open）但可被监控发现。

- **[severity: high, confidence: 0.94]** Hook 内直接写 ledger，与 transition 事件无事务绑定
  - **问题**: OBSERVE 模式下 hook 先写 MONITOR_VIOLATION，engine 再写 transition。transition 写失败时 ledger 残留无对应状态的 violation。
  - **修正 (C3)**: Hook 不写 ledger。通过 `engine.report_hook_alert()` 缓存。Engine 在 transition 之后 flush violation 事件。顺序保证：transition → violation。

- **[severity: high, confidence: 0.95]** T5 删除 `on_task_completed()` 中的 monitor checks 会回归 WF-6
  - **问题**: `record_verification_warning`（WF-6）依赖 `on_task_completed` 中的 `check_completer_mismatch`。删除后 WF-6 行为丢失，现有测试回归。
  - **修正 (C4)**: 保留 `on_task_completed` 中所有现有 monitor checks 和 WF-6 verification_warning。OBSERVE 模式下会有冗余记录（可接受），Batch F 统一清理。

- **[severity: medium, confidence: 0.91]** T2-T5 验证命令指向尚不存在的测试名
  - **处理**: 已知限制，与 Batch D 模式一致。测试将由各 task 创建。
