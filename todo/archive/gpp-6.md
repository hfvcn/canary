**VERDICT**: `needs-attention`

**SUMMARY**: 基于上传的方案文本，这版不该现在放行。它识别到了设计偏移，但仍把几个关键安全属性排在依赖它们的改动之后：Phase 2 先上线 Foreman 异步重试/重新分配协议，Phase 5 才补 `assignment_id/actor_run_id` 透传；Phase 2 先暴露 `submit.assignments`，Phase 4 才让 Engine 成为 assignment 权威；Phase 4 做持久化状态 schema 迁移，但回滚方案只有 git tag。对一个多阶段、异步、会重试的工作流系统，这会直接留下重复派发、陈旧响应覆盖当前决策、以及回滚后在途 workflow 无法恢复的风险。 

**FINDINGS**:

* **[severity: critical] Phase 2 的异步重试协议先于 attempt 身份透传，上线后无法防止陈旧响应重放**

  * File: `8c5ac0db-c2e0-49d2-a000-1066f9073060.md`, lines 377–389, 463–469
  * Confidence: 0.93
  * Body: Phase 2 的 Option Z 让 daemon 发出 `BatchAssignmentFailed`，再由 Foreman 异步回复结构化动作；这本质上引入了一个会超时、会重试、会乱序到达的协议。但文档把 `assignment_id/actor_run_id` 在 handler 管道中的透传（ARCH-6）放到了 Phase 5 才修。这意味着系统会先拥有“重试/重新决策”能力，却还没有一个端到端的 attempt 标识去把 Foreman 的回复绑定到“哪一次失败、哪一次分配尝试”。一旦出现 Foreman 延迟回复、用户重提交流程、daemon 先把任务转成 `BLOCKED`，旧回复仍可能命中当前状态并触发重复派发、重复创建 actor，或把已经结束的批次重新打开。这是典型的乱序/幂等性漏洞，而且正好落在你要修复的信任边界上。
  * Recommendation: 把 ARCH-6 前移到 Phase 2。任何 `BatchAssignmentFailed` 通知和 Foreman 决策都必须携带 `workflow_id`、`task_id`、`assignment_attempt_id` 和 `state_version`，并在 Engine/Orchestrator 侧做 compare-and-swap 校验；不匹配当前 attempt 的回复一律拒绝，且在拿到这些 ID 之前不要启用 Option Z。

* **[severity: high] Phase 2 提前开放 `submit.assignments`，但 assignment 仍然不是 Engine 的权威状态**

  * File: `8c5ac0db-c2e0-49d2-a000-1066f9073060.md`, lines 135–138, 371–375, 443–445
  * Confidence: 0.91
  * Body: 方案在 Phase 2 就要让 `workflow submit` 增加 `assignments` 并“贯穿 CLI → IPC → Engine”，同时宣称“没有任何任务分配发生在 Foreman 显式 submit 之外”。但文档自己又明确把 ARCH-4 放到 Phase 4：Engine 仍然缺 assignment 存储，orchestrator 仍维护 `_active_workflows` 影子状态。也就是说，在 Phase 2/3 的整个窗口里，系统会接受 Foreman 做出的 assignment 决策，但 durable state machine 还不是这些 assignment 的单一权威。只要发生 daemon 重启、`retry_after_verification()`、状态读取走 Engine 而不是 shadow state，assignment provenance 就可能丢失、旧 `agent_id` 被带回，或者 workflow 对“谁被授权执行这个 task”给出错误答案。把 INV-1/2 先做绿、把 INV-5 留到 Phase 4，不是安全的中间态。
  * Recommendation: 不要在 Engine 持久化 assignment provenance 之前把 `submit.assignments` 作为正式路径上线。最少也要把不可变的 assignment record（如 `assigned_by`、`assigned_at`、`assignment_attempt_id`）前移到 Phase 2，所有读路径先切到 Engine，再通过 feature flag 逐步移除 `_active_workflows`。

* **[severity: high] Phase 4 有持久化 schema 迁移，但“回滚方案”只有代码 tag，无法保护在途 workflow**

  * File: `8c5ac0db-c2e0-49d2-a000-1066f9073060.md`, lines 443–451, 542–543
  * Confidence: 0.89
  * Body: Phase 4 要扩展 `TaskState`、删除 `_active_workflows`，文档也承认这里涉及 JSON 持久化状态的 schema 迁移，需要版本号、迁移路径和向后兼容。但给出的回滚检查点只是 `git tag pre-phase4`。这不是有效的回滚：代码可以回退，已经写入的新状态不会自动回退。只要 Phase 4 部分上线、写过新格式 state，再回滚到旧代码，就可能出现旧代码无法反序列化、忽略关键字段、或错误恢复在途 workflow 的问题。事故时你想依赖的“回滚”本身会制造第二次事故：workflow 卡死、assignment provenance 丢失，甚至因为部分状态被误读而发生重复调度。
  * Recommendation: 把存储兼容性提升为 Phase 4 的硬门槛，而不是附注。至少要有 versioned serializer、old-code/new-data 的兼容读策略（或 dual-write / lazy migration）、活跃 workflow 的快照/恢复流程，以及一次演练过的“带在途 workflow 的回滚 drill”。

**NEXT STEPS**

* 把 `assignment_id/actor_run_id`、attempt correlation、以及状态版本校验前移到 Phase 2，先补幂等性再上 Foreman 异步重试。
* 把 assignment 的最小持久化前移到 Engine，同一阶段完成读路径收口；在 `_active_workflows` 仍是权威之前，不要宣称 Foreman assignment 修复已经成立。
* 给 Phase 4 增加真实的数据回滚与兼容计划，并用“有在途 workflow 的回滚演练”作为上线前门槛。

