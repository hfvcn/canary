我按你上传的提示词来做，视角是“**无代码库访问权限、只基于文档里的 file:line/data-flow 描述做第三方再反驳**”。提示词要求的是三维评审、逐项判定、再给系统级判断；方案正文给了 Ralph 的角色、Foreman/Worker 交互、第一阶段 13 项、第二阶段 11 项、以及独立的 `ralph audit` 命令。    

## 1. 执行摘要

总体判断：**本质正确，但还不能原样直接执行**。这份方案抓住了 Ralph 当前最真实的主矛盾，不是“规则不够多”，而是**validation 信息在三个边界上持续失真**：plan snapshot 边界（#1）、control-plane/ledger 边界（#3/#9/#11）、以及 worker prompt 边界（#2/#4/#10）。这一判断和你们在文档里强调的三个 “huh, good catch” 基本一致。 

我最关键的 3 个发现是：
第一，**方案元数据本身还没封板**：正文口头说“23 项”，但按正文枚举其实是第一阶段 13 项 + 第二阶段 11 项 = 24 项，另加独立 `ralph audit` 还要再算 1 个命令；提示词也写成“23 个改进项 + 1 个新命令”。这不是小笔误，而是会影响 PR 拆分、追踪和复盘口径。  
第二，**#1 的 detect-only 不是终局设计**。它对“保住 frozen snapshot 语义”是对的，但对“阻止 old-plan completion divergence”还不够；如果 completion 路径不带 `plan_digest` 断言，warning 被忽略后还是会把旧 plan 的完成记录写进 ledger。这个风险其实已经被你们自己在红队问题里点出来了。  
第三，**#9 只做 parity 不够，必须做 versioned envelope**。否则 `ralph audit` 读历史时只是把今天的不对齐，换成半年后的“兼容多代 schema 的解析泥潭”。  

## 2. 维度 1 · 方案评审

先说一句总评：**方向上我同意大多数项，真正需要改的不是“做不做”，而是 5 个关键项的设计边界。** 下面我按正文里实际列出来的项目逐项判。正文实际列出了 24 个命名项，再加 1 个独立命令。

### 第一阶段

* **R-1** — ✅ **ENDORSE**
  基础卫生项，应该最早做。没有确定性排序，后面所有 diff/snapshot/审计都不稳。

* **R-2′** — ⚠️ **ENDORSE WITH CAVEAT**
  方向对，但“声明 `schema_version` 才启 `extra="forbid"`、未声明继续 legacy ignore”会让系统长期处在双语义状态。必须加两个配套：一是 legacy 模式显式 banner；二是迁移 deadline，否则 typo 静默吞掉的问题会拖很久。

* **R-4** — ✅ **ENDORSE**
  daemon 长生命周期下只按 path 缓存确实会返回陈旧结果，这个修补是低风险高回报。

* **U-3** — ⚠️ **ENDORSE WITH CAVEAT**
  我支持 `validate --diff`，但它要么建立在**稳定 issue fingerprint**之上，要么接受“message wording / evidence normalization 变化也会看起来像新 issue”。你们现在的 diff key 仍偏脆。

* **CMP-1** — ✅ **ENDORSE**
  纯完整性缺口，且是会被静默吞掉的拼写错误，价值很高。

* **CMP-2** — ✅ **ENDORSE**
  把 `state` 三个字段统一检查是对的，属于“修口径而不是加规则”。

* **CMP-3** — ✅ **ENDORSE**
  duplicate id/invariant 类错误没有什么争议，应该补。

* **CMP-4** — ✅ **ENDORSE**
  定成 warning 而不是 error 很合理；这是语义残缺，不是结构不可用。

* **CMP-5** — ⚠️ **ENDORSE WITH CAVEAT**
  `H_SUPPRESS_UNUSED` 值得做，但只看“本轮没命中”会有单次噪音，尤其是 provider-dependent finding 或条件性 issue。最好明确这是**advisory cleanup signal**，不要让用户误以为 suppress 必错。

* **CMP-6** — ⚠️ **ENDORSE WITH CAVEAT**
  我同意方向，但“扫 `command + checks[*].command`”本质是启发式，shell wrapper、Make target、script indirection 都会让它误判。这个更像低置信度 finding，不宜过强。

* **CMP-7** — ✅ **ENDORSE**
  `plan_scope` 不 overlap 任何真实路径，本来就该被指出。

* **U-6** — ✅ **ENDORSE**
  成本低，立竿见影。

* **U-1′** — ✅ **ENDORSE**
  扩展 `ralph explain` 比新发明命令干净。

### 第二阶段

* **#1 `W_REGISTERED_PLAN_STALE`** — ⚠️ **ENDORSE WITH CAVEAT**
  作为第一步，detect-only 是对的；作为终局，不够。它能解释“为什么你改了 plan 不生效”，但挡不住“旧 plan 上报完成”这个更糟的 divergence。至少 completion/start 路径要做 `plan_digest` 对比或显式 stale override。 

* **#9 Validation Ledger Schema Parity** — ⚠️ **ENDORSE WITH CAVEAT**
  必做，但必须升级成 **schema parity + schema_versioned envelope**。只补字段不补版本，历史 audit 仍然会烂。

* **#10 Prompt Budgeter for Foreman Assignments** — ⚠️ **ENDORSE WITH CAVEAT**
  这是前置项，我同意。但预算必须按 **token** 不是按字符；同时要有**不可截断保底区**，不能把 header/goal/verification/recommended tests/truncation notice 一起裁掉。 

* **#2 Prompt Task Issue Digest** — ⚠️ **ENDORSE WITH CAVEAT**
  必做，但我不接受“severity-first top-3”作为最终 inclusion policy。真正应该排前面的不是 `error > warning > hint`，而是**是否改变执行策略 / 是否不可逆 / 是否改变验证选择**。某些 hint 完全可能比某些 warning 更该让 worker 先看到。 

* **#4 Recommended Tests Reach The Worker** — ✅ **ENDORSE**
  这是典型“数据已经算出来了，却在最后一米掉地上”的项，直接补。

* **#3 Serialize Semantic Summary** — ✅ **ENDORSE**
  `fingerprints` / `suggested_deps` 在 report 里存在、序列化时丢掉，这就是纯 data loss。修它是正当的。 

* **#5 `W_VERIFY_PASSED_BUT_SEMANTIC_INCONSISTENT`** — ⚠️ **ENDORSE WITH CAVEAT**
  我支持“把假绿灯显式化”，但不支持一个单体 warning 吞掉所有低置信度语义不一致。至少要分 evidence type，或挂 confidence/source 字段，否则很容易把用户训练成忽略 semantic warning。 

* **#6 Semantic Gate Cache Freshness** — ✅ **ENDORSE**
  纯 cache invalidation 缺口，没有理由不修。

* **#7 Structured Internal Failure Envelope** — ✅ **ENDORSE**
  方向正确，而且你们把它做成 out-of-band 而非 ValidationIssue，我同意。内部异常不是 plan 错，是系统错误；混进 report 会污染语义层。最好再加 `trace_id` / debug-only raw traceback 保留。

* **#11 Text Output Semantic Parity** — ✅ **ENDORSE**
  人类默认看 text，却只有 JSON 才有 semantic data，这个差异必须补齐。

* **#8 `W_CROSS_WORKFLOW_WRITE_PRESSURE`** — ⚠️ **ENDORSE WITH CAVEAT**
  值得做，也确实应该最后做。但这项如果没有非常清楚的“same project / same group / same workspace”边界定义，会很容易出现 phantom pressure。

### 独立命令

* **`ralph audit`** — ✅ **ENDORSE**
  放在 validate 主路径之外是对的。它读 ledger + stats，本质是 retrospective audit，不应该污染即时 plan linting。

### 对 5 个关键项的更直接判断

* **#1**：设计方向对，安全性不够；必须再加 completion/path digest guard。
* **#2**：应该做，但排序轴错了；要 actionability-first。
* **#5**：应该做，但要置信度分层。
* **#7**：本质正确，是少数我几乎无保留支持的项。
* **#10**：必须先做，但必须是 token-aware + mandatory-minima，不然只是“更优雅地截断错误信息”。

### 对被砍掉的 8 项，我的看法

我**同意继续砍掉其中 7 项**：H-2/H-3/H-4/H-5/H-7/H-9/H-10 目前都不值得进 validate 主线，理由与你们文档里给出的 code-level 理由一致。唯一我不想完全放掉的是 **CMP-8 `finding_refs` 关系语义**：它现在不该进校验规则，但也不能长期保持“模型里有字段、语义却未定义”。我的意见是：**不救回为 rule，救回为 schema contract work**。

### 对 Codex 拒绝的 4 个方向，我的看法

我**全部认同继续拒绝**，而且理由可以再强化一点：
`ralph init` 解决的是 onboarding friction，不是当前最贵的 correctness/data-loss 问题；incremental validate 在你们现在的调用路径里不是 hot path，提前做只会把一致性问题带进缓存/增量失效；auto-severity 在只有 count/last_plan/last_time、没有分母和 action metadata 时，几乎一定会把“常见但轻”的问题误包装成“重要”；rule retirement 在没有 rule introduction timestamp 且 seed data 污染 baseline 的前提下，退掉的更可能是“曝光少”而不是“无价值”的规则。

## 3. 维度 2 · 新建议

下面这些都**不与现有 24 个命名项重复**，也不与文档里显式拒绝的 4 个方向重叠。它们大多是在你们已经识别出 data-loss/prompt-loss 问题后，顺手应该补上的下一层结构件。你们自己的审查问题已经把这些接口暴露出来了。

* **E_PLAN_DIGEST_MISMATCH_ON_COMPLETE**
  kind：data flow / protocol
  动机：#1 只检测 stale plan，不阻止“旧 snapshot 上报完成”。这会让 ledger 记录与作者心智模型分叉。
  落地约束：`cccc task complete` 或 completion RPC 需要携带 registered `plan_digest`；Foreman 需要比较当前 file digest / context digest，并提供显式 override。
  **Tier 1**

* **validation_report.schema_version / event_schema_version**
  kind：data model / observability
  动机：#9 只做 parity 不做版本化，`ralph audit` 迟早要变成“解析多代历史事件的兼容层地狱”。
  落地约束：CLI、orchestrator、ledger reader 三方都要接受 versioned envelope；旧事件默认为 v0。
  **Tier 1**

* **finding.confidence / source / actionability**
  kind：output model
  动机：现在 warning/hint 太粗，#5、CMP-6 这类启发式 finding 如果没有 confidence/source，用户会学会忽略所有黄色信息。
  落地约束：要给每类规则定义最小一致的 confidence 语义，不要让各 rule 各写各的。
  **Tier 1**

* **DEGRADED_MODE_MANIFEST**
  kind：data flow / UX
  动机：当 semantic provider 不可用、gate 关闭、或某类 validator 被跳过时，“没有 finding”不等于“干净”。必须显式告诉人和 worker 现在处于 degraded mode。
  落地约束：text/json/prompt 三个出口都要一致暴露，而且不能刷屏。
  **Tier 1**

* **IssueFingerprintID**
  kind：data model / CLI
  动机：U-3 现在靠 `(severity, code, task_ids, normalized evidence)` 做 diff，message wording 一变就抖。稳定 issue id 会同时利好 diff、suppress、ledger audit。
  落地约束：evidence canonicalization 要做得很克制，否则 id 反而不稳定。
  **Tier 2**

* **PromptBuildManifest**
  kind：observability / prompt path
  动机：#10 上线后，下一类抱怨一定是“为什么 worker 没看到 X”。要能追溯每个 assignment 实际包含了哪些 section、截断了多少 token、基于哪个 digest 生成。
  落地约束：日志体积会上升；需要注意不要把敏感上下文再打印一遍。
  **Tier 2**

* **Suppress requires reason + expiry**
  kind：schema / rule
  动机：`H_SUPPRESS_UNUSED` 只能抓“死 suppress”，抓不到“永生 suppress”。要求 suppress 带 reason 和可选 expiry，能显著降低临时 suppress 永久化。
  落地约束：要保留永久 suppress 的合法路径，不能逼用户乱填日期。
  **Tier 2**

* **ralph replay-validation**
  kind：CLI / reproducibility
  动机：当 #6/#7 这类运行时/环境相关问题出现时，最好能一键打包“plan bytes + report + provider state + key digests”做复现，而不是靠口述。
  落地约束：bundle 大小、secret scrubbing、workspace snapshot 范围都要谨慎。
  **Tier 2**

* **CapabilityMatrix for non-Python repos**
  kind：UX / capability disclosure
  动机：文档自己问到了 Flutter/TS/Rust。真正危险的不是“能力少”，而是“用户不知道哪些能力少”。要显式声明当前 repo 哪些 validator/AST/semantic 能力可用、哪些是 degraded。
  落地约束：维护每语言能力矩阵会带来持续成本。
  **Tier 3**

## 4. 维度 3 · 系统级判断

### A. 边界问题

Ralph 应该继续是**plan-centric validator**，但允许有两个“邻接面”：
一个是 **runtime delivery surface**，把 validation 结果送到真正的消费者，也就是 worker prompt；这就是 #2/#4/#10。
另一个是 **retrospective audit surface**，读 ledger/stats 做事后分析；这就是 `ralph audit`。

这两类都**不是 agentization**。它们仍然没有让 Ralph 去执行任务或自主决策，只是在解决“Ralph 的输出到底有没有被用到”这个现实问题。我认为这条边界是正确的。 

### B. LLM 时代的 linter 形态

是，我会建议 Ralph 引入**第三种输出**，而不只保留“给人看的 text”和“给 IPC 的 JSON”。文档自己已经把这个缺口问出来了。

我会做一个专为 worker 设计的 `ValidationPacket`，核心字段不是 prose，而是：

`task_id`
`hard_blockers[]`：`code / why_it_matters / required_action / evidence / confidence`
`execution_hazards[]`：会改变工具、路径、顺序选择的事项
`recommended_tests[]`
`semantic_summary`：risk_level / fanout / suggested_deps / symbol anchors
`degraded_modes[]`
`truncation_manifest`

然后再把它渲染成一个很短的 markdown block 喂给模型。
重点不是“更好看”，而是**把 message 从人类叙述改成模型可排序、可执行的槽位结构**。

### C. 23 项的执行顺序

你们的总顺序大体对，但我会改两处：

第一，**#7 应该前移**。它不该等到 γ 才做；没有结构化内部错误，你后面 rollout #10/#2/#3 时，出了问题很难判断是 plan 错、rule 错、还是 orchestration 错。
第二，**#11 应该和 #3/#5 同步落地**。否则 JSON 世界看得见 semantic，text 世界还看不见，会形成双轨体验。

我自己的顺序会是：
R-1 → #7 → #10 → #1 → #9 → #3 → #11 → #2 → #4 → #5 → 其余 completeness 项 → #6 → #8。
其中 #8 最后做，我同意。

### D. 反事实思考

如果只能做 5 项，我会选：#10、#2、#1、#7、#5。
理由见下面“反事实选 5”。

### E. 方案之外的系统性风险

半年后 Ralph 最可能碰到的最大麻烦，不是性能，而是**信任衰减**。更具体地说，是三种信任衰减：

一，**finding 置信度混杂**：静态、语义、启发式、历史型 finding 都挤在一起，用户最后学会忽略所有 warning。
二，**schema drift**：plan/report/ledger/prompt 四个输出面逐步分叉，任何一个都能“看起来能用”，但彼此不一致。
三，**多语言假安全感**：Python-centric 能力在 Flutter/TS/Rust 仓库里 silently degrade，作者却以为 Ralph 仍提供同等级保证。

所以真正要防的不是“规则太少”，而是“规则很多，但用户不再相信它们”。

## 5. 反事实选 5

1. **#10 Prompt Budgeter for Foreman Assignments**
   没它，后续所有 prompt-path 改动都可能被上下文膨胀吃掉。

2. **#2 Prompt Task Issue Digest**
   这是 Ralph 输出第一次真正抵达主要消费者 worker 的关键一跳。

3. **#1 `W_REGISTERED_PLAN_STALE`**
   这是最典型、最伤信任的“我明明改了 plan 为什么没生效”。

4. **#7 Structured Internal Failure Envelope**
   没有它，系统炸了和 plan 错了在用户眼里根本分不清。

5. **#5 `W_VERIFY_PASSED_BUT_SEMANTIC_INCONSISTENT`**
   “假绿灯”比“明确红灯”危险得多。

没进前五但接近的是 **#9** 和 **#3**。如果你们已经有强烈的 ledger/audit 路线图，我会把 #9 顶进前五，替掉 #5。

## 6. 结论

**需要修改后执行**：方案本质正确，但至少应先补上 `#1` 的 completion-side digest guard、`#9` 的 schema versioning、`#10` 的 token-aware mandatory budget、以及 finding confidence/source 这一层，否则你们会修掉今天的数据丢失，却把半年后的审计和信任问题提前埋下。
