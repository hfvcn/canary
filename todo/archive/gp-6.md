**VERDICT**: `needs-attention`

**SUMMARY**: 这份方案已经识别出核心偏移，但按现在的分期和机制设计，还不够安全到可以直接推进：它把新的异步决策通道提前引入，却把关联标识传递放到更后面；它要在持久化状态上做 source-of-truth 迁移，却只给了 git tag 级别回滚；它把运行时监控描述成“立即检测并阻断”，但实现位置仍是 orchestrator 旁路监听，且允许按检查项关闭。对一个已经出现 silent fallback、影子状态和自动分配漂移的系统，这些都是真实的高成本失效点。

**FINDINGS**:

* **[severity: critical]** 新的 Foreman 异步决策链路缺少关联/version 语义，重复消息和过期回复会把错误决策应用到错误状态

  * File: `4cb2b955-d04a-4818-9499-61892540c9a5.md`, lines 371–389, 443–449, 467–469
  * Confidence: 0.96
  * Body: Phase 2 要把 `_fallback_to_group_actors()` 改成 `BatchAssignmentFailed` 异步消息，Phase 4 又新增 `TasksReadyForAssignment` 异步通知，让 Foreman 事后回复分配决策；但直到 Phase 5 才补 `assignment_id/actor_run_id` 在 handler 管道中的传递。也就是说，方案打算先上线新的“请求-响应式重新分配”控制面，再晚一个 phase 才补齐最基础的关联标识。这样一来，只要出现超时重发、重复投递、Foreman 延迟回复、或 task 在等待期间已被别的路径推进，系统就没有被明确设计出的 compare-and-swap / 去重 / 版本校验手段来拒绝陈旧决策。结果不是简单“再试一次”，而是可能重复启动 worker、把旧回复应用到新状态、或把错误 batch 从 BLOCKED/READY 推进到执行态。  
  * Recommendation: 把 `assignment_id`/`actor_run_id`/`workflow_version` 前移到 Phase 2，作为所有 `BatchAssignmentFailed` 和 `TasksReadyForAssignment` 请求与回复的强制字段；Engine 接受 Foreman 决策时必须做版本匹配和一次性消费，拒绝重复或过期回复。没有这层幂等/版本保护，不应引入新的异步分配回路。

* **[severity: high]** 持久化状态迁移的回滚设计停留在代码回退，不能保护正在运行或已写盘的 workflow 状态

  * File: `4cb2b955-d04a-4818-9499-61892540c9a5.md`, lines 295–296, 311–312, 444–451, 542–543
  * Confidence: 0.93
  * Body: 文档自己承认此前“没有回滚计划”，随后给出的补救主要是“每个 Phase 前打 git tag”。但 Phase 4 明确要把 assignment 元数据并入 `TaskState`、删除 `_active_workflows` 影子状态，并对现有 JSON 持久化状态做 schema 迁移。这不是单纯的代码变更，而是 source of truth 的迁移：一旦新版本开始写入新结构，单靠回滚代码到旧 tag 并不能恢复旧代码可理解的状态，更不能保证正在运行的工作流不会被卡死、误判或丢失 assignment。风险表虽然写了“需要版本号 + 迁移路径 + 向后兼容”，但方案没有把这些定义成发布前置条件，也没有提出双写/双读、备份快照、或 downgrade 测试。对状态机系统，这属于真实的数据兼容性缺口。   
  * Recommendation: 把迁移安全升级为 Phase 4 的硬门槛：定义状态版本字段、可重复执行的迁移器、发布前持久化快照、至少一个版本窗口的双读兼容，外加“新版本写入后回退到旧版本”演练。没有经过 downgrade 测试验证的迁移，不应与删除影子状态一起上线。

* **[severity: high]** 运行时监控被设计成旁路监听且可关闭，无法真正保证“违规会被立即检测并阻断”

  * File: `4cb2b955-d04a-4818-9499-61892540c9a5.md`, lines 341–359, 481–485
  * Confidence: 0.89
  * Body: Phase 1 把 `workflow_monitor` 定义为“作为事件监听器接入 WorkflowOrchestrator，违规时阻断 + 结构化错误”，同时又明确写出“如果监控器误报过多，可以通过配置开关关闭单个检查”。这意味着关键不变量并没有被下沉到 Engine 的状态转换或 IPC 接受边界，而仍然是 orchestrator 旁边的一层可选守卫。对已经确认存在 silent approval、auto dispatch、shadow state 的系统，这个位置过晚：如果非法状态先在 orchestrator/engine 中被写入，再由监听器发现，回滚和恢复就已经复杂化；如果生产上因噪音关闭检查，又会重新回到“先违规、后发现”的老路。文档自己也承认 orchestrator 里仍可能残留隐式决策，且“纯状态机”要到后续阶段才考虑，这进一步放大了该风险。 
  * Recommendation: 把 INV-1/2/4/5 这类发布阻断级不变量直接做成 Engine/IPC 边界上的硬拒绝，monitor 只负责告警和审计；生产环境不允许关闭 critical invariant checks。否则这层“监控”更像告警系统，不是防止状态污染的控制面。

**NEXT STEPS**:

* 先把异步决策链路的关联 ID、版本号和幂等接收语义提前到 Phase 2，再讨论 `BatchAssignmentFailed` / `TasksReadyForAssignment` 上线。
* 把 Phase 4 的 schema 迁移改成“有 downgrade 演练的状态迁移方案”，不是“打 tag 可回滚”。
* 把关键不变量从 monitor 下沉到 Engine/IPC 写入路径，禁止以配置开关绕过生产保护。
