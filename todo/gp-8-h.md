## 1. 执行摘要

这份方案**本质正确，但还不能原样执行**。强项很清楚：它抓住的不是“再加几条 lint 规则”，而是 Ralph 产物在 **Foreman → prompt → worker → ledger** 这条链路上不断失真的问题，尤其是 frozen plan、prompt 不带 issue、verify 假绿、内部异常裸 traceback 这几个点，判断是准的。最关键的 3 个发现是：第一，**#1 只做 detect-only 不够**，因为真正危险的是 completion/ledger 继续在旧 plan 语义下落账；第二，**#2 不能靠 severity top-3 粗排**，否则会把“真正改变执行策略”的信息埋掉；第三，**#5 必须加 confidence/升级门槛**，不然很快会把 semantic warning 做成噪音源。我的结论是：**需要修改后执行**，而不是推翻重来。方案的方向对，差的是几处边界条件和协议设计。  

## 2. 维度 1 · 方案评审

以下 23 项来自方案第 4 节；我按逐项 verdict 给出。 

### 第一阶段

**R-1** ✅ ENDORSE
该做，而且应尽早做。没有确定性排序，所有 snapshot / diff / audit 都会被抖动污染。

**R-2′** ⚠️ ENDORSE WITH CAVEAT
方向对，但“声明 `schema_version` 才 `extra="forbid"`，未声明继续 legacy ignore”会形成双轨世界。至少要额外输出一个显式 banner：`legacy schema parsing active`，不然用户会以为 typo 已受保护。

**R-4** ✅ ENDORSE
这是标准 daemon 缓存卫生，收益确定，副作用低。

**U-3** ⚠️ ENDORSE WITH CAVEAT
值得做，但 diff key 只靠 `(severity, code, task_ids, normalized evidence)` 还不够；需要再加 `rule_version` 或 `evidence_hash`，否则同一规则换了 message 归一化方式，diff 会产生假新增/假消失。

**CMP-1** ✅ ENDORSE
明显的 completeness hole，低成本高收益。

**CMP-2** ✅ ENDORSE
这是状态引用完整性，应该补齐 completed/failed/running 三类。

**CMP-3** ✅ ENDORSE
重复 ID / invariant name 属于必须尽早显式化的结构错误。

**CMP-4** ✅ ENDORSE
warning 定位合理。它不是 plan 不可执行，而是 ownership 语义退化。

**CMP-5** ⚠️ ENDORSE WITH CAVEAT
只能作为 hint，且必须在“所有 issue 都产生完、所有 suppress 都匹配完、semantic provider 状态已知”之后跑。否则很容易把“暂时没触发”“provider 降级”“规则尚未 rollout”的 suppress 误判成无用。

**CMP-6** ⚠️ ENDORSE WITH CAVEAT
我同意补这个洞，但不赞成仅靠扫 `command + checks[*].command` 的字符串层实现就直接上 warning。它很容易在 shell wrapper、Makefile、tox/npm script、pytest alias 场景里误报或漏报。更稳的做法是：第一版保守些，提成 hint 或只在可直接解析路径引用时报警。

**CMP-7** ✅ ENDORSE
plan_scope 无效但静默，确实会制造“我以为在收窄检查，实际上没生效”的错觉。

**U-6** ✅ ENDORSE
纯 UX，但高频使用面广，值得顺手补。

**U-1′** ✅ ENDORSE
沿用 `ralph explain` 比重造 `why` 好，命令面不会膨胀。

### 第二阶段

**#1 `W_REGISTERED_PLAN_STALE`** ⚠️ ENDORSE WITH CAVEAT
问题判断完全正确，detect-only 设计不够。真正的风险不是“用户看到旧警告”，而是**completion/sync-state/ledger 继续在旧 digest 上结算**。我建议：保留 frozen plan 语义不动，但在 `cccc task complete` 或等价 completion 路径增加一次 `plan_digest` 比对；若磁盘 plan 已变，至少写一个显式 stale-context event，必要时要求 `--force-stale-complete`。仅靠 warning，风险仍会漏进 ledger。 

**#9 Validation Ledger Schema Parity** ⚠️ ENDORSE WITH CAVEAT
要做，但不要直接 hard bump 旧事件。正确姿势是 **dual-read, single-write**：新 writer 统一 schema，reader 同时兼容旧字段；等 `ralph audit` 稳定后再考虑迁移/回填。否则你会把“修 observability”做成“先做全量历史迁移”。

**#10 Prompt Budgeter for Foreman Assignments** ⚠️ ENDORSE WITH CAVEAT
这是必做前置，但预算单位不应是 chars，而应是**token budget**。而且必须保留保底区：`Task ID / Goal / Acceptance Criteria / Verification Command / Do-not-ignore issues / Recommended tests` 这几段不能被任意截断；被截断的应该优先是 context-store 和长 semantic narration，而不是 assignment 核心。 

**#2 Prompt Task Issue Digest** ⚠️ ENDORSE WITH CAVEAT
方向对，但 `error > warning > hint` 的 top-3 过于粗糙。worker 真正需要的是“**会改变行动路径**”的信息，不是传统严重级排序。我建议改成：1 条 blocking fact + 1 条 execution-risk + 1 条 verification-risk 的配额式选择；同类内再按 severity 和稳定排序键决定。否则会出现“3 条 error 都是整理类问题，而真正要改测试选择的 warning 被挤掉”的情况。 

**#4 Recommended Tests Reach The Worker** ✅ ENDORSE
这个价值直接，而且与 #10/#2 形成闭环。

**#3 Serialize Semantic Summary** ⚠️ ENDORSE WITH CAVEAT
同意序列化，但不要把 `fingerprints` / `suggested_deps` 原样裸透传到所有消费者。应该定义一个 compact, versioned summary；否则你会把 semantic 内部结构直接绑定到 IPC 协议上，后面很难演进。

**#5 `W_VERIFY_PASSED_BUT_SEMANTIC_INCONSISTENT`** ⚠️ ENDORSE WITH CAVEAT
必须做，但不能无条件升 warning。这里最容易把“semantic provider 低置信度猜测”变成“verify 假绿”的常驻噪音。建议门槛：仅当 `ConsistencyReport` 含高置信度 stale/missing-create，或同一 task 连续出现，才升为 warning；其他情况维持 details/hint，并带上 confidence 与 provider mode。 

**#6 Semantic Gate Cache Freshness** ✅ ENDORSE
纯 correctness bug，且收益明确。

**#7 Structured Internal Failure Envelope** ⚠️ ENDORSE WITH CAVEAT
大方向完全正确：内部异常不该伪装成 ValidationIssue。但我建议除了 exit code 2 和 `error` 对象，还要有一个稳定的 `internal_error_code` / `stage` 枚举，并默认隐藏原始 traceback，仅在 debug 模式展开。否则 CI 和上层 orchestrator 还是只能依赖 message 文本做分流。 

**#11 Text Output Semantic Parity** ✅ ENDORSE
人类默认看 text，而 JSON 才有 semantic 信息，这个落差应该补。

**#8 `W_CROSS_WORKFLOW_WRITE_PRESSURE`** ⚠️ ENDORSE WITH CAVEAT
值得做，但我会把它定义成**scheduler-pressure / coordination signal**，而不是纯 validator truth。需要严格限定作用域：同 project/group、活动 workflow、有租约/最近心跳、路径 overlap 可信。否则 stale workflow 和历史残留会造成大量假压力。

**`ralph audit`** ✅ ENDORSE
边界划分是对的：历史/行为问题留给 audit，不污染 validate 的语义。前提是它保持只读，不影响 validate exit code。 

### 我对 5 个关键项的总判断

* **#1**：本质正确，但必须把 stale 检查推进到 completion/ledger 边界，否则只是“提醒用户已偏离”，并没有防止偏离继续写账。
* **#2**：本质正确，但排序维度错了；应该围绕 actionability，而不是 severity。
* **#5**：本质正确，但最容易噪音化，必须加 confidence gate。
* **#7**：方向最干净，应该提前做。
* **#10**：必须先于 #2/#4，上线前要有 token 保底区和 truncation report。 

### 对被砍掉的 8 项，我的判断

我**基本同意全部砍掉**。唯一我不想“救回成规则”的是 **CMP-8 finding_refs 关系语义**：它现在不该进 validate，但它值得被救回成一个**先定义语义契约、后上规则**的 spec note。其余 H-2/H-3/H-4/H-5/H-7/H-9/H-10 被砍是合理的：不是信号弱，就是误报高，要么与既有排期重叠。 

### 对 Codex 拒绝的 4 个方向，我的判断

我也**同意全部拒绝，而且理由可以更强**：
`ralph init` 是 adoption 加速器，不是 correctness multiplier；当前主痛点是产物失真，不是起步慢。
incremental validate 不只是“不是 hot path”，更关键是它会引入**增量失效判定**、cache coherence、semantic provider 局部失真等一整套复杂度，收益与风险不成比例。
auto-severity from stats 在现有 stats 只记录命中次数/时间、没有 action outcome / suppression outcome 的情况下，属于**伪数据驱动**。
rule retirement 更不该现在做，因为你们连“规则引入时间”“哪些仓库启用了哪些规则”“命中为 0 是没人触发还是根本没覆盖到”都没法可靠区分。 

## 3. 维度 2 · 新建议

下面这些都尽量避开现有 23 项和已明确拒绝方向。新建议的标准，是补协议、补边界、补可观测性，而不是再堆一层 lint。你给外部审查 AI 的提示词也明确要求新增方向不能与 23 项重叠。 

**1. `report_schema_version` + `producer_version` stamp**
kind：data flow 改动
动机：现在你们在做 U-3 diff、#9 parity、#11 text parity，本质都依赖“我知道这份 report 是按哪个 schema 和哪个 Ralph 版本产出的”。没有这个 stamp，未来最常见的误判是“字段变了/归一化变了/排序变了，却被当作 plan 质量变化”。
落地约束：要同时进 JSON、IPC、ledger 事件；不能只放 CLI。
Tier：🏆 Tier 1

**2. `suppress.reason / owner / review_after` + `W_SUPPRESS_EXPIRED`**
kind：新规则 + schema 能力
动机：`H_SUPPRESS_UNUSED` 只能抓“没命中任何 issue 的 suppress”，抓不到“还在命中，但其实早该复审的 suppress”。后者才是真正会慢慢腐蚀规则可信度的东西。
落地约束：要兼容旧 suppress 结构；最好先作为 advisory。
Tier：🏆 Tier 1

**3. `H_SEMANTIC_COVERAGE_DEGRADED`**
kind：observability / report path
动机：文档里已经暴露了 `semantic_provider`、`semantic_failure_reason`、gate 模式和缓存问题；但用户最容易误解的是“这次 validate 没报 semantic 问题 = semantic 检查通过”。实际上可能只是 provider 掉了、gate 降级了、或某类检查被跳过。
落地约束：要把 provider unavailable / advisory fallback / strict skipped 区分开。
Tier：🏆 Tier 1

**4. `issue_instance_id`（基于 code + normalized evidence + scope 的稳定指纹）**
kind：data model 改动
动机：你们想做 diff、suppress、audit、worker digest、ledger 关联，但现在 issue 似乎还是“靠 code + 文本 message + evidence 松散比对”。稳定实例 ID 会显著降低 message 改写带来的连锁噪音。
落地约束：evidence 正规化必须足够稳定；不同规则要避免 hash 冲突语义。
Tier：🏆 Tier 1

**5. `ralph emit-worker-brief` / `--format worker-brief`**
kind：CLI 能力 / data flow 改动
动机：今天 Ralph 只有“给人看的 text”和“给 IPC 的 JSON”。但下游高频消费者明明是 worker。你们自己在文档里已经意识到 #2/#3/#4 是在补 LLM 消费链路；与其把 digest/tests/semantic_summary 零碎塞进 orchestrator，不如定义一个**专门给 LLM 的瘦身协议**：immutable facts、blocking issues、execution traps、recommended tests、truncation notice。
落地约束：必须 versioned；否则 prompt budgeter 与上层 orchestrator 会被反绑。
Tier：🏆 Tier 1

**6. `ralph plan-diff A.yaml B.yaml`**
kind：CLI 能力
动机：U-3 只是在比两次 validate 结果；作者真正关心的往往是“我的计划语义变了什么”：task graph、claimed/awareness、covers.flows、required_issues、suppress、verification level。这个命令会比 output diff 更接近作者心智。
落地约束：需要定义 plan 语义 diff 的 canonical view，而不是文本 diff。
Tier：🥈 Tier 2

**7. `ralph --profile-rules` / per-rule latency & hit-rate**
kind：observability
动机：你们已经有 40+ 规则和 semantic provider；半年后最大的隐患不是“少一条规则”，而是“不知道哪条规则慢、哪条规则噪、哪条规则从不命中”。这和 rule retirement 不同：先测量，再谈治理。
落地约束：profile 不能污染默认路径；最好按 debug/flag 开启。
Tier：🥈 Tier 2

**8. `language_capability_matrix` for Ralph**
kind：architecture / UX
动机：文档已经承认 Ralph 偏 Python。真正的问题不是“多语言支持不够”，而是用户**不知道哪些检查在当前语言里是 authoritative，哪些是 disabled / heuristic**。一个能力矩阵会直接降低 Flutter/TS/Rust 项目的误解成本。
落地约束：要给 filesystem / semantic / AST 类检查都打 capability tag。
Tier：🥈 Tier 2

**9. `W_RULE_OUTPUT_UNVERSIONED_CONSUMER`**
kind：新规则 / integration hygiene
动机：当某个上游字段被 worker prompt、ledger、audit、CLI text 同时消费，而没有 schema/version 防护时，任何一次 message 或字段调整都可能造成隐性 break。这个不是在管“代码质量”，是在管**跨组件契约**。
落地约束：需要先盘点 consumers。
Tier：🥉 Tier 3

## 4. 维度 3 · 系统级判断

**A. 边界问题**
Ralph 应该保持成 **“静态 validator + 派生读模型/投影器”**，而不是演变成 plan + 历史 + agent 的混合体。`ralph audit` 读取 ledger 是合理扩边，因为它是只读审计视角；#2 给 worker 注入 issue digest 也合理，因为那是在做 validator 结果的投影，而不是让 Ralph 接管执行。真正危险的越界点，是让 Ralph 开始自己决定调度策略或自动改 plan；当前方案还没越界。 

**B. LLM 时代的 linter 形态**
我会建议引入专为 LLM 设计的输出格式。不是把现有 `error/warning/hint + message` 原样 JSON 化，而是一个 bounded packet：
`immutable_facts`、`blocking_constraints`、`execution_risks`、`verification_targets`、`suggested_tests`、`confidence`、`truncation_notice`。
其中每条都要短、结构化、可排序、可裁剪。这和文档里 #2/#3/#4/#10 的动机完全一致，只是把它们提升成正式协议，而不是继续让 orchestrator 拼 free-text。  

**C. 23 项的执行顺序**
原分组大体合理，但我会调整两处：
第一，把 **#7 Structured Internal Failure Envelope** 提前到第一波；因为后面做 prompt/report/provenance 改造时，若内部异常仍是裸 traceback，排障成本太高。
第二，把 **#9 Ledger Schema Parity** 放到 `ralph audit` 真要落地前再做，不必过早抢在 β1/β2 前。
其余里，**#10 必须先于 #2/#4**，这个我完全同意。 

**D. 反事实思考：如果只能做 5 项**
见下一节，我会单独排名。

**E. 方案之外的系统性风险**
半年后最可能炸的不是性能，而是**信任债**：
人看到的 text、worker 吃到的 prompt、ledger 记下的事件、audit 读出的历史，不是同一个真相表面。只要这四个面持续不一致，用户就会开始选择性忽略 Ralph。第二风险才是 semantic 噪音；第三才是多语言能力落差。性能问题反而会在规则/provider 数量再翻一倍时才真正成为主导。 

## 5. 反事实选 5

如果只能做 5 项，我会选：

**1. #10 Prompt Budgeter for Foreman Assignments**
没有预算器，后续所有 worker-facing 改进都可能变成上下文污染。 

**2. #2 Prompt Task Issue Digest（但改成 actionability-based selection）**
这是让 Ralph 真正进入 worker 决策闭环的最低成本入口。 

**3. #7 Structured Internal Failure Envelope**
没有稳定的内部错误封装，后续 rollout 会很痛。 

**4. #1 `W_REGISTERED_PLAN_STALE`（并补 completion digest guard）**
这是最像“你以为系统理解了你的 plan，实际没有”的致命认知偏差。 

**5. #5 `W_VERIFY_PASSED_BUT_SEMANTIC_INCONSISTENT`（加 confidence gate）**
它直接修复 verify 假绿，是信任恢复项。 

我**不优先**做的 5 项是：U-6、U-1′、#11、#9、CMP-4。不是说不值得，而是在“只能做 5 项”的条件下，它们对 correctness / trust loop 的增益更低。 

## 6. 结论

一句话结论：**这份方案需要修改后执行，不需要重新讨论。**方向是对的，关键是把 #1、#2、#5、#7、#10 的协议边界再收紧一圈。 
