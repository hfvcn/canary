整体判断：这份方案最有价值的地方，是它已经把问题从“某几个 bug”提升成了“决策权漂移、失败暴露缺失、负向不变量缺失”这三个系统级问题来看；这个诊断方向我基本认同。尤其是把 `silent fallback`、`assignment` 溯源、Phase 化回滚、Findings 主动约束放到主线上，这比继续补局部逻辑要正确得多。

但我会对几个关键点提出质疑，而且其中有几处我认为必须改，不然方案本身会再制造一轮新的复杂度。

## 一、我最想质疑的 7 个点

### 1）“Foreman 是唯一决策者”这个表述太硬，应该改成“Foreman 是唯一授权源”

文档现在的表述，容易把系统推到“每一个 ready task 都要同步回问 Foreman 一次”的模式。这样做短期能止住漂移，长期却会带来三个副作用：吞吐量下降、Foreman 成为单点延迟源、系统一旦 Foreman 响应慢就重新诱发 silent fallback 的冲动。

更合适的做法不是放弃 Foreman 主导权，而是把“决策”拆成两层：

* **价值判断/授权** 归 Foreman
* **在授权边界内的机械执行** 归 Daemon

也就是说，Foreman 可以显式提交：

* 逐任务 assignment
* 或一个**受限授权策略**：允许哪些 actor、允许的调度策略、TTL、attempt budget、是否允许 ready 后自动释放

这样一来，真正应该禁止的不是 `NO_AUTO_DISPATCH`，而是 **`NO_UNAUTHORIZED_DISPATCH`**。
只要任务是按照一个仍然有效、可审计、可溯源的 Foreman 授权释放的，就不算越权。

---

### 2）Phase 1 的 monitor 不应该一上来就“阻断”，应该先 shadow mode

文档 Phase 1 里写的是“违规时阻断 + 结构化错误”，这在理念上对，但在落地上过猛。因为 monitor 本身也是新代码，新断言器在没经过充分校验前就进入控制面，很容易把“真实架构缺陷”和“监控误报”混在一起。

更稳的方式是三段式：

* **observe**：只记录、不拦截
* **warn**：标红 E2E、影响评分，但不阻断
* **block**：只对已经证明误报极低的高严重度不变量启用

我建议：

* Phase 1：5 个不变量全部 `observe`
* Phase 2：`INV-1 / INV-2` 升到 `block`
* Phase 4：其余不变量再升到 `block`

这样你们先拿到完整 trace，再让监控真正接管。

---

### 3）ARCH-6 / 7 / 8 被放到 Phase 5，我认为优先级判断错了

这是我最强烈的质疑点。

文档把下面三项放得比较后：

* `assignment_id / actor_run_id` 透传（ARCH-6）
* `DEFERRED` 进入 Engine（ARCH-7）
* `retry_after_verification()` 清理旧 agent_id（ARCH-8）

但这三项其实不是“收尾优化”，而是前面几阶段能不能成立的基础：

**ARCH-6 不前移，Phase 1 的 monitor 和 Phase 2 的 assignment 溯源就很难被证明。**
没有 assignment_id / actor_run_id / decision_id，`FOREMAN_OWNS_ASSIGNMENT` 只能靠猜。

**ARCH-7 不前移，等待 Foreman 决策这件事仍然会落在 orchestrator 影子状态里。**
这直接违背你们自己写的 `ASSIGNMENT_PERSISTED` 和 Engine 权威化目标。

**ARCH-8 不前移，Option Z 的 retry 协议就不安全。**
清掉旧 `agent_id` 还不够，真正要做的是引入 `attempt_id / assignment_version`，否则旧 worker 的迟到完成消息还会污染新一轮状态。

我的建议是：

* ARCH-6 移到 **Phase 1**
* ARCH-7、ARCH-8 移到 **Phase 2**
* 只有 ARCH-5（`--worker-prompt`）留在后面比较合理

---

### 4）“Phase 0 让 5 个负向不变量测试全部红掉”可以作为发现手段，但不适合作为常态 CI

文档 Phase 0 的验收是“5 个测试存在且全部红色”。这个动作适合拿来证明“现在确实有漂移”，但不适合变成主干分支上的日常状态。因为一旦红灯是“预期中的”，团队很快会对红灯失去感觉。

更稳的方案是：

* 把这些测试放进单独套件，比如 `tests/invariants/`
* 用 `xfail(strict=True)` 或 phase expectation matrix 管理
* 明确写出每个阶段哪些测试应当 `xfail`、哪些应当 `pass`

这样 Phase 2 时 `INV-1 / INV-2` 从 xfail 变 green，Phase 4 时全部 green，信号会更清晰，也不会污染主 CI。

---

### 5）核心不变量不能只靠 monitor 检测，必须下沉到 Engine transition guard

文档现在很重视 runtime monitor，这是对的；但只靠 monitor 还不够。原因是 monitor 常常是“事后发现”，而很多违规一旦已经发生，外部副作用可能已经产生。

更合适的防线应该是三层：

1. **Schema / contract 层**：没有关键字段就不允许过
2. **Engine transition guard**：非法状态转换在入口处直接拒绝
3. **Monitor / reverse-check**：作为第二道和第三道审计防线

举例：

* `rejected -> approved` 不应由 monitor 发现，而应由 Engine 明确拒绝，除非附带新的 `ForemanDecision(decision_id)`
* `task complete` 必须携带当前 `assignment_version`
* 老版本 worker 的迟到消息直接丢弃，不进入状态机

所以我建议把“监控层”改成“**监控 + transition guard**”双轨，而不是只补一个 monitor。

---

### 6）Findings 激活如果只靠 prompt 注入，很容易变成“仪式化引用”

文档很准确地指出 Findings 现在是被动文档，不是主动约束；这个判断我完全同意。问题在于，后面给出的 A/C/D 路线如果处理不好，会让 AI 学会“引用 Finding 编号”，而不是“真的受约束”。

比“强制引用 Finding ID”更好的方式，是把 Findings 结构化成一个 registry：

* `finding_id`
* `stage_tags`：plan / submit / retry / migration / evaluation
* `trigger_conditions`
* `required_evidence`
* `runtime_signal`
* `enforcement_mode`：prompt / guard / monitor / accepted-risk

然后在关键时刻不是问“你参考了哪个 finding”，而是要求填写证据字段：

* F16：你的 forbidden transition 是什么
* F17：失败如何显式暴露给 Foreman
* F15：迁移如何证明旧路径已下线
* F18：这轮成功信号里，哪些可能是虚假繁荣

这样 Findings 才会从“知识库”变成“约束接口”。

---

### 7）你们现在只有 safety invariants，没有 liveness invariants

文档里的 5 个不变量几乎全是“不能做什么”，这很重要；但工作流系统还需要回答“多久之内必须有结果”。否则 silent fallback 被拿掉以后，系统可能不越权了，却开始默默卡住。

我建议再补两条：

* **`EVENTUAL_VISIBILITY`**：每个 task 必须在 SLA 内进入 `done / failed / blocked` 之一，并带明确 owner
* **`BOUNDED_ESCALATION`**：无 actor、Foreman 不响应、verify 长时间不结束，都必须在边界时间内升级，而不是悬空等待

这两条会直接改善你们在开放问题里提到的“阻断粒度”和“重试参数”问题。

---

## 二、我认为更合适的目标架构

我会把目标架构从“Foreman 全同步审批 + Daemon 纯执行”微调成下面这个版本：

### 1）Decision Ledger + Engine Projection

* **Decision Ledger**：append-only，存所有 `decision_id / causation_id / correlation_id / assignment_version`
* **Engine**：当前状态的唯一投影，不负责保存完整历史
* **Orchestrator**：只负责驱动 transition，不保存业务影子状态

这比“Engine 既是状态权威又是 assignment 双权威”的表述更清楚。
当前状态是一回事，历史溯源是另一回事，最好不要混成一个概念。

### 2）原生状态机必须显式支持等待决策

我建议至少有这样一条主路径：

`READY -> AWAITING_ASSIGNMENT -> ASSIGNED(v3, decision_id=D17) -> RUNNING(run_id=R5) -> VERIFYING(attempt=3) -> DONE`

异常路径：

* 无匹配 actor：`AWAITING_ASSIGNMENT -> BLOCKED_AWAITING_FOREMAN`
* verify fail：`VERIFYING -> READY`，同时 `attempt_id++`
* 旧 worker 迟到上报：因为 attempt/version 不匹配，被丢弃

这比“DEFERRED 先放 orchestrator，之后再补到 Engine”稳得多。

### 3）把“自动”改成“可审计授权内的自动”

* 自动释放 ready task：可以，但必须已有有效授权
* 自动创建 worker：不可以，除非是 Foreman 预先批准过的 actor template
* 自动 retry：只允许对**明确标记为 transient** 的错误类型执行

---

## 三、我建议你们重排 Phase

### Phase 0

保留评分校准，但补一件更重要的事：**先统一事件/决策 ID 模型**。
没有 `decision_id / assignment_id / actor_run_id / attempt_id / causation_id`，后面很多“不变量”其实是不可证的。

### Phase 1

做两件事，不要只做 monitor：

1. trace recorder / decision ledger
2. shadow-mode workflow monitor

同时把 **ARCH-6 前移**。

### Phase 2

做真正的 P0 修复，但范围比原文略大：

* ARCH-1：submit 带 assignments / policy
* ARCH-2：删 silent fallback
* ARCH-7：Engine 增加 `AWAITING_ASSIGNMENT / BLOCKED`
* ARCH-8：引入 `attempt_id / assignment_version`

这里不要只“清理旧 agent_id”，那只是表面修复。

### Phase 3

处理 ARCH-4，但不要直接删影子状态。
更稳的是先 **dual-write**：

* orchestrator 继续写旧影子状态
* 同时写 Engine 新状态
* monitor 比对两边一致性
* 连续若干轮 E2E 一致后再切流删除 `_active_workflows`

这比一次性切换安全得多。

### Phase 4

再做 Ralph 规则增强和 Findings registry。
而且 `forbidden_flows` 不够，建议扩展成：

* forbidden transition
* required provenance
* exclusivity
* cleanup obligation
* liveness bound

### Phase 5

再上 reverse-check、CLI 易用性、`--worker-prompt` 之类的工程化收尾。

---

## 四、对文档里 6 个开放问题，我的直接答案

### 1）Findings 注入颗粒度

不要“全量注入”，也不要靠 LLM 自己猜最相关。
用 rule-based selector：按 `stage_tags + object_tags + severity` 选 **最多 3 条**。默认保底注入 F16、F17。

### 2）Foreman 重试参数

不要固定“最多 2 次 + N 分钟”。
按失败类型分层更合理：

* `NoCompatibleActor`：默认不自动重试，直接等 Foreman
* `ActorUnavailable / rate limit`：1~2 次退避
* `Verification flake`：1 次
* `Transport error`：短重试窗口

### 3）监控阻断粒度

分三级：

* **A 级**：决策权越权、状态污染、版本错配 —— 立即阻断当前 workflow
* **B 级**：缺 provenance、影子状态不一致 —— 阻断相关 branch，不必全局停
* **C 级**：monitor 不确定性高 —— 只告警，不阻断

### 4）哪些 Phase 子任务可并行

可并行的是：

* 文档/评分规则/测试标记
* monitor 的 observe 实现
* ledger schema 定义

不要并行的是：

* state schema 迁移
* fallback 移除
* assignment authority 变更
* shadow state 切流

### 5）何时启动 orchestrator 纯状态机重构

我会设一个触发条件，而不是按时间排：

* 到 Phase 4 结束后，orchestrator 里仍存在 2 个以上“业务判断分支”
* 或 monitor 在两轮 E2E 中仍抓到未经授权的决策行为

满足任一条，就该正式启动纯状态机重构。

### 6）评分标准怎么改

我会这样改：

* **过程分**：出现一次 `unauthorized approval / dispatch / actor creation`，本轮过程分上限直接封顶到 1/5
* **结果分**：如果 happy path 依赖越权兜底跑通，结果分最高 2/5
* **体验分**：一次必要且结构化的升级，不扣分；反复、无行动选项的打断才扣分

这样“正确阻塞”才会真正比“静默跑通”更高分。

---

## 五、最值得立刻改的，不是更多规则，而是这三件事

1. **把 decision / assignment / attempt 的 ID 体系立起来**
2. **把等待决策和重试版本化放进 Engine 原生状态**
3. **把 `NO_AUTO_DISPATCH` 改成 `NO_UNAUTHORIZED_DISPATCH`**

这三件事一做，文档里的很多 Phase 才会从“方向正确”变成“真的可执行”。

这份方案的主诊断我赞成，但我不建议按原顺序直接开工；我会先重排优先级，再把“Foreman 唯一决策者”改写成“Foreman 唯一授权源”，这样既能保住你们最重视的决策边界，也不至于把系统推成一个高摩擦、低吞吐、强依赖同步审批的新瓶颈。
