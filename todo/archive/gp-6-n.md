我先给结论：这份方案最有价值的地方，不是“列了很多 Phase”，而是已经把真正的根因抓出来了——问题不是某几个函数写错，而是**决策权边界、失败暴露机制、成功判据**一起偏了，所以系统才会自然滑向 silent fallback。文档把根因归纳为“负向不变量缺失、失败暴露通道缺失、成功判据偏向先跑通、现有测试编码了偏移行为”，这个判断我基本赞同。 

但如果按文档原样推进，我会对其中几处关键方案提出质疑。不是方向错，而是**有些设计会把这次修偏移，变成下一次新的偏移来源**。下面我按“认可点—质疑点—更合适方案”来讲。

## 我认可并建议保留的部分

第一，先把“Foreman 是唯一决策者”重新立起来，是对的。文档把目标架构明确成“Foreman 决策、Daemon 纯执行、Engine 做状态权威、Monitor 断言不变量”，这比继续在 orchestrator 里修补 fallback 逻辑正确得多。

第二，把问题从“正向流程描述”提升到“负向不变量”也对。像 `NO_SILENT_APPROVAL`、`FOREMAN_OWNS_ASSIGNMENT`、`NO_AUTO_DISPATCH` 这些约束，比“应该怎么做”更能防设计漂移。这个判断是全文最强的部分。

第三，文档意识到“现有测试编码了偏移行为”，这很关键。很多修复失败，不是代码没改，而是测试还在奖励旧行为。把这一点单独提出来，说明方案已经不是在表面 patch，而是在碰系统的真实约束。

---

## 我会明确质疑的 8 个点

### 1）我质疑：Phase 1 一上来就“监控+阻断”过重

文档里把 Phase 1 定义成运行时不变量断言层，并且“违规时阻断 + 结构化报错”。同时又承认此时偏移代码还在，5 个监控器部署后应该能检测到已知违规。

**质疑理由：**
如果你一边承认系统当前稳定路径本身就含违规，一边让监控器默认阻断，那么很容易出现两个问题：

* 监控层变成“新的业务逻辑入口”，自己开始决定什么能跑、什么不能跑；
* 还没完成修复，就先让生产路径大面积停住，逼团队为了恢复流转去给监控器加豁免，最后把监控器也污染成例外系统。

**我认为更合适的方案：**
把 Phase 1 拆成两个子阶段：

* **Phase 1A：Observe-only**
  只记录、不阻断。输出 violation ledger，建立当前违规基线。
* **Phase 1B：Selective enforce**
  只对最核心、最确定、最不可接受的两条做强制阻断：
  `NO_SILENT_APPROVAL`、`FOREMAN_OWNS_ASSIGNMENT`
* 其他不变量先告警，等 Phase 2/4 修完再转 enforce。

这样既能先拿到真实数据，又不让 monitor 过早变成“第二个 orchestrator”。

---

### 2）我质疑：`assignments: dict[task_id, actor_id]` 太薄，撑不起 INV-2

文档在 Phase 2 里把 ARCH-1 的修复定义为：`workflow submit` 增加 `assignments: dict[task_id, actor_id]`，贯穿 CLI → IPC → Engine。

**质疑理由：**
这只能表达“分给谁”，不能表达“为什么是这个人、由谁在何时依据什么约束做出这个决定”。但文档自己定义的 INV-2 是：**每个 assignment 必须溯源到 Foreman 的提交或决策事件**。
一个裸 `dict` 无法证明“assignment 溯源”，只能存结果，不能存决策来源。

**我认为更合适的方案：**
不要直接上 `dict`，而是引入最小 `AssignmentRecord`：

```text
task_id
actor_id
decision_id
decided_by          # foreman / user
decision_reason
constraint_snapshot
assigned_at
```

然后：

* CLI/IPC 传的是 `AssignmentRecord[]`
* Engine 持久化的是 `AssignmentRecord`
* Monitor 检查的是 `decision_id` 是否存在、是否属于 Foreman 决策事件链

这样 INV-2 才不是口号，而是可验证对象。

---

### 3）我质疑：Option Z 的“最多 2 次重试 + 最长 N 分钟”太像硬编码政策

文档把 ARCH-2 的重试协议定成 Option Z：Foreman 决策，但系统加两条安全轨道——最多 2 次重试、最长 N 分钟等待，超过就 BLOCKED。

**质疑理由：**
这个方向比系统自己编码重试策略好，但仍有两个风险：

* “2 次 / N 分钟”没有跟任务复杂度、成本、优先级绑定，很可能变成新的拍脑袋默认值；
* 系统虽不决定“怎么重试”，却决定“何时放弃”，本质上还是在偷偷接管一部分业务策略。

**我认为更合适的方案：**
把“安全轨道”改成**预算模型**，不要写死成全局常数。

建议最少分三类：

* `interactive`：默认 0 自动重试，快速抛回
* `normal`：允许 1 次重试或 1 次 actor 替换
* `expensive`：允许更长等待，但必须有人类确认

并且每次重试都必须生成新的 `decision_id`。
也就是说：**系统可以管理预算，但不能替 Foreman 生成下一步决策。**

---

### 4）我质疑：Phase 4 才解决 Engine 持久化 assignment，顺序偏晚

文档把 ARCH-4 放到 Phase 4：扩展 `TaskState` 持有 assignment 元数据、删除 `_active_workflows` 影子状态、做 schema 迁移。

**质疑理由：**
这和 Phase 2 的目标有冲突。Phase 2 说要恢复 Foreman 作为唯一 assignment 决策者，Phase 1 又要监控 assignment 是否溯源到 Foreman。可如果 assignment 直到 Phase 4 才进 Engine，那么 Phase 1/2/3 期间，系统还是在靠影子状态或旁路信息验证最核心的不变量。

换句话说：**你想先修“谁做决策”，但真正的决策记录却还没进入唯一权威。**

**我认为更合适的方案：**
把 ARCH-4 拆成“两段式”：

* **Phase 2 前移一个最小 schema 变更**
  先让 Engine 能存 `decision_id / actor_id / assigned_by`
* **Phase 4 再做完整收敛**
  再删除影子状态、补 `assignment_reason`、做迁移和清理

这样 Phase 2 修的不是“接口表面”，而是“系统权威位置”。

---

### 5）我质疑：Phase 3 的 Findings 提示词注入，容易变成“仪式化引用”

文档提出 Option A + C：在计划生成前、批次提交前、E2E 后注入 findings 检查问题；并在运行时做 finding 衍生行为断言。

**质疑理由：**
运行时断言我赞同，但**纯提示词注入**有一个老问题：AI 很容易学会“引用 finding 的格式”，而不是真的被约束。最后可能出现：

* 计划里机械写“我考虑了 Finding #16”
* 但实际结构没有 failure path
* 系统却因为“引用过了”而产生虚假安全感

这和文档自己批评的“findings 退化成事后解释库”其实是一条线上的问题。

**我认为更合适的方案：**
把 Findings 从 prompt 文本，升级成**结构化计划字段**，例如：

```yaml
finding_refs:
  - id: F16
    mitigation: "declare negative invariants"
    enforced_by: ["ralph:E_NO_NEGATIVE_INVARIANTS", "monitor:NO_SILENT_APPROVAL"]
  - id: F17
    mitigation: "explicit failure escalation"
    enforced_by: ["ipc:BatchAssignmentFailed"]
```

Ralph 校验的是：

* 是否引用了相关 finding
* 是否给了 mitigation
* mitigation 是否绑定到真实规则/监控/状态机

这样 finding 才是“可执行约束”，不是“语言层证明”。

---

### 6）我质疑：`reverse-check` 放在 Phase 5 太晚

文档自己承认一个上位矛盾：Ralph 验证的是静态计划，但执行是动态的，所以提出在 Phase 5 加 `reverse-check`，用计划中的 forbidden flows / 负向不变量去扫描执行日志。

**质疑理由：**
这其实不是“长期优化”，而是**最早应该补上的闭环**。
因为你前面所有 Phase 都在修运行时偏移，可直到 Phase 5 才给“事后审计执行轨迹”的工具，中间会有很长一段时间只能靠 monitor 的在线判断，没有离线复盘闭环。

**我认为更合适的方案：**
把 `reverse-check` 拆成两版：

* **Phase 2.5：最小版 reverse-check**
  只检查三件事：
  `NO_SILENT_APPROVAL` / `FOREMAN_OWNS_ASSIGNMENT` / `NO_AUTO_DISPATCH`
* **Phase 5：完整版 reverse-check**
  再支持 forbidden flows、verification 分类、finding 覆盖等

这样从修核心偏移开始，就有“在线监控 + 离线审计”双保险。

---

### 7）我质疑：评分标准校准说得对，但还不够具体，容易失焦

文档已经看到了“v4 的 3.3/5 部分得益于静默 fallback”，所以在 Phase 0 提出要把静默 fallback、自动审批、绕过 Foreman 的自动分配计负分，把正确阻塞并升级给 Foreman 计正分。

**质疑理由：**
这一步非常必要，但目前还是原则，不是可执行 rubric。
没有量化条目，后面很可能又会回到“happy path 更流畅，所以体验更高”的直觉打分。

**我认为更合适的方案：**
直接把评分改成“约束先于流畅”：

### 建议评分修订

**过程分（5 分）**

* 发现 silent fallback：-2
* 未经 Foreman 的 assignment：-2
* 影子状态驱动关键决策：-1
* 正确阻塞并发出结构化失败：+1
* 有审计链可追溯 decision_id：+1

**体验分（5 分）**

* 不因“少报错”加分
* 只因“边界清晰、原因可解释、恢复路径明确”加分

**结果分（5 分）**

* happy path 跑通但违反不变量，不得高于 2/5

这能把“跑通”从主目标改成“合规地跑通”。

---

### 8）我质疑：把 orchestrator 纯状态机重构放成“长期方向”，还缺触发条件

文档已经识别到上位矛盾：orchestrator 现在同时做执行和业务决策，长期应该变成纯状态机；但出于回归风险，暂时延后。

**质疑理由：**
延后本身没问题，但现在的写法容易无限延期。
因为“长期方向”如果没有触发条件，现实中常常会变成“大家都知道该做，但永远还有更紧急的修补”。

**我认为更合适的方案：**
把“是否启动纯状态机重构”改成硬触发规则。比如：

满足任一条件就立项：

1. Phase 4 后仍有任一 invariant 违规来源于 orchestrator 内分支；
2. 一个新功能需要同时改 orchestrator、monitor、engine 三处才能维持决策边界；
3. assignment / retry / readiness 三类事件仍有任一类无法只靠 Engine 权威还原。

这样不是“看感觉决定重构”，而是“达到阈值就必须做”。

---

## 我建议的更稳版本：把原方案改成 6 步，但调整顺序和颗粒度

### A. 评分与契约先落地

保留 Phase 0，但补两样：

* 评分 rubric 量化
* `AssignmentRecord` 契约先定义

### B. 监控先影子运行，不先强阻断

先 Observe-only，拿真实违规分布，再只强制最核心两条不变量。

### C. 核心修复时，先把 assignment 写进 Engine

不要只改 submit 接口；先让 Engine 成为 assignment 的最小权威。

### D. 立刻加最小 reverse-check

不等到 Phase 5，核心偏移修完就要有离线轨迹审计。

### E. Findings 结构化，不只靠 prompt

Prompt 可以保留，但它只能做提醒，不能做约束主体。约束主体必须是：

* 计划字段
* Ralph 规则
* runtime monitor
* reverse-check

### F. 纯状态机重构设硬触发条件

不要写成“将来考虑”，要写成“达到什么条件就启动”。

---

## 如果让我直接改写这份方案，我会把核心结论压缩成一句话

**这次不是“修 fallback”，而是“把决策事件、失败事件、assignment 事件全部收回到可追溯的权威链里”。**

所以最合适的主线不是：

> 先监控 → 再修若干点 → 再补审计

而应该是：

> **先定义可追溯决策契约 → 监控影子运行 → 修核心权力边界 → 立刻补执行轨迹审计 → 再做 findings 与验证体系增强**

---

最后给你一个最短判断：

这份文档的**诊断**基本是对的，
这份文档的**Phase 方向**大体也是对的，
但它目前最大的不足是：**有些地方还停留在“原则正确”，没有把原则落成最小可验证的数据结构与审计闭环。**
尤其是 assignment 的表示、monitor 的启用方式、reverse-check 的时机、findings 的结构化落地，这四个点我建议优先重写。

如果你愿意，我下一步可以直接把这份方案重写成一版“更适合执行的 v6”，按“保留 / 删除 / 前移 / 后移”四栏给出可替换文本。
