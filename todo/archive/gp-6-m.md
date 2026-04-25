**VERDICT**: `needs-attention`

**SUMMARY**: 基于当前提供的上下文，我看到的是一份架构修正方案而不是实现代码；按这份方案原样推进，还不足以支撑“可以安全落地”的结论。最大问题不是方向错，而是几个关键安全边界仍未被定义成可执行契约：Phase 2 对“Foreman 独占分配权”的完成条件写得过满，Phase 1 的监控器会在已知漂移仍存在时先行阻断但没有定好阻断/恢复语义，新的异步决策回路也没有幂等与过期响应约束，另外把 failure-path 仅做 warning 与文档自己给出的根因分析是冲突的。  

**PRIMARY FINDINGS**:

* **[severity: high]** Phase 2 对“Foreman 已重新拿回分配权”的声明过度，实际仍保留一条自动分配路径

  * File: `优化路径方案-v5.md`, lines 367-375, 437-445
  * Confidence: 0.96
  * Body: Phase 2 的不变量声明写的是“没有任何任务分配发生在 Foreman 显式 submit 之外”，并把 INV-1/INV-2 视为在该阶段变绿；但文档后面又明确把 ARCH-3（后续批次 `_resuggest_ready_tasks()` 绕过 Foreman 自动分配）留到 Phase 4 才修。也就是说，系统在 Phase 2 完成后仍然存在“非 Foreman 显式决策触发 assignment”的运行路径，只是从初始 submit 场景收窄到了 DAG 解锁场景。这个阶段性表述会制造错误的完成感，最直接的后果是测试和验收很容易只覆盖首批任务，遗漏后续 ready task 仍可自动派发的高成本回归。 
  * Recommendation: 要么把 Phase 2 的不变量改窄，明确只涵盖“初始 submit assignment”；要么把 ARCH-3 一并前移，使“Foreman owns assignment”在所有 assignment 入口同时收口后再宣布 INV-2 通过。

* **[severity: high]** Phase 1 监控器被要求在已知违规仍存在时“立即阻断”，但阻断语义和恢复路径仍未定义

  * File: `优化路径方案-v5.md`, lines 341-359, 541-542, 556-556
  * Confidence: 0.93
  * Body: 文档要求 Phase 1 先于修复部署，并明确说“由于偏移代码还在，5 个监控器应该能检测到已知的违规行为”；同时 P1-B 要求“违规时阻断 + 结构化错误”。但后面的开放问题又承认：到底是首个违规就阻断，还是累计到阈值才阻断，以及阻断后的恢复路径是什么，都还没定。这个缺口不是实现细节，而是决定监控层是“安全网”还是“自我 DoS”的核心行为。若按当前字面落地，最可能的结果只有两个：要么监控器一上线就在现有漂移路径上持续打断 workflow；要么因为误报/噪音被快速关掉单项检查，导致监控层失去约束力。  
  * Recommendation: 先把监控 rollout 语义补齐，再推进实现：至少定义 observe-only、warn、fail-closed 三档；为每个不变量定义默认级别；补一个显式恢复路径（例如 unblock/retry command）；只有在影子观测期证明信号稳定后，才允许切到阻断模式。

* **[severity: high]** 新的 Foreman 异步决策回路没有幂等/过期响应契约，重复消息会把 assignment 再次做脏

  * File: `优化路径方案-v5.md`, lines 371-389, 443-447
  * Confidence: 0.84
  * Body: Phase 2 引入 `BatchAssignmentFailed` 请求—Foreman 回复结构化动作，Phase 4 再引入 `TasksReadyForAssignment` 异步通知；但文档只规定了“最多 2 次重试 + 最长 N 分钟总等待”，没有规定 request/response 的唯一标识、attempt 编号、状态前置条件、超时后迟到响应如何处理。真实故障下，重复投递、Foreman 延迟回复、旧响应晚到、用户重试并发发生都很常见；没有幂等与 stale reply 规则时，系统可能把同一 ready set 分配两次、在任务已 BLOCKED 后又接受旧决策、或者既创建新 actor 又应用放宽约束重试，直接破坏 assignment 的单写语义和审计链。这个风险正落在文档最敏感的边界：authority handoff。 
  * Recommendation: 在协议层补齐 `request_id` / `attempt` / `workflow_version` / `decision_id`；所有 Foreman 回复必须带上“我在回应哪一次请求”；Engine 只在状态版本匹配时接受决策，过期/重复响应一律拒绝并记录。

* **[severity: medium]** 文档把“失败路径缺失”认定为根因，但编译期只给 `W_NO_FAILURE_PATH` warning，约束强度不够

  * File: `优化路径方案-v5.md`, lines 125-126, 169-171, 405-407
  * Confidence: 0.91
  * Body: 文档自己把“失败暴露通道缺失”列为深层根因，并且把 Finding #17 定义为“失败不能显式抛回决策者，系统会自然滑向 silent fallback”。在这种前提下，Phase 3 却把“依赖外部 actor 的任务必须声明分配失败时的处理方式”只做成 warning。也就是说，新的计划仍可在没有 failure-path 的情况下通过，只是得到一个提示。这会把同一类设计压力重新留在系统里：当 happy path 压力上来时，AI 或实现很容易再次选择“先跑通”，而不是补 failure channel。  
  * Recommendation: 把 `W_NO_FAILURE_PATH` 至少提升为对“涉及 assignment / external actor / async decision”的任务的 hard error；若确有例外，要求显式 accepted-risk 注记，而不是默认放行。

**STRUCTURAL PRESSURE TEST**:

* **[type: sequencing]** 把 `ASSIGNMENT_PERSISTED` 监控放在 Phase 1，会把安全层绑到即将删除的影子状态上

  * Grounding: `优化路径方案-v5.md`, lines 353-357, 444-445
  * Why it matters: 文档要求在 Phase 1 就部署 `ASSIGNMENT_PERSISTED`，但真正把 assignment 放进 Engine、删除 `_active_workflows` 影子状态要到 Phase 4。也就是说，预修复监控若想“看见”这个不变量，很可能不得不去读取或理解影子状态本身。这样安全层会与过渡态模型耦合，到了 Phase 4 反而需要先改监控器，增加迁移面和误判面。 
  * Better shape: 把该检查拆成两段：Phase 1 只检查“assignment provenance 不应只存在于 orchestrator 私有变量而无审计事件”；等 Phase 4 完成后，再启用真正的“assignment persisted in Engine”硬断言。
  * Confidence: 0.88

* **[type: authority]** 方案是在“按入口修 assignment”，不是在“按统一决策契约修 assignment”

  * Grounding: `优化路径方案-v5.md`, lines 371-372, 385-389, 443-447
  * Why it matters: 初始提交用 `assignments: dict[task_id, actor_id]`，分配失败用 `BatchAssignmentFailed`，后续 DAG 解锁又新增 `TasksReadyForAssignment`。这意味着同一个 authority boundary 被拆成多个消息形态和多套交互语义，未来极容易再次出现某一条路径补了安全轨道、另一条路径没补，重新形成漂移。  
  * Better shape: 统一成一个 assignment decision contract：无论是初始 submit、无匹配重试、还是 ready task 释放，都走同一套 `AssignmentRequested -> AssignmentDecided/Declined` 协议、相同的幂等规则、相同的 timeout/blocked 处理。
  * Confidence: 0.87

**NEXT STEPS**:

* 先重写 Phase 2 的完成条件，不要在 ARCH-3 仍存时声称“Foreman owns assignment”已恢复。
* 在实现前补一页协议规范：消息 ID、attempt、状态版本、超时后旧回复处理、BLOCKED 后可否解封。
* 给 Phase 1 监控定义明确 rollout：观测期、告警期、阻断期，以及每档的恢复动作。
* 把 `W_NO_FAILURE_PATH` 提升为关键路径上的 hard gate；否则这份方案会再次把根因降级成“提醒”。
