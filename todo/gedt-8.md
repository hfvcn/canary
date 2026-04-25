### 1. 执行摘要 (Executive Summary)

这是一份工程纵深极深、极具务实性的加强方案。Claude 与 Codex 的拉锯有效过滤了“传统静态代码洁癖”，直击了当前 LLM Agent 架构的核心痛点：**状态漂移（State Divergence）**与**上下文黑洞（Context Blackhole）**。

然而，作为独立审查者，我发现本方案在数据流向的最后一公里存在严重的**“人类中心主义视角错位”**。最关键的 3 个发现：
1. **#1 的防线存在致命漏洞**：仅靠 Warn-only 无法阻止被污染的完成态写入 Ledger，将直接导致后期的 Audit 脑裂。
2. **截断与路由策略的灾难**：#2 和 #10 沿用给人类看的严重度（Error > Warning）来喂给 LLM，且采用硬截断，必然导致 Worker 产生执行幻觉。
3. **并发调度与负向契约盲区**：方案修补了跨 Workflow 冲突，却漏掉了同图无向节点的隐式并发踩踏；校验了负面清单，却从未将其注入 Worker 的脑子里。

本方案大方向极佳，但必须打上以下安全补丁后方可执行。

---

### 2. 维度 1 · 方案评审

#### 2.1 核心 5 项深度审查 (直面 Q1-Q4)
*   **#1 `W_REGISTERED_PLAN_STALE`**
    *   ⚠️ **ENDORSE WITH CAVEAT**
    *   *红队推演 (Q1)*：Detect-only **绝对不安全**。如果作者无视告警（或没看到控制台），继续让 Foreman 下发任务，Worker 汇报完成时，`cccc task complete` 会将基于旧拓扑的成果强行写入新 Plan 对应的 Ledger 中。这不仅是 divergence，这是不可逆的账本污染。
    *   *修正要求*：保持 `validate` 时告警以防破测，但在 `ralph complete` 或 state sync 接口进行**硬拦截 (Hard Block)**——强制校验运行时 `plan_digest`，不匹配则拒绝标记完成（Exit code 1），除非显式传入 `--force-stale-complete`。
*   **#2 Prompt Task Issue Digest**
    *   ⚠️ **ENDORSE WITH CAVEAT**
    *   *红队推演 (Q2)*：`error > warning > hint` 的 Inclusion policy 错得离谱。Error 往往是结构合规错（如 `CMP-1` 未知流、覆盖率不足），这是给人类（Plan 作者）看的，干活的 Worker 无权修改 `plan.yaml`。喂给它 Error 会导致它擅自生成 python 脚本去强改 yaml。
    *   *修正要求*：必须改为基于 **Worker Actionability (执行可干预度)** 排序。`S_*` (语义错位) 和 `W_VERIFICATION_*` (行为不符) 必须置顶。屏蔽所有纯结构校验 Issue。
*   **#10 Prompt Budgeter**
    *   ⚠️ **ENDORSE WITH CAVEAT**
    *   *红队推演 (Q3)*：单纯的 Size Cap 和 Section Truncation 会导致大模型“失明”。截断 Context 会引起幻觉，截断 Digest 会导致重复犯错。
    *   *修正要求*：采用**降维压缩 (Degradation)** 而非硬截除。当预算触顶时，将 Semantic Context 从“全量源码”降维成“仅暴露类/函数签名”；将 Issue Digest 从“完整 message”降维成“Code + 核心行动词”。截断处必须显式注入 `[SYSTEM: CONTEXT DEGRADED DUE TO TOKEN LIMIT]` 消除 LLM 脑补错觉。
*   **#5 `W_VERIFY_PASSED_BUT_SEMANTIC_INCONSISTENT`**
    *   ⚠️ **ENDORSE WITH CAVEAT**
    *   *红队推演 (Q4)*：动态语言下 Provider 的推断必然存在 Opaque Confidence，极易变成“狼来了”。
    *   *修正要求*：必须引入置信度阈值机制。若信心指数低，自动降级为 Hint；且必须在 `plan.yaml` 的 Suppress 体系中要求附带 `reason` 字段才能被豁免此高价值警告。
*   **#7 Structured Internal Failure Envelope**
    *   ✅ **ENDORSE**。Exit code 2 的隔离极为优雅，这是成熟自动化基建的标志。

#### 2.2 其余 18 项与 Codex 争议项复核
*   **其余 18 项**：✅ **全面 ENDORSE**。其中 `R-1`（确定性排序）和 `CMP-6` 是收益极高的高杠杆改动。
*   **对 Ledger Schema (Q5) 的判决**：绝对不要做双向兼容迁移。直接强拉 `schema_version`（协同 R-2'），`ralph audit` 遇到旧格式使用安全 Fallback。AI 基建历史包袱越早丢越好。
*   **Codex 砍掉的 8 项**：认同砍掉其中 7 项（低信噪比的代码洁癖），但 **❌ 必须救回 `CMP-8 finding_refs 关系语义`**。如果 Plan 声明 `finding_refs: ["ISSUE-1"]`，但没有任何一个 task 的 `addresses` 指向它，这就是虚假契约，只需做一次集合差验证即可低成本拦截。
*   **Codex 拒绝的 4 个方向**：✅ **完全认同 Codex**。
    *   *强化 Incremental Validate 的拒绝*：Ralph 的 `core.py` 中的 write-set projection 意味着局部节点的改变会导致全局并发锁和连通图推导结果的震荡。在 Python 处理几百行 YAML 的几十毫秒开销面前，维护缓存 Invalidation Matrix 是极度得不偿失的过早优化。

---

### 3. 维度 2 · 没想到的新方向 (Tier 1-3)

以下建议完全避开方案已有项，锚定并发、状态与契约盲区：

#### 🏆 Tier 1 ("Huh, good catch" 级别盲区)
**1. 并发调度写踩踏：`E_CONCURRENT_WRITE_COLLISION`**
*   **Kind**: DAG 核心结构规则
*   **动机**: #8 解决了跨 Workflow 的写压力，但漏了**系统内部**！如果同 Plan 下的 Task A 和 Task B 没有 `depends_on` 边（Foreman 将并行执行它们），且它们的 `claimed_paths` 有交集。两个 LLM Worker 会在同一刻重写同一个文件，引发致命的竞态覆盖。
*   **落地约束**: 纯静态图分析，找出拓扑同层可并发的节点组，对其 `claimed_paths` 求交集。

**2. 负向契约不入脑：`Prompt: Forbidden Flows Injection`**
*   **Kind**: Data Flow (Worker 侧注入)
*   **动机**: `plan.yaml` 有 `forbidden_flows`，Ralph 在静态时校验了它，但 Foreman 的 `_build_task_prompt` 压根没把它拼进提示词！Worker 完全不知道“什么是系统不允许做的”，处于闭眼走雷区状态。
*   **落地约束**: 从 Plan 顶层投影 `forbidden_flows` 描述，到目标任务组装出专门的 `[Forbidden Actions]` XML 块注入 Prompt。

**3. 状态图时序倒置：`E_STATE_TOPOLOGY_INVERSION`**
*   **Kind**: 状态一致性校验
*   **动机**: 验证 Ledger 与 DAG 的物理因果律。如果 Task A depends_on Task B，但在 Ledger 中 Task A 已进入 `completed_task_ids`，而 Task B 还在 `failed_task_ids` 甚至 `running_tasks` 中，说明历史记录被篡改或发生脑裂。
*   **落地约束**: 交叉校验 `plan.state` 的归属类别与 DAG 拓扑连通路径。

#### 🥈 Tier 2 (极高 ROI)
**4. 验证视野脱节：`W_VERIFIER_BLIND_TO_TARGET`**
*   **Kind**: 跨节点契约规则
*   **动机**: Task B 的 role 是 `verification` 且依赖 Task A。但如果 B 的 `awareness_paths`（只读视界）完全不包含 A 的 `claimed_paths`，B 要基于什么上下文去验证 A 的产出？
*   **落地约束**: 遍历验证节点，校验下游 `awareness_paths` 对上游 `claimed_paths` 的覆盖度。

**5. 幽灵压制清理：`W_ORPHANED_SUPPRESSION`**
*   **Kind**: 垃圾回收验证
*   **动机**: 区别于 CMP-5（当次未命中），这是指 `suppress` 绑定的目标 Task ID 已经处于 `completed` 状态，或者对应的 Path 已被重命名/删除。这条豁免规则成了烂在配置里的安全后门。
*   **落地约束**: 将 `plan.suppress` 列表与 Ledger 完成态及文件索引比对验证有效性。

**6. 暗依赖 Mock 提示注入：`Prompt: Verification Mock Guidance`**
*   **Kind**: Prompt Data Flow
*   **动机**: #3 把 `suggested_deps` 透传给了 Foreman。当 Worker 执行测试任务时，它最痛苦的就是“不知道该 mock 谁导致跑测无限失败”。把 Serena 推断出的暗依赖直接转换成一句明确提示：`Serena suggests mocking these dependencies: [deps]`，极大提升 Worker One-shot 跑通率。

#### 🥉 Tier 3 (价值大但需基建)
**7. 提前阻断越权预测：`W_PREDICTED_SIDE_EFFECT_VIOLATION`**
*   **Kind**: 语义预校验
*   **动机**: 不等执行后 verify，利用 Serena 在 Validate 阶段仅根据 `goal_behavior` 推测 Worker“打算改什么”。如果预测的修改意图超出了声明的 `claimed_paths` 范围，在执行前直接拦截。

---

### 4. 维度 3 · 系统级判断

*   **A. 边界问题**：向包含状态感知的控制面演进是**绝对正确的方向**。AI 时代的 plan 本就不是静态配置，而是动态执行图。只要 `validate` 核心引擎保持纯函数特性（不改写 Ledger），让独立的 `audit` 和 `sync-state` 命令去承接历史时序分析，这种架构解耦就是最优解。
*   **B. LLM 时代的输出格式 (Q8)**：必须摒弃人类视角的 `Error/Warning/Hint` 文本体系。强烈建议增加 `ralph validate --format=llm-directive` 专门给 Worker 看，输出带有强类型约束的 XML/Markdown：`<Constraint severity="MUST_FIX" target="behavior">Do not write unit tests, rewrite the integration script.</Constraint>`。大模型对结构化 System Directive 的遵循度远高于自然语言段落拼装。
*   **C. 23 项的 PR 执行顺序**：当前的 `α → β1 → β2 → γ → δ` 存在致命的风险倒置。**PR γ (#7 Structured Envelope) 必须被提至绝对的最前端，与 PR 1 合并**。因为后续的大量复杂 Prompt 解析和 Serena 对接极易引发 Python 炸栈；如果不先把 Exit code 2 和内部崩溃的隔离壳套好，一旦抛错，Foreman 侧将收到满屏乱码，完全瘫痪本地测试链路。
*   **E. 系统性风险预测**：半年后最大的系统性麻烦将是 **“压制雪崩（Suppression Bloat）”** 与告警疲劳。随着语义检查规则（`S_*`）变得严厉且存在假阳性，为了让主干绿灯，人类工程师会习惯性在 `.cccc/ralph.yaml` 堆满全局 `suppress_codes`，导致 Ralph 从重型雷达退化为一只瞎眼的假老虎。必须在系统引入“Suppress 必须附带工单号 / 限时过期”的强制防腐机制。

---

### 5. 反事实选 5 项

如果开发资源极度受限，以下 5 项是构筑防御底线的唯一选择：
1. **#7 Structured Internal Envelope**：运维排障保命线。隔离框架崩溃与业务校验，没它调试如同蒙眼狂奔。
2. **#10 Prompt Budgeter**：运行时保命线。没有降维防洪机制，必然会面临 Context 撑爆或截断导致的 Worker 集体智障。
3. **#1 W_REGISTERED_PLAN_STALE (+ 强化版的硬拦截)**：数据保真防线。确保证算出来的结果能够正确映射回实际对应的图拓扑。
4. **R-1 Deterministic Issue Sort**：研发心智防线。终结 CI 快照测试的无意义薛定谔闪烁。
5. **#3 Serialize Semantic Summary**：算力利用率基石。让高昂成本计算出的 Serena 深度情报终于能流入调度引擎发挥批次决策作用。

---

### 6. 结论

**这份方案【需要打补丁修改】 (ENDORSE WITH CAVEAT) 后方可执行**。必须修正 #1 的完成态握手漏洞与 #10 的截断降维策略，并将 #7 的架构防爆盾优先提至 PR 的第一顺位。