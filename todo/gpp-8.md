以下评审按你附带的外发提示词来写：把我当成一个没有代码库访问权限、只能依赖文档里的 file:line anchors 与数据流描述来判断的第三方 reviewer。先指出一个小但真实的问题：文首写“23 项”，但正文可见的是第一阶段 13 项、第二阶段 11 项，另有一个 helper refactor 和单独的 `ralph audit`；这类计数漂移本身就会伤害后续 PR 跟踪与外部审查的可信度。 

## 1. 执行摘要

总体判断：**方案本质正确，但不是“可直接合并”的状态**。最有价值的不是多了多少规则，而是你们抓到了 Ralph 现在真正的结构性缺陷：**provenance 丢失**、**semantic 信号在 control plane / worker 路上掉地**、以及**人类视图、JSON 视图、ledger 视图、prompt 视图的分裂**。我最关键的三个发现是：第一，`W_REGISTERED_PLAN_STALE` 不能只做 detect-only，必须保护 state-mutating 路径；第二，`Prompt Budgeter` 不能只是按 section priority 截断，而要做真正的 token budgeting、摘要化和 omission manifest；第三，`W_CROSS_WORKFLOW_WRITE_PRESSURE` 的问题是真问题，但**不该作为 validation warning 落在 Ralph**，而该作为 Foreman 的调度阻塞信号。你文档里标出的几个核心机制——冻结的 `plan_source`、零 size cap 的 `_build_task_prompt()`、被丢弃的 `fingerprints/suggested_deps`、埋进 `semantic_details` 的 `ConsistencyReport`、以及不失效的 semantic gate cache——足以支撑这些判断。

## 2. 维度 1 · 方案评审

### 第一阶段

| 项                                  | 结论                     | 评语                                                                                                               |
| ---------------------------------- | ---------------------- | ---------------------------------------------------------------------------------------------------------------- |
| R-1                                | ⚠️ ENDORSE WITH CAVEAT | 方向对，但 sort key 不要只用 `task_ids[0]` + stringified evidence；应使用完整 `task_ids` tuple + canonical JSON evidence，否则仍会抖。 |
| R-2′                               | ⚠️ ENDORSE WITH CAVEAT | 方向对，但 legacy `ignore` 至少应显式提示 ignored extras；否则老 plan 仍会 silent swallow typo。                                    |
| R-4                                | ⚠️ ENDORSE WITH CAVEAT | `(path, mtime)` 太弱，至少 `mtime_ns`，更稳是 `(path, size, mtime_ns)` 或 digest。                                          |
| U-3                                | ⚠️ ENDORSE WITH CAVEAT | 值得做，但 diff key 不能依赖 human message；要依赖 typed/normalized evidence，否则 copy edit 也会制造假 diff。                         |
| PR3 helper `_covered_flow_summary` | ✅ ENDORSE              | 抽 helper 正确，能减少 flow coverage 逻辑在多个规则间漂移。                                                                        |
| CMP-1                              | ✅ ENDORSE              | 高价值，直接堵住 `covers.flows` typo 黑洞。                                                                                 |
| CMP-2                              | ✅ ENDORSE              | `warning` 定位基本合理；state 往往是 runtime 残留，不必默认上升成 blocking error。                                                    |
| CMP-3                              | ✅ ENDORSE              | 必补；duplicate IDs 会让后续 coverage、audit、解释全失真。                                                                      |
| CMP-4                              | ✅ ENDORSE              | `warning` 恰当；这是死配置味道，但还不到阻断级。                                                                                    |
| CMP-5                              | ✅ ENDORSE              | 有用，前提是文案明确：这是 “current-run unused”，不是 “永远多余”。                                                                    |
| CMP-6                              | ⚠️ ENDORSE WITH CAVEAT | 只应在 literal path + compile/unit 场景下触发；shell 包装、env 变量、脚本转发都容易误报。                                                 |
| CMP-7                              | ✅ ENDORSE              | 值得做，能暴露形同虚设的 `plan_scope`。                                                                                       |
| U-6                                | ✅ ENDORSE              | 小改动高回报。                                                                                                          |
| U-1′                               | ✅ ENDORSE              | 应并入现有 `explain`；最好同时输出修复模板、适用前提和 suppression 交互。                                                                 |

### 第二阶段

| 项                                              | 结论                     | 评语                                                                                                                                                                                        |
| ---------------------------------------------- | ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| #1 `W_REGISTERED_PLAN_STALE`                   | ⚠️ ENDORSE WITH CAVEAT | 保留 frozen semantics 是对的；但 warning-only 不够。`complete/sync-state` 这类 state-mutating 路径应做 digest guard，并把 `registered_digest/current_digest` 写入 ledger。                                      |
| #9 Validation Ledger Schema Parity             | ⚠️ ENDORSE WITH CAVEAT | 要做，但应用 **dual-read / single-write** 迁移；不要靠强 bump 让旧 ledger 失去可读性。                                                                                                                         |
| #10 Prompt Budgeter                            | ⚠️ ENDORSE WITH CAVEAT | 必须先做；但预算应按 token 而非 char，策略应先 summarize 再 truncate，并在 prompt/日志里回显 omission manifest。                                                                                                     |
| #2 Prompt Task Issue Digest                    | ⚠️ ENDORSE WITH CAVEAT | 要做，但 `top-3` + `error>warning>hint` 过粗；应先保留 all blockers，再按 actionability 选剩余额度。                                                                                                          |
| #4 Recommended Tests Reach The Worker          | ✅ ENDORSE              | 直接高回报；推荐 tests 不应停留在 `task_results` 黑箱里。                                                                                                                                                  |
| #3 Serialize Semantic Summary                  | ⚠️ ENDORSE WITH CAVEAT | 方向对，但建议传 **bounded summary**，不要直接扩散完整 provider payload。                                                                                                                                   |
| #5 `W_VERIFY_PASSED_BUT_SEMANTIC_INCONSISTENT` | ⚠️ ENDORSE WITH CAVEAT | 需要 confidence gating；高置信且命中 `claimed_paths`/creates 语义时 `warning`，否则应降为 hint 或 telemetry-only。                                                                                            |
| #6 Semantic Gate Cache Freshness               | ✅ ENDORSE              | 这是实打实的 freshness bug，应该修。                                                                                                                                                                 |
| #7 Structured Internal Failure Envelope        | ⚠️ ENDORSE WITH CAVEAT | 方向正确；要定义 stage taxonomy、retryable、redaction，并尽量保留 partial results。                                                                                                                        |
| #11 Text Output Semantic Parity                | ✅ ENDORSE              | 人类默认 text 视图不应长期落后于 JSON 视图。                                                                                                                                                              |
| #8 `W_CROSS_WORKFLOW_WRITE_PRESSURE`           | ❌ REJECT               | 问题真实，但不该表现为 validation warning；它是 **Foreman scheduling pressure**，不是 plan defect。替代方案：orchestrator 事件/状态 `task_deferred_due_to_external_write_pressure`，携带 competing workflow/path 与 TTL。 |

### 独立命令

| 项             | 结论                     | 评语                                                                                                                      |
| ------------- | ---------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `ralph audit` | ⚠️ ENDORSE WITH CAVEAT | 作为独立命令是对的；`W_TASK_FLAPPING` / `H_COMPLETED_BUT_UNVERIFIED` 好，`H_PLAN_AGE` 则应等 issue registry 结构化后再做，不应依赖 markdown 归档文本。 |

### 我最关注的 5 项

`#1`：你们对“不要自动解冻”的判断是对的，但**只做 warning 会把 divergence 从 validate 侧推迟到 completion 侧**，问题更难追。最小闭环是：warning + mutating-command digest guard + ledger 双 digest。

`#2`：真正缺的不是“再排序一下”，而是 **issue 的 recipient / actionability**。没有这一层，worker 会收到计划作者才该处理的 hygiene 噪音。

`#5`：不要把 semantic provider 的不确定性直接升级成 warning spam。`confidence`、路径交集、重复去抖，是这条规则能否活下来的前提。

`#7`：exit code 2 没问题，但前提是有稳定的 machine-readable `error.stage`，并且异常消息做过 redaction；否则只是把 traceback 换了个壳。

`#10`：Budgeter 的优先级应是：assignment contract > blockers > verification command > recommended tests > condensed semantic focus > raw semantic context > context store。不是“谁重要谁全留、剩下硬砍”。

### 对 8 个被砍项的判断

我**同意全部砍掉**，没有一个需要现在救回。最接近“以后可复活”的只有 `CMP-8 finding_refs`，但那不是因为它方向错，而是因为 relation contract 还没被定义；在 contract 未定前把它做成规则，只会制造高争议和高误报。

### 对 4 个被拒方向的判断

| 方向                             | 判断   | 强化理由                                                                                                                 |
| ------------------------------ | ---- | -------------------------------------------------------------------------------------------------------------------- |
| `ralph init` / 模板              | 同意拒绝 | 它不仅是优先级低；更危险的是它会把“当前 schema 偏好”固化成默认权威，后续 schema 演化会转化为模板迁移负担。                                                       |
| incremental / partial validate | 同意拒绝 | Ralph 的很多规则是全局耦合的：flow coverage、duplicate IDs、unused suppression、state refs。做 invalidation graph 的复杂度接近重写 validator。 |
| auto-severity from stats       | 同意拒绝 | 没有“是否被修复 / 是否被 suppress / 是否误报”的标签，只有 hit count；用它推 severity 是数值幻觉。                                                  |
| rule retirement 机制             | 同意拒绝 | “零命中”无法区分 dead rule、成功 deterrence、样本太新、或被全局 suppress。没有 rule introduction cohort 与 richer telemetry 前，退休判断不成立。       |

## 3. 维度 2 · 新建议

下面这些建议尽量避免和 23 项、被明确拒绝的方向、以及已有规则变种重叠。

### Tier 1

1. **`validation_provenance` / `ruleset_digest`** — kind: data flow
   动机：当你们上线新规则、切换 `semantic_mode`、或升级 semantic provider 后，同一份 plan 产生的新 findings 可能不是 “plan 变差了”，而是 “ruleset 变了”。现在无论 `validate --diff`、ledger audit、还是 worker prompt，都缺少这个归因层。
   落地约束：digest 需要覆盖 rule registry、semantic mode、provider version/config、suppression semantics，但必须排除时间戳等非语义字段。
   Tier：🏆

2. **Typed Evidence Schema** — kind: data model / CLI
   动机：你们现在多处依赖 `normalized evidence` 或 stringified evidence 做排序、diff、explain、ledger parity；这意味着 message copy edit、dict key 顺序变化、甚至渲染器重写都可能制造假变化。
   落地约束：每个 issue code 需要稳定 evidence schema 与 renderer；需要一次性迁移，但回报极高。
   Tier：🏆

3. **`action_owner` / `worker_relevance` on `ValidationIssue`** — kind: data model / prompt path
   动机：不是所有 findings 都该发给 worker。有些只该给 plan author，有些只该给 Foreman。没有 recipient 语义，#2 的 inclusion policy 只能靠猜。
   落地约束：需要给现有规则家族补注解；默认值可先设为 `author`，逐步回填。
   Tier：🏆

4. **Semantic Confidence & Freshness Surface** — kind: data flow
   动机：`recommend_tests`、`ConsistencyReport`、`suggested_deps` 只有在 provider 置信度和索引 freshness 足够时才可靠。没有这层元数据，#5 非常容易变成噪音源。
   落地约束：provider API 必须能返回 confidence / freshness；没有时要有明确 fallback，而不是伪精确。
   Tier：🏆

5. **Worker Acknowledgement Handshake** — kind: orchestration / ledger
   动机：如果 Ralph 开始把 issue digest 和 recommended tests 注入 worker prompt，那么 worker 完成任务时也应反馈“我处理了哪些 issue / 无法处理哪些 / 实际跑了哪些 tests”。否则新 prompt path 仍是单向广播。
   落地约束：需要扩 completion payload、适配多 worker、并定义“未回报”的语义。
   Tier：🏆

6. **Analyzer Capability Manifest** — kind: UX / report honesty
   动机：文档已经点出 Ralph 今天明显偏 Python；在 Flutter/TS/Rust 仓库里，某些 AST / filesystem 规则可能静默降级。最危险的不是“漏报”，而是用户把一份 clean report 当成“完整安全”。
   落地约束：每个 rule family 需要声明 capability tag，报告里展示 active/skipped analyzers 及原因。
   Tier：🏆

7. **Suppression Lease (`owner`, `reason`, `expires_on`)** — kind: governance
   动机：`H_SUPPRESS_UNUSED` 只能看到“这次没命中”，看不到“这个 suppress 三个月前为了临时迁移加的，现在没人认领”。抑制债务会越滚越大。
   落地约束：旧 suppress 需要兼容；可以只对新 suppress 强制 lease metadata。
   Tier：🏆

### Tier 2

8. **Rule Canary Channel** — kind: rollout / observability
   动机：新规则在刚落地时最容易误报。与其直接变正常 warning，不如先进入 `experimental_findings` 或 telemetry-only 通道，用真实命中率和人工采样评估后再升格。
   落地约束：要有规则生命周期管理，避免 “实验态永久化”。
   Tier：🥈

9. **Worker / Runtime Capability Negotiation** — kind: orchestration
   动机：推荐 tests、runtime adapter hints、甚至 verification command，不是每个 worker/runtime 都能执行。没有 capability negotiation，就会把不可能完成的 instruction 塞进 prompt。
   落地约束：需要为 worker/runtime 建立能力模型；Foreman 侧要能降级。
   Tier：🥈

10. **`ralph profile` / per-rule timing & cache stats** — kind: observability
    动机：半年后你们很可能不是先死在 correctness，而是先死在“为什么这个 plan validate 变慢了”。每条规则耗时、provider 耗时、cache 命中率都应可见。
    落地约束：profile 模式要低开销、默认关闭，并注意路径/命令 redaction。
    Tier：🥈

11. **Golden-plan Corpus** — kind: test strategy
    动机：规则级 fixture test 只能覆盖局部，覆盖不了 suppress + semantic + serialization + prompt path 的交互。一个经过脱敏的真实 plan corpus 能显著提高回归信心。
    落地约束：脱敏成本高，expected outputs 也会在规则演进中频繁更新。
    Tier：🥈

### Tier 3

12. **Language Adapter Registry** — kind: architecture
    动机：多语言支持长期不可避免；把 Python AST 假设一路带到 TS/Flutter/Rust 只会制造“虚假完整性”。
    落地约束：设计重、ROI 晚，不该抢当前这波 integrity/provenance 修复的优先级。
    Tier：🥉

## 4. 维度 3 · 系统级判断

### A. 边界问题

Ralph 的**核心**应该继续停留在“纯静态、确定性、side-effect-free 的 plan validator”。但系统整体可以有三个环：

* 核心环：`validate`，只看 plan + repo state + optional semantic provider，输出稳定 report。
* 适配环：Foreman/worker prompt adapter，把 report 变成执行信息。
* 历史环：`audit`、stats、ledger 分析。

按这个框架看，`ralph audit` 和 `#2 issue digest` 的方向都是对的，因为它们还在外环，没有把历史/agent 状态反灌进核心 validator。真正错误的方向，是让 `validate` 本身开始依赖 ledger 历史或 worker 回报来决定 findings。

### B. LLM 时代的 linter 形态

我会建议 Ralph 增加**第三种输出**，专门给 LLM worker 消费。传统 `error/warning/hint + free-text message` 适合人，不适合执行型模型。对 LLM 更有效的是一个 **`llm_bundle` / `assignment capsule`**，包含：

* `task_contract`: 任务目标、不可违背的约束、scope
* `blockers`: 会改变执行策略的 findings
* `tests_to_run`: selector、理由、置信度
* `semantic_focus`: 要看的 symbols / paths / deps
* `do_not_assume`: stale plan、missing deps、unsupported analyzers
* `omitted_context`: 被 budgeter 砍掉了什么

核心思想是：**对人给 severity，对模型给 actionability + confidence + ownership**。

### C. 23 项的执行顺序

你们的 α/β1/β2/γ/δ 分组**大体合理**，但我会调三处：

第一，把 `#7 Structured Internal Failure Envelope` 前移。它是后续所有 rollout 的保险丝，越早有越好。

第二，把 `#11 Text Output Semantic Parity` 和 `#3 Serialize Semantic Summary` 放得更近。不要让“机器视图已经增强了、人类视图还看不到”再持续一个 PR 周期。

第三，`#8` 不要进 Ralph validate 线，直接改成 Foreman/scheduler 可见性项，单独排到 orchestrator lane。

### D. 反事实思考：如果只能做 5 项

我的前 5 名是：

1. **#10 Prompt Budgeter**
   因为它是所有 worker-facing 增强的前置条件。没有它，#2/#4 只会把 prompt 继续做胖。

2. **#1 `W_REGISTERED_PLAN_STALE` + mutating-path digest guard**
   我把 caveat 算进实现里。它解决的是“作者以为自己在新 plan 上工作，系统其实还在旧 plan 上跑”的根本完整性问题。

3. **#2 Prompt Task Issue Digest**
   Ralph 已经知道 task 的问题，却没告诉 worker，这个信息断层太伤。

4. **R-2′ `plan.schema_version` + strict extras**
   吞 typo 是最隐蔽也最反直觉的配置错误来源之一，应该尽早堵住。

5. **#7 Structured Internal Failure Envelope**
   不是功能性感知最强的一项，但它能显著降低 rollout 和排障成本。

排在第 6 位的是 `#5`，但前提是你先有 confidence/freshness surface；否则它太容易噪音化。

### E. 方案之外的系统性风险

半年后 Ralph 最可能遇到的麻烦，我排第一的是：**truth surfaces 分裂导致的信任 erosion**。同一个问题，在 text、JSON、ledger、worker prompt、audit 里各长一个样，用户最后会问的不是“Ralph 发现了什么”，而是“我该信哪个 Ralph”。

第二个风险是 **suppression debt + rule governance**。规则越来越多后，团队会开始倾向于 suppress，而不是修 plan。没有 owner/expiry/provenance，规则体系会迅速失去锋利度。

第三才是 **性能与 provider 可靠性**。semantic provider、一堆 filesystem scan、以及更复杂的 prompt 组装，最终都会把 validate/prompt path 推向性能与稳定性瓶颈。

## 5. 反事实选 5

1. `#10 Prompt Budgeter`
2. `#1 W_REGISTERED_PLAN_STALE`（实现时补 mutating-path digest guard）
3. `#2 Prompt Task Issue Digest`
4. `R-2′ plan.schema_version + strict extras`
5. `#7 Structured Internal Failure Envelope`

不进前 5 但应保留的下一梯队：`#4 Recommended Tests Reach The Worker`、`#5 W_VERIFY_PASSED_BUT_SEMANTIC_INCONSISTENT`、`#3 Serialize Semantic Summary`。

## 6. 结论

**结论：本方案本质正确，但需要修改后执行。** 最少要先补齐 `#1` 的 mutation guard、把 `#10` 做成真正的 token-aware budgeter、并把 `#8` 从 Ralph validation 中移走，变成 Foreman 的调度可见性。
