# CCCC 问题清单 v5 (未解决) — Ralph 改进专项

> 全量版本（含历史归档）：[问题清单-v5-ralph-full.md](./问题清单-v5-ralph-full.md)
> 评估报告：[v58](./e2e-实战评估报告-v58.md) | [v57](./e2e-实战评估报告-v57.md) | [v51](./e2e-实战评估报告-v51.md) | [v50](./e2e-实战评估报告-v50.md) | [v48](./e2e-实战评估报告-v48.md) | [v47](./e2e-实战评估报告-v47.md) | [v42](./e2e-实战评估报告-v42.md)
> **本文档只保留未解决的改进项和已知局限。已完成条目与历史记录保存在 full 版本中。**
> 执行计划来源：[v60-执行计划.md](./v60-执行计划.md)（基于 v58 假完成调查 + 四份外部建议综合制定）

---

## 实施路线图

> 核心策略：不试图让 AI 不犯错，而是用机制逼迫系统交出 Layer 6（真实行为改变）的证据

| 阶段 | 内容 | 退出标准 |
|------|------|---------|
| 第一阶段 | M0 止血 + M2-A AF 修复 | 真实 E2E 中 AF 跑完整任务；归档冻结生效 |
| 第二阶段 | M1 规则补齐 + M2-B/C 模型选择/复盘 | `ralph validate` 自动拦截"AF 组件存在但主路径不调用"；`model suggest backend → codex`；空 EVALUATION 被阻断 |
| 第三阶段 | M4 回归场景 + M5 Flow 关口升级 | 6 个假完成回归场景全自动通过；flow 每步都有行为证据 |
| 第四阶段 ✅ | M3 蓝图中间层（v69 核心闭环 behavior-verified） | 一个真实 Task 拆成 ≥2 Module，mock I/O 黑盒验收 + 拼接通过 Task verify gate（pilot 端到端达成；全活体推广待后续） |

---

## 第一阶段：M0 止血 + M2-A AF 修复 —— 已完成（全部 behavior-verified）

M0-1~M0-5、FL-75 已迁入 [full 归档](./问题清单-v5-ralph-full.md#代码修复归档2026-06-06-v60-第二批m0-归档纪律--fl-75behavior-verified)。
AF-07（fire-and-forget 死循环 → 真异步 suspend-until-terminal）与 AF-08（plan 初始提交接入 AF 主路径）
已 behavior-verified，迁入 [full 归档（2026-06-07 AF-07/AF-08）](./问题清单-v5-ralph-full.md#代码修复归档2026-06-07-v60-第一阶段收尾af-07-异步重构--af-08-主路径接入behavior-verified)
（14 字段 evidence bundle + 双独立 live 主路径验证，全仓 3739 passed，Codex 复验 verdict=works）。**第一阶段全部完成。**

AF-09（AF compile 路径丢失 task.type → 选错 worker model）已 behavior-verified，迁入
[full 归档（2026-06-07 AF-09）](./问题清单-v5-ralph-full.md#代码修复归档2026-06-07-v60-第一阶段收尾续af-09-模型选择保真behavior-verified)
（task_ref_to_plan_task 白名单补 `type`；14 字段 evidence bundle；真实 TaskRef→bridge→compile→resolve_model_for_task
链路 4/4 pass + 删字段负向复现 4/4 fail；关联回归 99 passed；Codex 设计评审 verdict=adjust 已采纳——
scope 收窄、测试改到运行时选型层、parity 落 resolve_model_for_task）。衍生检测能力缺口 DG-12/DG-13 已记入 DG 规则族。

---

## 第二阶段：M1 规则补齐 + M2-B/C 主链路闭合

### DG-1（active-path reachability — 模块级第一道防线已 behavior-verified，迁入 full 归档）

模块级 active-path reachability 规则（`_check_active_path_reachability` / `W_INTEGRATION_DORMANT_PATH`）
已 behavior-verified，迁入
[full 归档（2026-06-07 v61 DG-1）](./问题清单-v5-ralph-full.md#代码修复归档2026-06-07-v61-第二阶段开篇dg-1-active-path-reachability模块级behavior-verified)
（entrypoint-seeded call-edge + activation-edge 模块图，per-module dormant 判定；真实 `ralph validate`
CLI 双独立验证 + Codex 独立对抗复核 verdict=works real_defects=[]，全仓 3751 passed；采纳 Codex
设计评审 5 finding + 独立复核 1 major 误报修复）。

**仍开放（移交 DG-14）**：函数级死分支 dormancy（漏报）、动态 importlib/getattr/星号导入/
package __init__ 相对导入·re-export 的可达性误判（误报）、warning→非可压制强制门升级。表中
compile-without-execute / doc-only-behavior-claim / write-without-consumer 属上述更深层语义，
模块级 reachability 仅部分触及。**博弈风险提示**：静态 AST 可被死分支（`if FORCE_RUN: call()`）绕过，
DG-1 作为第一道防线，须搭配 M1-5 行为证据门 + M4 回归场景多层拦截。

### FL-66（solve flow 集成测试验证不检测主路径接入，组件独立通过≠系统集成）

solve flow 的 step-4 gap check 和 Codex review 只验证"代码存在+单元测试通过"，
不验证"新代码是否被主路径调用"。v53 AF 引擎就是典型案例——零件造好了但没装到车上。

> **部分覆盖（v61）**：DG-1 的 W_INTEGRATION_DORMANT_PATH 在 `ralph validate` 已能拦截
> 「组件 import+call 接入了，但接到从声明 entrypoint 不可达的死路径」这一典型形态（模块级）。
> 完整覆盖（函数级死分支、动态/re-export 接入）待 DG-14。

### RV-48（validate 不检测 plan 声称的集成是否有主路径调用证据）

task 声称集成 A→B 但实际只在测试中 mock 了 A→B 而未改动 A 的生产代码时，
validate 无法区分"真集成"与"测试级伪集成"。

> **部分覆盖（v61）**：DG-1 模块级 reachability 已能识别「生产侧确有接入但落在不可达模块」的伪集成；
> 「只在测试 mock、生产零接入」由既有 W_INTEGRATION_NO_PRODUCTION_CALL_EVIDENCE 家族负责。
> 函数级/动态导入的剩余盲点待 DG-14。

### DG-3（observable-fallback）—— 已 behavior-verified，迁入 full 归档

except 静默兜底（吞异常/非抛出退出且无 >=WARNING 日志/ledger emit）检测规则
`_check_observable_fallback` / `W_SILENT_FALLBACK` 已 behavior-verified，迁入
[full 归档（2026-06-07 v62）](./问题清单-v5-ralph-full.md#代码修复归档2026-06-07-v62-第二阶段批量dg-3--dg-4--m2-cux-23--m2-bbehavior-verified)
（真实 `ralph validate` 翻转 + 双独立对抗验证，首轮发现自违例/claimed-paths 盲区已修 CLOSED，全量 3775 passed）。
**仍开放**：间接 helper 信号可达性（DG-17）、warning→非可压制强制门升级（待误报率验证，DG-14 族）。

### DG-4（guard-ordering）—— 已 behavior-verified，迁入 full 归档

守卫顺序规则 `_check_guard_ordering` / `W_GUARD_AFTER_SIDE_EFFECT`（同函数级，窄映射
emit_workflow_terminal/on_workflow_completed ↔ workflow_evaluation_empty_sections/_check_section_substantive）
已 behavior-verified，迁入 [full 归档（2026-06-07 v62）](./问题清单-v5-ralph-full.md#代码修复归档2026-06-07-v62-第二阶段批量dg-3--dg-4--m2-cux-23--m2-bbehavior-verified)。
**仍开放（移交 DG-16）**：跨函数/调用栈守卫支配关系；archive commit / actor dispatch 副作用对的映射扩展。

### DG-2（semantic-default consistency）—— 第一道防线（file-touch 启发式）已 behavior-verified（v64）

**v64 落地**：新增 `src/cccc/ralph/validation_rules/semantic_defaults.py` ——
静态 registry `SEMANTIC_DEFAULT_GROUPS`（首个 group `executor_runtime` / canonical=codex /
5 个 grep 核实的真实定义点：agent_pool.py、assignment_actor_registration.py、agent_ops.py、
kernel/actors.py、actor_add_ops.py）+ 规则 `_check_semantic_default_consistency` /
`W_SEMANTIC_DEFAULT_PARTIAL_UPDATE`（命中定义点真子集即告警，全覆盖/全不命中不报），已接入
`__init__.get_all_rules` + `validator._collect_structural_issues`（CLI `ralph validate` 活跃路径）。
validate_with_project 在合成 fixture 上翻转（部分命中告警 / 全覆盖不报 / 无关不报 / registry 真实性
os.path.exists），10 passed；step-3 Codex 评审 F5 采纳（清单补全 + 文档化范围）；全量 3816 passed。
**仍开放（移交 DG-20）**：本规则是 file-touch 启发式，**不解析文件内容值**——「定义点都改了但实际
默认值仍与 canonical 漂移 / 单点值漂移」（如 agent_ops 载入路径残留 "claude"）无法检测，需内容级
AST/字面值比对。

同一语义默认值不能散落在多个文件里各自硬编码。建立 semantic defaults registry：

```yaml
semantic_defaults:
  executor_runtime:
    canonical: codex
    allowed_overrides:
      - security_review
      - frontend_aesthetic_review
    definitions:
      - agent_pool.py
      - assignment_actor_registration.py
      - actor_cli.py
```

task 修改其中一个定义点时，Ralph 必须提示其它同语义定义点。

**实证（v60 FC 批次 solve 复盘）**：本轮 Codex review 抓到两处 `ralph validate` 无法检测的语义默认/过滤一致性缺口，正好印证 DG-2，可作固定 fixture：
1. `executor_runtime` 兜底默认散落：FC-1 改了 `agent_pool.py` / `assignment_actor_registration.py` 的 `or "claude"→codex`，但 `agent_ops.create_agent()` 仍残留 `model_runtime="claude"` 默认；validate 无规则检测「同一执行兜底默认在某定义点未同步」。
2. `enabled` 过滤未覆盖全部消费端：FC-2 给 `select_model_for_task()` 加了 `enabled` 过滤，但并行的复用打分路径 `agent_pool.evaluate_for_task()` 未过滤，可复用绑定到 disabled 模型的 agent；validate 无规则检测「同一 registry 的过滤不变量在某消费端缺失」。
> 两处均为人工 Codex review 才发现、单元测试与 validate 均放行 → DG-2 应同时覆盖「兜底默认同步」与「过滤不变量跨消费端覆盖」两类 check。修复已落地（reuse-path enabled gate + create_agent 默认 codex），但**检测规则仍缺**。

#### DG-5（validate 无法检测「检查规则的解析定位器与真实数据格式漂移 → 死规则」）

v60 M0 批次 step-3 Codex review 发现：`flow_improvement_check._full_tracker_archive_paragraph`
的段落 locator 只匹配 `^#### {issue_id}`，但真实 full tracker 归档段落实际是
`**{ID} evidence bundle**` + `- field: value` 列表项格式。该检查规则在合成 `#### ID`
fixture 上能正确翻转 pass/fail，在真实 tracker 上却定位不到段落、静默放行——
即"测试绿、生产失效"的死规则。`ralph validate` / flow check 当前无能力检测
「某 detection rule 的输入解析格式与系统真实产出格式不一致」这类 coverage 盲区。
本批 T2 修复了该具体 locator，但**通用检测规则仍缺**：需要一类 check 验证纪律规则的
解析器在真实 tracker 样本上至少命中一个段落（rule-on-real-data smoke），否则规则可能
长期空转而无人察觉。

#### DG-6（validate 无法检测「阻断门的输入无任何生产写入路径 → 休眠门」）

step-3 Codex review 发现：M0-5 deferral 阻断门 `_check_plan` 读取 ledger，但若无任何
生产路径调用 `record_deferral` 写入，则"连续 2 轮 defer → 升级 P0 → 冻结"这条链在主路径
上永不触发，检查只能靠手工 seed ledger 演示。这是 DG-1 active-path reachability 的镜像：
DG-1 查 write-without-consumer（写了没人读），此处是 **gate/consume-without-producer**
（读/拦了没人写）。`ralph validate` 无 rule 检测「某 gate/check 依赖的状态输入缺少可达的
生产写入点」。本批 T5 显式补了 step-4 写入点，但**通用 reachability 检测规则仍缺**，
应纳入 DG-1 规则族扩展。

#### DG-7（validate 无法检测「证据/归档检查用整段 substring 包含而非字段值解析 → 填词绕过」）

step-3 Codex review 发现：`_check_archive_evidence_bundle` 用整段 `field:` 子串包含判断，
不解析字段值，导致把 `regression_test:`（空值）或在别处塞 `behavior-verified` 词即可过闸。
这与 RV-51/RV-59「文本关键词可被同义/填词绕过」同源，但更具体：`ralph validate` 无 rule
检测「某 evidence/discipline check 的字段判定停留在 substring 层，未做 field→value 解析与
非空校验」。本批 T2/T4 改为按行解析 + 负向反例，但**通用检测规则仍缺**（防御有静态上限，
见已知局限 RV-51/RV-59）。

> DG-5/DG-6/DG-7 均由 v60 M0 批次 step-3 Codex review 发现、`ralph validate` 当前放行 →
> 应作为 DG 规则族的固定 detection-capability 缺口跟踪；本批仅修复具体实例，通用规则待后续。

<!-- v60 AF-07 异步设计评审（step-3 Codex review，2026-06-06）新增 DG-8~DG-11 -->

#### DG-8（validate 无法检测「跨调用链的匹配/身份键未端到端贯通 → 消费端永远匹配不上」）

AF-07 异步重构 step-3 Codex review（F2 blocker）发现：T4 的 apply_task_event→gateway 桥接
需要用 attempt_id 把真实 worker terminal 匹配回同一 AF wait，但该身份键在 ingress 链路
（`ralph_ipc_handler.handle_ralph_task_event` → `workflow_task_ops.complete_task/fail_task`
→ orchestrator `apply_task_event`）并未端到端贯通：completed 路径不透传 attempt_id、
`fail_task` 根本无该形参。结果是「生产端声明用 attempt_id 匹配，但中间某跳把键丢了」→
消费端（AF wait）永远等不到、或 retry 时旧键误配新 wait。`ralph validate` 无 rule 检测
「某 detection/匹配逻辑依赖的 identity/correlation 字段是否在其完整生产调用链的每一跳都被
传递」——这是 DG-1 write-without-consumer 的镜像延伸（write 与 consume 之间的中间 hop 漏传）。
本批 T3 修复该具体链路，但**通用「跨层身份键连续性」检测规则仍缺**。

#### DG-9（validate 无法检测「并发 producer/consumer 的登记早于副作用顺序 → 丢唤醒竞态」）

step-3 Codex review（F1 blocker）发现：异步事件桥若把 active gateway / inflight 的登记放到
后台执行线程里，而 send 触发的快 worker 可能先于登记到达 apply_task_event → 桥接按规则跳过
→ AF wait 永挂到 timeout（非互斥死锁，而是唤醒事件被错过）。这是 DG-4 guard-ordering 在
并发场景的延伸：DG-4 查「阻断门必须在副作用前」，此处是「唤醒注册必须在产生唤醒事件的副作用
（send）之前、且在 return 之前」。`ralph validate` 无 rule 检测「concurrent wakeup 的
register-before-side-effect 时序不变量」。本批 T5 强制 caller 线程登记，但**通用时序检测仍缺**。

#### DG-10（validate 无法检测「dispatch/retry 路径缺少有界 attempt 预算 → 无上限重试风暴」）

step-3 Codex review（F3 major）发现：去重仅按 attempt_id 挡同一 attempt 二次派发，挡不住
override/retry 生成新 attempt_id 后的顺序无限重派——把毫秒级 death loop 变成较慢但仍无上限的
真实重试风暴。`ralph validate` 无 rule 检测「某 dispatch/retry/override 循环是否存在
有界 attempt budget / circuit breaker 终止条件」（与 M0-5 反推诿锁死同属「无界循环需熔断」
家族，但针对 runtime dispatch 路径）。本批 T5 加 max-attempt 熔断，但**通用熔断缺失检测仍缺**。

#### DG-11（validate 无法检测「语义变更使既有回归断言静默失效，但其测试未纳入 plan 范围」）

step-3 Codex review（F4 major）发现：本批移除 synthetic completion + 改 fail_task 签名会让
若干既有测试（`test_workflow_orchestrator_apply_event.py` 的 ASSIGNED→completed auto-start 门、
`test_foreman_workflow.py` 的 AF/attempt 语义、`test_ralph_ipc.py` 枚举契约等）所断言的旧契约
发生漂移；若 plan 只列新增测试、不显式纳入这些既有测试，会出现「新测试全绿但老契约悄悄漂移」。
`ralph validate` 无 rule 检测「plan 改动的 symbol/contract 是否有既有测试断言它，且这些测试
是否被 claimed_paths/verification 覆盖」（比 RV-52 更具体：不是关键词改动，而是 contract-change
未枚举受影响 regression surface）。本批 T6 显式列出必改/必保清单，但**通用检测规则仍缺**。

> DG-8~DG-11 均由 v60 AF-07 异步重构 step-3 Codex review 发现、`ralph validate` 当前放行 →
> 纳入 DG 规则族 detection-capability 缺口；本批仅在 T3/T5/T6 修复具体实例，通用规则待后续。

<!-- v60 AF-09 step-4 gaps (2026-06-07)：DG-12 AF adapter 字段 parity + DG-13 双引擎选型 parity -->

#### DG-12（validate 无法检测「AF compile 适配器静默丢弃 downstream 路由依赖字段 → 选型降级」）

v60 AF-09 step-3 Codex review（minor finding）发现：`af_gateway_bridge.task_ref_to_plan_task`
的字段白名单漏传 `type`，使 AF 编译出的 node 丢失 `TaskRef.type` → `PlanCompiler` 回落
`general` → `agent_pool` 按 `task.type` 选 worker 时降级到 general worker（实测 AF 选
`codex-general-worker`，控制面 assignment 是 `codex-backend-worker`）。`ralph validate`
当前无 rule 检测「某 AF/IPC bridge 适配器（TaskRef → plan-task dict 投影）是否透传了所有被
downstream 控制逻辑消费的字段」。这是 DG-1 write-without-consumer 的镜像变体：字段在
producer（TaskRef contract）存在、consumer（`agent_pool` 选型）依赖，但中间投影 helper 丢字段，
单元测试与 validate 均放行。**修复方向（detection rule）**：AF metadata field-parity check ——
对 TaskRef 中被 downstream routing/选型消费的字段集合（至少 id/type/claimed_paths/role/
verification）做静态投影 coverage 校验，若 `task_ref_to_plan_task` 等 bridge helper 未列入则
报 warning。本批 T1 仅修复 `type` 具体实例，通用 parity 检测规则仍缺。
- issue_id: DG-12
- detection_type: af-adapter-field-parity（静态投影字段白名单 coverage 规则）
- description: validate 无法检测 AF bridge 适配器丢弃 downstream 消费字段导致 worker 选型降级

#### DG-13（validate 无法检测「两条执行引擎各自独立重算同一选型决策、缺 parity 断言 → 选型漂移」）

v60 AF-09 step-3 Codex review（major findings）+ AF-09 修复后 Codex 独立对抗核验（2026-06-07，
verdict=incomplete，独立脚本复现）确认：AF 模式下 control-plane 先 `调用`
`create_or_reuse_agent()` 算出 assignment / `preferred_model_key`，AF 真执行时 `actor_runner`
又以 `mode="auto"` 再次 `agent_pool.acquire` 重新选模；且 AF compile path 不写、`_acquire_auto_agent`
也不消费 `preferred_model_key`。即使 `type` 修好，两条执行路径仍各自独立调用 `select_model_for_task`，
无任何 parity 断言或调用链证据证明二者一致。**Codex 独立复现的两个真实旁路（即便 type 已修仍存在）**：
1. **suggestion_gap**：`suggestion_gap {'control_plane_with_suggestion': 'general-key',
   'af_runtime_without_suggestion': 'backend-key'}` —— `task_model_suggestions`/`preferred_model_key`
   存在于 `workflow.py`/`assignment_batches.py`，但未传到 AF runner→`_acquire_auto_agent`，故 AF
   实际选型与控制面 suggestion 不兑现。
2. **group-peer reuse 旁路**：`group_peer_lease {'task_type': 'backend',
   'model_id': 'general-model-id', 'agent_id': 'peer-general'}` —— `AgentPoolManager._find_group_peer_agent`
   复用分支不经 `resolve_model_for_task`，backend 任务复用 group-peer 时仍可拿到 general 模型
   （与 DG-2 实证 #2「reuse path enabled/选型不变量缺失」同源）。
`ralph validate` 无 rule 检测「同一语义决策（worker 选型）由两条执行路径分别计算、或经 reuse/peer
分支绕过按 type 选型时，是否汇聚到单一权威 selector 或带 parity 校验」。属 DG-2 semantic-default
一致性家族延伸（从「散落的默认常量」扩到「散落的决策计算路径 + 复用旁路」）。**修复方向**：
(a) AF compile/runner 透传并由 acquire 消费 `preferred_model_key`；(b) reuse/group-peer 分支按 task.type
校验所选 model；(c) 检测规则验证双引擎对 model_key 的计算单一来源或带 parity 断言。
AF-09 范围内不修（Codex 设计评审明确建议收窄 scope 为「修复 `type` 降级」，不过度宣称 parity），
记为 detection-capability 缺口 + 运行时行为缺口 + 已知局限。
- issue_id: DG-13
- detection_type: dual-path-decision-parity（跨执行引擎选型一致性 + reuse 旁路选型 rule）
- description: validate 无法检测两条执行路径独立重算 worker 选型、或 reuse/group-peer 分支绕过按 type 选型导致的选型漂移（Codex 独立复现 suggestion_gap + group_peer_lease 两旁路）

> DG-12/DG-13 均由 v60 AF-09 step-3 Codex review 发现、`ralph validate` 当前放行 →
> 纳入 DG 规则族 detection-capability 缺口；本批 T1 仅修复 DG-12 的 `type` 具体实例，
> 通用 field-parity / dual-path-parity 检测规则待后续。

<!-- v61 DG-1 active-path reachability step-3 Codex review（2026-06-07，verdict=incomplete）新增 DG-14 -->

#### DG-14（active-path reachability 只是模块级语法启发式——函数级死分支 + 动态/re-export 导入无法判定）

v61 DG-1 step-3 Codex review（verdict=incomplete，多 major finding）确认：本批落地的
`_check_active_path_reachability`（W_INTEGRATION_DORMANT_PATH）是「entrypoint-seeded、module-level、
syntactic heuristic」，对真实 dormancy 的判定有两类系统性盲点，`ralph validate` 当前无能力覆盖：
1. **函数级/控制流盲点（漏报方向）**：可达模块内「死分支（`if False:`）或从不被调用的函数」里
   出现的 `ast.Call` 仍会在模块级图上生成可达边——真实位于死分支后的 dormant 接入被误判为
   reachable。需要 function/control-flow-aware reachability（调用图下沉到函数级）才能检测。
2. **动态/re-export 导入解析盲点（误报方向）**：`importlib.import_module`/`getattr(mod, name)()`、
   星号导入、条件导入，以及既有 helper 对 package `__init__.py` 相对导入的解析缺陷
   （`_module_name_from_rel_path` 把 `src/pkg/__init__.py` 归一为 `pkg`，但
   `_resolved_import_from_module_name` 按普通模块去尾段解析相对导入，使 `from . import af_engine` /
   `from .af_engine import execute` 解析不出 `pkg.af_engine`）——真实可达模块经 package initializer /
   re-export / 动态 dispatch 接入时会被误报为 dormant。`ralph validate` 无 rule 验证「import 解析器
   在 package re-export / 相对导入 / 动态导入样本上的可达性判定正确性」。
此外，本批 W_INTEGRATION_DORMANT_PATH 为 warning 且默认可 suppress，「能检测」≠「能封堵」——
是否升级为 `_NON_SUPPRESSIBLE_ALWAYS` 强制门须待误报率验证（与 #2 的误报盲点直接相关）。
本批 DG-1 仅落地模块级启发式 + activation-edge（自注册）覆盖，**函数级可达性 / 动态导入解析修复 /
强制门升级 仍缺**，记为 detection-capability 缺口待后续。
- issue_id: DG-14
- detection_type: function-level-reachability + dynamic-import-resolution（调用图下沉 + import 解析正确性 rule）
- description: validate 的 active-path reachability 仅模块级语法启发式，无法检测函数级死分支 dormancy，且对 package re-export/相对导入/动态 dispatch 误判可达性

> DG-14 由 v61 DG-1 step-3 Codex review 发现、本批显式收窄 DG-1 规则定位为「第一道防线 warning」
> 后留存的 detection-capability 缺口 → 纳入 DG 规则族；本批不修，待函数级可达性 + import 解析
> 专项实现。FL-66/RV-48 由 DG-1 模块级 reachability 部分覆盖（接到死路径可拦），完全覆盖需 DG-14。

<!-- v62 批次（DG-3 + DG-4 + M2-C/UX-23 + M2-B）step-3 Codex review（verdict=incomplete，9 finding 全采纳）
     落地后留存的 detection-capability 缺口：DG-15（writer↔checker 标题 parity）、DG-16（跨函数守卫顺序）、
     DG-17（observable-fallback 间接信号）。本批 DG-3/DG-4 规则均已挂入 validator._collect_structural_issues
     （validate_with_project / CLI `ralph validate` 的活跃路径），非死代码。 -->

#### DG-15（validate 无法检测「文档/模板 writer 生成的章节标题集合 与 其 checker/parser 解析的标题集合漂移 → 死章节 / 休眠判定输入」）

v62 M2-C step-3 Codex review（F3 blocker）发现：WORKFLOW_EVALUATION 的 writer
（`workflow_evaluation_io.py`）只自动生成 5 个固定反馈 section，而要新增的「八维定性维度」
若只在 checker（`_check_section_substantive`）侧按标题判定、writer 侧不生成对应子标题，则这些
维度标题既不会被自动产出、parser 也切不到 → 检查永远命中不到（休眠门，DG-6 镜像变体），或
反向：writer 生成了某标题但 checker 不解析 → 死章节。`ralph validate` 无 rule 检测「同一结构化
文档的 writer 产出标题集合 与 该文档 detection/substantive checker 解析/要求的标题集合是否一致」。
与 DG-5（检查规则的解析定位器与真实数据格式漂移）同源、但定位在 **writer↔checker 两侧 schema parity**
（不是规则 locator vs 真实样本，而是同仓内生成器与校验器对同一文档的标题契约漂移）。本批 T3 在
writer 与 parser 两侧同时落地八维标题保持一致，但**通用 writer↔checker 标题/字段 parity 检测规则仍缺**。
- issue_id: DG-15
- detection_type: writer-checker-section-parity（结构化文档生成器与校验器的标题/字段集合一致性 rule）
- description: validate 无法检测结构化文档 writer 生成的章节集合与其 checker 解析/要求的集合漂移导致的死章节/休眠判定

#### DG-16（guard-ordering 仅同函数内语句序判定——守卫与副作用分处不同函数/跨调用栈时的顺序漂移无法检测）

v62 DG-4 step-3 Codex review（F6 major，收窄映射后）确认：本批落地的 `_check_guard_ordering`
（W_GUARD_AFTER_SIDE_EFFECT）按**同一函数体内**的 `ast.Call` lineno 判定「守卫先于副作用」，
对「守卫调用与受管副作用分处不同函数/方法（如守卫在 caller、emit 在 callee，或反之）」的跨调用栈
顺序漂移无能力判定（漏报方向）；且映射表为保守白名单（仅 emit_workflow_terminal/on_workflow_completed
↔ workflow_evaluation_empty_sections/_check_section_substantive），新副作用/守卫对需手工扩表。
`ralph validate` 无 rule 检测「跨函数调用栈上守卫节点是否支配（dominate）副作用节点」——需函数间
控制流/调用图下沉（与 DG-14 的函数级可达性同属「模块/函数级语法启发式不足」家族）。本批仅落地
同函数级第一道防线 warning，**跨函数 guard 支配关系检测仍缺**。
- issue_id: DG-16
- detection_type: cross-function-guard-dominance（跨调用栈守卫支配副作用的顺序 rule）
- description: validate 的 guard-ordering 仅同函数语句序，无法检测守卫与副作用分处不同函数时的顺序漂移

#### DG-17（observable-fallback 仅识别直接 logger.warning+/ledger-emit 调用名——经间接 helper 发出的可观测信号会误报，且白名单外信号漏检）

v62 DG-3 step-3 Codex review（F5 major）确认：本批 `_check_observable_fallback`
（W_SILENT_FALLBACK）按 except handler 体内是否出现**直接调用名** logger.warning/error/exception/
critical、logging.warning+、append_event/publish_event 判定「有无可观测信号」（并显式排除 `_log`
等普通状态播报）。对「实际有信号、但经间接 helper 包一层（如 `self._emit_warning(...)`→内部再
logger.warning）」的 handler 会误报为静默（误报方向）；对白名单外的真实告警通道（其它日志封装/
事件 API）漏检（漏报方向）。`ralph validate` 无 rule 跨函数解析「兜底作用域是否最终触达 >=WARNING
日志或 ledger 写入」——需信号可达性（调用图下沉到 helper 内部）。本批为可 suppress 的第一道防线
warning，**间接信号/封装日志的可达性判定仍缺**。
- issue_id: DG-17
- detection_type: fallback-signal-reachability（兜底作用域到 >=WARNING 信号的跨函数可达性 rule）
- description: validate 的 observable-fallback 仅识别直接调用名信号，无法判定经间接 helper 发出的告警信号

> DG-15/DG-16/DG-17 均由 v62 step-3 Codex review（verdict=incomplete）发现、`ralph validate` 当前放行
> → 纳入 DG 规则族 detection-capability 缺口；本批 T1/T2/T3 仅落地各自第一道防线规则的具体实例，
> 通用的 writer↔checker parity / 跨函数守卫支配 / 兜底信号可达性 检测规则待后续专项。

<!-- v63 批次（M1-5 verification 主路径行为命令门）step-3 Codex 设计评审（verdict=adjust，5 finding 全裁决）
     落地 W_VERIFICATION_NO_MAIN_PATH_COMMAND 后留存的 detection-capability 缺口：DG-18（命令与被修
     flow 的因果关联）、DG-19（launcher/wrapper/subshell 主路径解析残余）。 -->

#### DG-18（validate 无法检测「主路径命令是否与被修复的 flow/entrypoint/运行时输出有因果关联 → 无关命令/陈旧日志充作行为证据」）

v63 M1-5 step-3 Codex review（F3 major）发现：新规则 `_check_verification_main_path_command`
（W_VERIFICATION_NO_MAIN_PATH_COMMAND）只能检测 verification 里「存在某类主路径命令」（程序名为
`cccc`/`ralph` 的 CLI，或对 `.log` 的 grep），但**无法证明该命令真的执行了被改动子系统的主路径**：
一条与本 task 覆盖的 flow/entrypoint 毫无关系的 `ralph validate`、一段陈旧或预生成的 `.log` grep，
都能让该 task「看起来有主路径行为证据」而过闸。`ralph validate` 无 rule 校验「verification 中声称的
主路径命令是否与 task 覆盖的 critical_flow / critical entrypoint / 预期 daemon 输出 / artifact 存在
可验证的关联」。这是 M1-5 第一道防线的语义上限：它把「行为证据存在性」当作「行为证据相关性」。
**修复方向（detection rule）**：把主路径命令与 task 的 covers.flows/claimed entrypoint/期望事件做
关联校验（如命令引用的子命令/日志路径需指向被覆盖 flow 的产物）。本批仅落地存在性门，关联性检测仍缺。
并连带 DEFERRED：critical_flow 命中是否由 warning 升 error / 不可 suppress（沿用 DG-1/3/4「强制门
升级待误报率验证」约定，evidence 已带 covered_critical_flows 供后续升级）。
- issue_id: DG-18
- detection_type: main-path-command-causal-linkage（主路径命令与被覆盖 flow/entrypoint 关联性 rule）
- description: validate 仅检测主路径命令存在性，无法检测该命令是否与被修复 flow/entrypoint/运行时输出因果相关，无关 CLI/陈旧日志可伪造行为证据

#### DG-19（validate 的命令解析对 launcher/wrapper/subshell/脚本再执行的主路径识别残余盲点）

v63 M1-5 step-3 Codex review（F4 minor）发现：`_is_main_path_command` 已复用
`filesystem_validator._unwrap_command` 剥离 `env`/`timeout`/`uv run`/`poetry run`/`pipenv run` 等
保义 wrapper 后按真实程序名判定（堵住 `python -m pytest tests/ralph/...` 路径含 "ralph" 的误判），
但对 `bash -lc 'ralph ...'`、`sh -c '...'`、子 shell `( ... )`、`xargs`、以及「自定义脚本内部再调
主路径命令」这类 launcher，仍会把真实主路径调用解析不出、误判为「无主路径命令」（误报方向）。
`ralph validate` 无 rule 通用地解析「命令经任意 launcher/wrapper/脚本封装后最终执行的程序」。
属 DG-19 命令解析能力缺口（与 DG-14 函数级可达性、DG-17 信号可达性同属「静态启发式解析能力不足」家族）。
本批为可 suppress 的第一道防线 warning，通用 launcher 解析待后续。
- issue_id: DG-19
- detection_type: launcher-wrapper-command-resolution（命令经 launcher/wrapper/subshell 封装后的真实程序解析 rule）
- description: validate 的主路径命令解析无法识别经 bash -lc/subshell/自定义脚本封装的命令，造成主路径误判（误报）

> DG-18/DG-19 均由 v63 M1-5 step-3 Codex review（verdict=adjust）发现、`ralph validate` 落地存在性门后
> 仍放行 → 纳入 DG 规则族 detection-capability 缺口；本批 M1-5 仅落地「主路径命令存在性」第一道防线，
> 因果关联校验 / 通用 launcher 解析待后续专项。

<!-- v64 批次（DG-2 + M1-6 + FL-73）step-3 Codex 设计评审（verdict=incomplete，8 finding 全采纳）
     落地后留存的 detection-capability 缺口：DG-20（DG-2 内容级默认值一致性）、DG-21（FL-73 派发宽度强匹配）。 -->

#### DG-20（validate 的 semantic-default 规则只比对 claimed_paths 是否触及定义文件，不解析文件内容值 → 内容级默认值不一致漏检）

v64 DG-2 step-3 Codex review（F5 major）确认：本批落地的 `_check_semantic_default_consistency`
（W_SEMANTIC_DEFAULT_PARTIAL_UPDATE）是 **file-touch 启发式** —— 只判定 plan 的 claimed_paths
是否命中 `SEMANTIC_DEFAULT_GROUPS` 某 group 定义文件集合的「非空真子集」（改了部分定义点漏了其它），
**完全不读取文件内容、不比对各定义点的实际默认值是否等于 canonical**。因此对「定义点全被某 plan
touch（不报）但其中某文件的实际默认值已与 canonical 漂移」这类内容级不一致无能力检测——实证：
`agent_ops.py` 载入路径残留 `"claude"` 默认，与 `agent_pool.py` / `assignment_actor_registration.py` /
`kernel/actors.py` / `actor_add_ops.py` 的 `"codex"` 默认不一致，`ralph validate` 即便补全 registry
清单也只能在「改一处漏一处」时报警，无法在「都改了但值仍不一致」或「单点值漂移」时报警。`ralph validate`
无 rule 解析「同一 semantic default group 各定义点的实际默认字面值是否一致地等于 canonical」——需源码
内容级 AST/字面值比对（与 DG-5「检查规则解析定位器与真实数据格式漂移」同属「静态规则只看结构不看值」家族）。
本批仅落地 file-touch 第一道防线，**内容级默认值一致性检测仍缺**。
- issue_id: DG-20
- detection_type: semantic-default-value-consistency（各定义点实际默认字面值与 canonical 的内容级一致性 rule）
- description: validate 的 semantic-default 规则仅比对 claimed_paths 触及面，不解析文件内容值，无法检测各定义点实际默认值与 canonical 漂移或彼此不一致

#### DG-21（flow step-5 并行度 gate 的实际派发宽度 D 按文件名计数，缺 task_id↔plan-task 强匹配 → D 可被伪造/误计）

v64 FL-73 step-3 Codex review（F8 major）确认：本批落地的 step-5 并行度 gate 以
`.ralph-flow/step-5-execute/` 下「有效 codex 输出 json（success=true）按文件名 stem 去重」的数量作为
**实际派发宽度 D** 的证据，但 `flow_engine.py` 的 codex json 校验只认 SESSION_ID / HMAC / success /
message 长度，**payload 中无 task_id**，D 与 plan task 的对应仅靠文件名约定。后果：一个独立任务被写成
多个不同 stem 的 json 可虚增 D（绕过 fail-closed）；或文件名不符约定使真实派发的 task 计不进 D（误报）。
`ralph validate` / flow 无 rule 校验「step-5 每个 codex 输出 json 是否携带可信 task_id 且与 plan
task 集合一一对应」——需在 codex 输出 payload 注入 task_id 并做 json↔plan-task 强匹配（与 DG-18
「主路径命令与被覆盖 flow 缺因果关联」同属「证据存在性≠证据与目标对象绑定」家族）。本批 D 计数为粗粒度
可绕过的第一道防线，**task_id↔plan-task 强匹配仍缺**。
- issue_id: DG-21
- detection_type: dispatch-width-task-identity-binding（step-5 派发 json 与 plan task 的 task_id 强匹配 rule）
- description: flow step-5 并行度 gate 的实际派发宽度 D 按文件名 stem 计数、codex json 无 task_id，D 可被重复/畸形文件伪造或误计

> DG-20/DG-21 均由 v64（DG-2 + FL-73）step-3 Codex review（verdict=incomplete）发现、落地各自第一道
> 防线（file-touch 启发式 / 文件名计数）后仍放行 → 纳入 DG 规则族 detection-capability 缺口；
> 本批仅落地第一道防线，内容级默认值一致性 / 派发宽度 task_id 强匹配待后续专项。

<!-- v65 批次（M2-B 读端闭合）step-3 Codex 设计评审（verdict=incomplete，6 finding/3 blocker 全核实属实）
     暴露的 `ralph validate` detection-capability 缺口：DG-22~DG-26 + 命名空间统一 deferred MSE-NS。
     这 6 个 finding 在原计划（共享 handler 事后留痕 + 别名表）下 `ralph validate` 全部放行（compact
     PASSED），仅 Codex 设计评审抓出 → 正是「validate 无法检测主链路假闭合」的又一批实例。 -->

#### DG-22（validate 无法检测「决策/选择事件只被写入、却未被消费去驱动它所声称治理的运行时行为 → 事后记账冒充闭合」）

v65 M2-B step-3 Codex review（F2 blocker）发现：原计划在 `handle_actor_add` **创建 actor 之后**才
追加 `model.selection_decision`，而 runtime 早在上游就由 `args.runtime or "codex"` 决定——即「选型
事件写了，但从未驱动本次创建的 runtime」。这条 task 极易靠断言 ledger 多一条事件让 pytest 变绿，
主路径却仍是默认 `--runtime`/profile 逻辑。`ralph validate` 无 rule 检测「某 decision/selection
事件的产出点是否在它所治理的副作用（runtime/command 决定）**之前**，并真正作为该副作用的输入被消费」
——这是 DG-1 write-without-consumer 的镜像变体（写了但消费方不读，此处是「写在副作用之后、根本来不及
被消费」），也与 DG-4 guard-ordering 同族（顺序不变量），但针对「选型→驱动」语义。本批 T1 改为选型
前置并驱动 runtime，但**通用「decision 写入须被 downstream 行为消费」检测规则仍缺**。
- issue_id: DG-22
- detection_type: decision-recorded-but-not-consumed（选型/决策事件须前置并驱动其治理的副作用 rule）
- description: validate 无法检测决策事件只写不被消费驱动运行时行为（事后记账），主路径行为未真正改变即假闭合

#### DG-23（validate 无法检测「被两类调用方共享的 handler 重复/矛盾地发出某逻辑实体已由上游 producer 写过的证据事件 → 双写/污染」）

v65 M2-B step-3 Codex review（F1 blocker）发现：`handle_actor_add` 同时服务「手工 cccc actor add」
与「foreman 按 task 注册 worker」两类调用方；foreman 路径已在上游 `agent_pool.resolve_model_for_task`
选型并由 `assignment_batches` 写过 **task 级** `model.selection_decision`。原计划在共享 handler 里对所有
actor 再按 `general` 写一条 **actor 级** decision，会对 foreman worker 产生重复且可能矛盾的证据（安全审查
worker 真实建议可能是 claude，actor-add 侧却记成相对 general/codex 的 override）。`ralph validate` 无 rule
检测「某 ledger 事件/证据在一个被多调用方共享的 handler 中产出时，是否与上游 producer 对同一逻辑实体
（task/actor）已写的同类事件重复或语义冲突」。本批 T1 用 `by=="user"` 收窄到手工路径、foreman 路径零改动
不双写，但**通用「共享 handler 跨 producer 证据去重/冲突」检测规则仍缺**。
- issue_id: DG-23
- detection_type: shared-handler-cross-producer-evidence-duplication（共享 handler 与上游 producer 同实体事件去重/冲突 rule）
- description: validate 无法检测共享 handler 重复/矛盾发出上游已写的同实体证据事件导致的 ledger 双写/污染

#### DG-24（validate 无法检测「配置/registry 路径以 cwd 相对解析，而运行该代码的进程 cwd≠该资源所属 group 工程根 → 主路径读错文件」）

v65 M2-B step-3 Codex review（F3 blocker）发现：原计划按相对 `.cccc/models/registry.yaml` 加载
registry，但 daemon 以 `CCCC_HOME` 为 cwd 启动（`daemon_main.py:35` / `common.py:494` 显式
`cwd=paths.home`），并非 group 工程根。结果：用临时 worktree fixture 测 `handle_actor_add` 能过，
真实 daemon 主路径却读 `CCCC_HOME/.cccc/...` 或空表。`ralph validate` 无 rule 检测「某 daemon 侧代码
按 cwd 相对路径加载 group-scoped 资源（registry/config），而该 daemon 进程 cwd 与 group active scope
根不一致 → 主路径读错/读空」。属 DG-3「测试绿生产失效」家族在**路径解析维度**的延伸。本批 T1 改用
group active scope 根解析，但**通用「daemon cwd-相对路径解析正确性」检测规则仍缺**。
- issue_id: DG-24
- detection_type: daemon-cwd-relative-path-resolution（daemon 侧 group-scoped 资源按 cwd 相对解析的正确性 rule）
- description: validate 无法检测 daemon 代码以 cwd 相对解析 group 资源、而 daemon cwd≠group 工程根导致主路径读错文件

#### DG-25（validate 无法检测「matcher/selector 新增的词表/语义键在生产调用方输入枚举无法产出时 → 主路径不可达的休眠词表」）—— 即命名空间统一 deferred 项 MSE-NS

v65 M2-B step-3 Codex review（F5 major）确认：给 `model_selection` 加 `security_review`/`code_change`/
`general_execution` 等 task_type↔strengths 别名，但生产 selector 调用点（`agent_pool.py:699-700`、
`af_gateway_bridge.py:463-465`）拿到的仍是 `TaskRef.type = Literal["frontend","backend","general"]`，
**根本产不出这些新键**。于是直调单测 `select_model_for_task("security_review")` 能绿，正常 workflow
主路径却永不发出这些语义键——纯假闭合。`ralph validate` 无 rule 检测「某 matcher/selector 新增的输入
词表/语义键，是否在生产调用链上被某真实输入源（contract 枚举 / 上游定型产物）可达地产出」——属 DG-1
dormant-path 在**值/枚举可达性**维度的延伸（DG-1 查模块/函数可达，此处查「输入取值是否可达」）。
**命名空间统一（M2-B 表）整体因此 DEFERRED 记为 MSE-NS**：真修需扩 `TaskRef.type` 契约 + 上游
ralph/foreman 任务定型真正产出这些类型（含「如何判定 security_review task」的设计决策），属多层契约
变更专项；当前主路径三类可达 type 经既有子串匹配均能命中、无 live 匹配失败，故本批不以别名表伪闭合。
- issue_id: DG-25
- detection_type: selector-vocabulary-reachability（matcher/selector 新增词表是否被生产输入源可达产出 rule）
- description: validate 无法检测 selector 新增 task_type/strength 词表在生产调用方输入枚举无法产出时主路径不可达（休眠词表/假闭合）

#### MSE-NS（命名空间统一 —— ✅ 已 behavior-verified v71，待迁 full 归档）

> **v71 已闭合**：扩 TaskRef.type/TaskSpec.type 枚举纳入 security_review + `task_typing.infer_task_type` 上游定型
> （词表可达非休眠）+ peer-reuse security_review-aware（采纳 step-3 F4），new-agent 与 peer-reuse 两条路由均收敛
> claude。证据见上「v71 本批已 behavior-verified」。下方原 deferred 说明保留作历史。

M2-B「命名空间统一」（task type 与 strengths 关键词统一：backend/general_execution/code_change/
security_review）经 v65 step-3 F5 证实**不能以 model_selection 别名表在本批闭合**（详见 DG-25）。
真修路径：(a) 扩展 `TaskRef.type`/`TaskSpec.type` 契约纳入统一词表；(b) 上游 ralph/foreman 任务定型
真正产出这些类型（含 security_review/code_change 的判定逻辑）；(c) selector 侧别名桥才有可达输入。
属多层契约变更 + 设计决策，超出单 solve 批安全范围 → 独立专项。优先级 P2（当前无 live 匹配失败）。

#### DG-26（validate 无法检测「审计/证据字段由反查或推断填充、而非取自真实决策来源 → 伪造证据」）

v65 M2-B step-3 Codex review（F6 major）发现：原计划在 actor 路径写 `chosen_model_key`，但 Actor 合同
（`contracts/v1/actor.py`）只存 `runtime` 不存 `model_key`；计划「按 chosen_runtime 反查第一个 enabled
model_key」会在同 runtime 多 enabled model 时伪造证据——ledger 看似记录了「选中的模型」，实则只是拿
runtime 猜了一个 key。`ralph validate` 无 rule 检测「某审计/证据字段（如 chosen_model_key）是否取自
真实决策来源（selector 实际返回），还是由反查/推断回填（无对应合同字段支撑）」。属 DG-7「字段判定停留
substring 未做 field→value 解析」家族在**证据来源真实性**维度的延伸。本批 T1 改为只写 selector 真实选出
的 key（无则置空），但**通用「证据字段来源真实性」检测规则仍缺**。
- issue_id: DG-26
- detection_type: inferred-evidence-fabrication（审计字段来源须为真实决策来源而非反查/推断 rule）
- description: validate 无法检测审计/证据字段由反查或推断回填（无合同字段支撑）导致的伪造证据

> DG-22~DG-26 + MSE-NS 均由 v65 M2-B step-3 Codex review（verdict=incomplete）发现、`ralph validate`
> 对原计划 compact PASSED → 又一批「validate 无法检测主链路假闭合」实例，纳入 DG 规则族 detection-capability
> 缺口；本批 T1 仅在「手工 actor add 读端闭合」具体实例上修复，通用检测规则与命名空间统一专项待后续。

<!-- v66 批次（DG-20 + DG-19 + DG-15）step-3 Codex 设计评审（verdict=incomplete，6 finding：1 blocker + 5 major，
     全部采纳，见 plan.yaml finding_refs）暴露的**新** `ralph validate` detection-capability 缺口：DG-27~DG-29。
     这些是评审在「检测规则自身能否成立/能否被绕过」层面抓出的元缺口（validate 检测 validate 规则的健康度），
     与既有「validate 检测主链路假完成」正交。 -->

#### DG-27（validate 无法检测「内容级/需读源文件的规则在 project_root 缺失时静默 no-op → 依调用路径而休眠的规则」）

v66 DG-20 step-3 Codex review（F1 blocker）暴露：现存大量需读文件内容的规则（`_check_active_path_reachability`/
`_check_observable_fallback`/`_check_guard_ordering`/`_check_integration_call_evidence`/`_check_status_code_implementation_drift`
等）形如 `if project_root is None: return issues` —— 一旦从**不传 project_root 的调用路径**进入即**静默返回空**，
规则形同未运行（休眠），且无任何告警/痕迹。本批 DG-20 value-drift 子检查正因同一约束被迫改用 cccc 包位置自解析
（绕开 project_root 依赖）。`ralph validate` 无 rule 检测「某规则依赖的运行时上下文（project_root 等）在其某条
实际调用路径上缺失，导致该规则在该路径上静默 no-op」——这是 DG-6 gate/consume-without-producer 的镜像
（规则需要某输入，但调用方没提供，于是规则自己变休眠）。**修复方向**：规则注册元数据声明所需上下文 +
validator 在缺上下文时对依赖它的规则发 `rule skipped: missing project_root` 痕迹（而非静默 []），或统一保证主
调用路径恒传 project_root。本批不修，记 detection-capability 缺口。
- issue_id: DG-27
- detection_type: rule-dormant-on-missing-context（规则因运行时上下文缺失而静默 no-op 的可达性 rule）
- description: validate 无法检测内容级规则在 project_root 缺失的调用路径上静默返回空、形同休眠，无告警痕迹

#### DG-28（validate/flow 无法检测「任务自称『正向触发某 code』作为行为证据，但该 code 已被本 plan 的 suppress_codes 降级 / 验收命令并不断言该 code → 自我抵消的假证据」）

v66 step-3 Codex review（F3，cross）暴露：原计划把「跑 `ralph validate plan.yaml`」当成「新规则会报某 code」的
正向行为证据，但本 plan 的 `suppress_codes` 恰恰把这些新 code 降成 hint，且 CLI 命令本身不断言 code 是否出现——
即「正向证据」在本 plan 内被自己 suppress 掉、且命令不校验，构成自我抵消的假证据。`ralph validate` / flow step-5
无 rule 检测「某 task 的 verification 声称触发/依赖某 issue code 作为行为证据，但同一 plan 的 suppress_codes 含该
code（证据被自降级）或验收命令未对该 code 做断言（证据未被校验）」。属 M1-5「行为证据存在性≠相关性」(DG-18) 在
**证据有效性/未被自我抵消**维度的延伸。**修复方向**：flow/validate 校验「正向 code 触发类证据须跑在不 suppress
该 code 的临时 plan/fixture 上并显式断言精确 code」。本批已据此把所有正向触发改到无 suppress fixture（plan-level
`ralph validate` 仅留接线/valid 回归），但**通用检测规则仍缺**。
- issue_id: DG-28
- detection_type: self-suppressed-positive-evidence（正向 code 证据被本 plan suppress/未断言的有效性 rule）
- description: validate/flow 无法检测「以触发某 code 为正向行为证据，但该 code 被本 plan suppress 或验收命令不断言」的自我抵消假证据

#### DG-29（validate 无法检测「一致性/parity 规则的两个被比对操作数派生自同一来源（共享常量/同一 helper）→ 恒等 tautology / 永不触发的休眠规则」）

v66 DG-15 step-3 Codex review（F4 major）暴露：原 DG-15 writer↔checker 章节集合 parity 若 writer 集合与 checker
集合都 `return REQUIRED_SECTIONS + RETRO_DIMENSIONS`（同源常量），则两集合恒等、规则永不触发——是 DG-1/DG-6
dormancy 在**「规则自身比较两个同源值」**维度的新变体（不是 gate 无 producer，而是 parity 的两端是同一个值的两个引用）。
本批据此把 DG-15 重定义为 writer**渲染输出** → checker**解析器** round-trip（两条独立代码路径），使 writer 格式或
parser locator 漂移可被真实捕获。`ralph validate` 无 rule 检测「某 consistency/parity 规则比较的两个操作数是否
来自独立来源——若派生自同一常量/同一 helper 返回值，则该规则是 tautology / 休眠」。**修复方向**：对自指类规则做
来源独立性静态分析（两操作数的数据来源不应是同一符号）。本批仅在 DG-15 具体实例上规避，通用检测仍缺。
- issue_id: DG-29
- detection_type: tautological-parity-rule（parity/一致性规则两操作数来源独立性 rule）
- description: validate 无法检测一致性/parity 规则两端派生自同一来源导致恒等、永不触发的休眠规则

> DG-27/DG-28/DG-29 均由 v66（DG-20+DG-19+DG-15）step-3 Codex review（verdict=incomplete）发现 → 这是 DG 规则族
> 首次出现的「validate 检测 validate 规则自身健康度（休眠/被绕过/tautology）」的**元缺口**类别，纳入 detection-capability
> 缺口待后续专项；本批仅在各自具体实例上规避，通用检测规则待后续。

### DG-20 / DG-19 / DG-15 —— v66 本批已 behavior-verified（solve flow 全 6 步完成）

**behavior 证据（真实 ralph validate CLI + 函数级断言 + 全量回归）**：
- **DG-20**：`ralph validate plan.yaml --no-agent` 在真实仓库对 `src/cccc/daemon/ops/agent_ops.py` 报出
  `W_SEMANTIC_DEFAULT_VALUE_DRIFT`（found_values 含 "claude"，canonical "codex"；suppress→hint，plan 仍 valid），
  其余 4 个定义点不报 → 检测器对**真实漂移** live 生效。规则按 project_root 解析（仅校验被验证工程自身的
  定义文件），外部/临时工程不误报。
- **DG-19**：`_is_main_path_command("bash -lc 'ralph flow next'")=True`、`("( ralph validate x )")=True`、
  `("bash -lc 'grep ... .log'")` 识别为日志断言；关键不漏报 `("bash -lc 'python -m pytest tests/ralph/x'")=False`。
  复杂 shell 安全降级。
- **DG-15**：doc_parity round-trip 规则接入 validator._collect_structural_issues（CLI 活跃路径，2 处引用），
  真实仓库 round-trip 一致→不报（regression-lock），合成漂移对正反翻转。
- **回归**：全量 `pytest` 3851 passed / 120 skipped / 0 failed；step-5 并行度门 satisfied E=3,D=6（FL-73 强制门
  对本批 3 个独立 task 真实生效）。step-3 Codex 评审 verdict=incomplete 6 finding（F1 blocker + 5 major）全采纳
  （F2 root-cause 因 Agent 合同默认强耦合改 partially-accepted+deferred→FL-74，见 plan.yaml finding_refs）。
  step-5 全量门连带抓出并修复 4 个跨文件回归（agent_ops round-trip 耦合 + validator size + DG-20 包锚定污染）。

落地的三条第一道防线规则（step-3 Codex 评审 6 finding 全采纳，见 plan.yaml finding_refs）：
- **DG-20**：semantic_defaults 增内容级默认值比对（AST 白名单语境，cccc 包位置自解析定义文件）。
  原拟连带修复 `agent_ops.py:119/146` 默认 `'claude'→'codex'`（F2(b)），但 step-5 全量门实证该默认与
  **Agent 合同默认强耦合**（见下方 **FL-74**）→ root-cause **DEFERRED**，本批改由 DG-20 检测器对 agent_ops
  真实漂移发 `W_SEMANTIC_DEFAULT_VALUE_DRIFT`（live 证据，非 suppress-and-forget）。
- **DG-19**：主路径命令解析剥离简单 `bash/sh -c` 与子 shell，复杂 shell 安全降级（采纳 F5）；不漏报 `python -m pytest` 路径。
- **DG-15**：重定义为 writer 渲染→checker 解析器 round-trip parity（采纳 F4，规避 DG-29 tautology）。
step-5 behavior-verify 后归档至 full、并保留 DG-27/28/29 + FL-74 为新开放项。

#### FL-74（executor_runtime 默认 'codex' 与 Agent 合同默认 'claude' 不一致 —— ✅ 已 behavior-verified v71，待迁 full 归档）

> **v71 已闭合**：合同默认 + load/save 兜底统一 codex（round-trip 自洽），真实仓库 DG-20 value-drift 消失。
> 证据见上「v71 本批已 behavior-verified」。下方原 deferred 说明保留作历史。

v66 DG-20 step-5 全量门实证：将 `agent_ops.py:119/146` 的 runtime 默认 `'claude'→'codex'` 会破坏
`test_create_or_reuse_populates_model_info` / `test_acquire_auto_mode_returns_valid_lease` /
`test_process_batch_suggestion_records_selector_bypass`。根因：`Agent.model_runtime` 合同默认是 `"claude"`
（`contracts/v1/agent.py:116`），而 `_save_agent_yaml` 用 `model_dump(exclude_defaults=True)`——当 agent 的
model_runtime 等于合同默认时被**省略**，再由 `_load/_save` 的 `get/pop(..., DEFAULT)` 兜底值写回；故这两处兜底
值**必须等于合同默认**才能 round-trip。要让 executor 默认真正统一为 canonical `codex`，须**协调**改：
(a) `Agent.model_runtime` 合同默认 `'claude'→'codex'`；(b) agent_ops.py:119/146 兜底；(c) 受影响的
auto-acquire / reuse / selector-bypass 测试期望；(d) 复核 amp/gemini 等非 codex runtime 的显式路径不受影响。
属多点 semantic-default 变更（正是 DG-2 家族实例），blast radius 跨 contract/daemon/foreman/tests，超出 DG
检测批安全范围 → 独立专项。本批不改 agent_ops 运行时默认值，仅由 DG-20 检测器 live 暴露此漂移。
- issue_id: FL-74
- detection_type: n/a（这是被 DG-20 检测出的真实 semantic-default 漂移**实例**，非检测能力缺口）
- description: executor_runtime canonical 'codex' 与 Agent 合同默认 'claude' 不一致；统一需合同级协调多点变更（含 round-trip 耦合与受影响测试），DG-20 已 live 检测，修复 deferred 为专项
- priority: P2（当前由合同默认 'claude' round-trip 自洽，无运行时 brick；属一致性/可维护性债）

### M1-5（verification 行为证据门）—— 已 behavior-verified，迁入 full 归档

plan-validate 层「主路径行为命令门」`_check_verification_main_path_command` /
`W_VERIFICATION_NO_MAIN_PATH_COMMAND` 已 behavior-verified，迁入
[full 归档（2026-06-07 v63 M1-5）](./问题清单-v5-ralph-full.md#代码修复归档2026-06-07-v63-第二阶段里程碑m1-5-verification-主路径行为命令门behavior-verified)。
运行时行为 task（role=integration / level=e2e / 覆盖 critical_flow，复用 `_task_covers_flow`）的
verification 若只挂 pytest、无主路径命令（`cccc`/`ralph` CLI 或 `.log` grep），真实 `ralph validate`
即告警；候选命令与真实执行语义一致（checks 非空只认 required check）、程序名经 `_unwrap_command`
归一化判定（不被 `python -m pytest tests/ralph/...` 路径里的 "ralph" 蒙混）。13 验收用例 + CLI 双向
翻转 + 全量 3788 passed。step-3 Codex 评审 verdict=adjust、5 finding 全裁决（F1/F2/F4/F5 ACCEPTED
落地，F3 PARTIAL）。
**仍开放（移交 DG-18/DG-19）**：主路径命令与被覆盖 flow/entrypoint 的因果关联校验（DG-18，
critical-flow 命中升 error 亦 DEFERRED 待误报率验证）、launcher/wrapper/subshell 命令解析残余（DG-19）。

### M1-6（review adoption check）—— 已 behavior-verified（v64）

**v64 落地**：扩展 `FindingRef`（models.py）加 `status` / `status_reason`；新增 discipline rule
`_check_finding_adoption` / `W_REVIEW_FINDING_NO_ADOPTION`，登记进 `_DISCIPLINE_RULES`
（经 collect_discipline_issues→get_all_rules→`ralph validate` 活跃执行）。finding_ref 缺采纳状态
（status 不在 accepted/rejected/deferred）或缺原因（status 合法但 status_reason 空）→ 告警，
validate_with_project 在合成 fixture 上翻转（缺状态/缺原因/非法状态告警，三态正向不报，无 finding_refs
兼容），95 passed；step-3 Codex F7 采纳（全仓正向 finding_ref fixture 同步补合规 status+reason）；
全量 3816 passed。本批 plan 自身的 8 条 step-3 finding 即以本机制（accepted/deferred + 原因）逐条裁决
（见 plan.yaml 采纳记录），属自指验证。severity=warning，可 suppress（第一道防线）。

### FL-73（并行度规则只是 advisory，跨对话必然被忽略 → 需升级为 step-5 强制门 + 留痕）—— 已 behavior-verified（v64，含 dogfood）

> 原列于第三阶段 M5-1，按优先级上移到第二阶段（属「M1 规则补齐 / flow 关口强制化」，且每个新对话都复发）。

**症状（本对话实测）**：solve flow step-5 的并行要求（`flow_engine.py:887`「Launch multiple
tasks with run_in_background for parallel execution」）与 foreman 指南
（`docs/foreman-capability-guide.md:739` estimated_parallelism「create at least that many
workers… if fewer, record explicitly」）目前**都只是 advisory 文本/warning，无任何机器强制**。
后果是跨对话稳定退化：

| 模型/时期 | 多任务批 fanout 峰值 | 行为 |
|-----------|-------------------|------|
| opus-4-6（5/31） | 7（b43e6f25：一次发 7 个独立任务） | 一任务一 codex 真 fan-out |
| opus-4-8（6/6 起） | ≤3，且多任务批 c49a0fb5(7 任务) 实测 **fanout=1** | 把改不同文件、无依赖的任务合并串行 |

c49a0fb5 是关键反例：plan 有 7 个任务，step-5 却把「改 agent_*.py」与「改
flow_improvement_check.py」两组**互不接触文件**的修复**串行**派发（16:38→16:44），既未并行、
也未按指南留痕说明为何少开。这证明 advisory 规则在实际执行中被直接忽略。

**根因**：并行度无 fail-closed 门。flow 无能力检测「plan 含 ≥2 个独立任务（无 depends_on 且
claimed_paths 互不相交）但 step-5 执行未并行 fan-out」，也不强制 foreman 记录
estimated_parallelism 与实际并行数的差异。**"AI 这次知道了≠下次会做"——靠模型记忆不可持续，
必须落到机制**（与本清单贯穿的「不让 AI 不犯错，而用机制逼证据」同源；也是「warning 不能只作
警告，否则被忽略」这一元教训的具体实例）。

**要求（升级为强制门，非 advisory）**：
1. `ralph suggest`/`validate` 计算并暴露 `estimated_parallelism` = 独立任务宽度
   （无 depends_on + claimed_paths 两两不相交的任务数 / DAG frontier 宽度）。
2. solve flow step-5 gate：若 `estimated_parallelism ≥ 2`，**必须**有证据表明 step-5 实际并发
   派发了 ≥N 个后台任务（或在 plan/flow 留痕显式记录少开并行的约束理由），否则 step-5 fail-closed，
   不得仅凭 pytest 退出码 0 通过。
3. 实际并行度可观测：以「重叠的后台 codex/worker 派发数」或 group 派发 ledger 为证据，与
   estimated_parallelism 对比；差异无留痕即判失败。
4. （E2E/foreman 侧镜像）assignment 路径按 estimated_parallelism 开 worker，少开必须写
   constraint 留痕事件，使「慢完成」不被误读为依赖瓶颈、也不被掩盖为「就该串行」。

- issue_id: FL-73
- detection_type: parallelism-enforcement-gate（独立任务宽度 → step-5 实际并行度 fail-closed 校验 + 留痕）
- description: 并行度规则仅 advisory，flow 无法检测/强制「plan 有独立任务但 step-5 未并行」，跨对话稳定退化为串行；需升级为强制门并要求 estimated vs actual 并行度留痕
- priority: P1（系统性降低吞吐，且每个新对话都会复发）

**v64 落地（已 behavior-verified，含 dogfood 闭环）**：
- `core.compute_estimated_parallelism(tasks)` —— 独立宽度 = 候选任务集中 claimed_paths 两两不相交的
  最大数（复用 cccc.kernel.claimed_paths；采纳 Codex F3，入参为候选集而非裸 plan）。
- `ralph_service` 的 `estimated_parallelism` 由 `len(ready)` 改为真实独立宽度；并修正下游会还原回
  `len(...)` 的两处 reset（assignment_deferrals / workflow_orchestrator，采纳 Codex F4，端到端语义一致）。
- `cli.py` `_cmd_suggest` 的 text/json 输出暴露 estimated_parallelism（对 ready 候选集计算）。
- `flow_engine._check_execute_and_verify` step-5 强制门：E=plan frontier 独立宽度，D=`.ralph-flow/
  step-5-execute/` 下按文件名 stem 去重的有效 codex json（success=true）数；E≥2 且 D<min(E,2) 且无
  sidecar 留痕 → **fail-closed**（采纳 Codex F1，并行度结果真正合取进 CheckResult.passed，非仅 advisory
  detail）；留痕豁免改用 sidecar 文件 `.ralph-flow/step-5-execute/parallelism_constraint.txt`（采纳
  Codex F2，避免 Plan 严格 schema 拒未知字段；plan 缺失/解析失败 → fail-closed，不再有「不确定即放行」绕过）。
- **dogfood**：本批 plan 刻意设 T1/T2/T3 claimed_paths 两两不相交（独立宽度=3），step-5 实际 fan-out
  并发派发，本流程自身 step-5 gate 实测 `parallelism gate: satisfied E=3, D=5` 通过——新机制对自己生效。
- 69 passed（纯函数多拓扑 + ralph_service 端到端 + CLI 暴露 + step-5 gate 正反翻转/D 计数稳健/缺 plan
  fail-closed），既有 flow_engine/flow_e2e 测试不回归；全量 3816 passed。
- **仍开放（移交 DG-21）**：D 按文件名 stem 计数、codex json 无 task_id → 可被重复/畸形文件伪造或误计；
  需 task_id↔plan-task 强匹配（第一道防线，warning 级证据）。

---

### M2-B（模型选择：从"Guide 建议"改为"流程消费"）

不通过 system prompt 强化"请用 codex"。应让模型选择流程本身成为 actor 创建路径的数据来源。

> **部分归档（2026-06-06，v60 FC 批次 Phase 1）**：下表「数据修正：codex 覆盖执行类 task type」与「enabled 过滤」两子点已 behavior-verified（FC-1/FC-2 + 复用路径 F1），证据束见 [full 归档](./问题清单-v5-ralph-full.md#代码修复归档2026-06-06-v60-fc-批次-phase-1fc-1--fc-2behavior-verified)。
> **续部分归档（2026-06-07，v62 T4）**：「override 留痕」（显式 runtime 不一致写 `model.selector_bypass` ledger 事件）与「读端留痕」（显式 + pool 两条 `process_batch_suggestion` 主路径均写 `model.selection_decision` 事件）已 behavior-verified（双独立验证，pool-path 缺失首轮发现已修 CLOSED），证据束见 [full 归档（v62）](./问题清单-v5-ralph-full.md#代码修复归档2026-06-07-v62-第二阶段批量dg-3--dg-4--m2-cux-23--m2-bbehavior-verified)。
> **M2-B 整体仍开放**：读端「actor add CLI 默认路径调用选择函数」、rating 变化驱动 suggest 的闭环、命名空间统一、E2E worker runtime 分布验证 未完成。
> **v65 进行中（本批 solve）**：「读端闭合」收窄到**手工 `cccc actor add`（by=user）默认路径**——
> step-3 Codex 评审（6 finding/3 blocker）证实 foreman 路径读端已闭合（上游 resolve_model_for_task +
> assignment_batches 写 task 级 decision），未闭合的是手工路径。本批 T1 让手工默认路径以
> select_model_for_task **驱动** runtime 并写 `model.selection_decision`（选型前置驱动，非事后记账；
> scope-resolved registry；可观测兜底；foreman 路径零改动不双写）。**rating 消费经评审独立确认早已实现**
> （`agent_ops.select_model_for_task` 把 foreman_rating 作 tiebreak、`test_select_model_rating_consumed`
> 已锁），本批不重做仅复核。**命名空间统一 DEFERRED → MSE-NS**（step-3 F5：语义键在 TaskRef.type Literal
> 下主路径不可达，真修需上游定型契约专项，见 DG-25/MSE-NS）。**E2E worker runtime 分布**以选型层代理
> （默认执行→codex）覆盖，完整活体分布留待 e2e flow。step-5/归档后回填 behavior-verified 证据束。

| 项目 | 改法 | 验收 |
|------|------|------|
| 读端闭合 | `actor add` 默认路径先调用 `model suggest` 或同等选择函数 | actor 创建日志包含 model_selection_decision |
| 数据修正 | codex 覆盖 backend/general/code_execution 等执行类 task type；claude 收窄到 review/frontend/aesthetic | `cccc model suggest backend` 返回 codex |
| 命名空间统一 | task type 与 strengths 关键词统一：backend、general_execution、code_change、security_review | 无命名空间不通导致的匹配失败 |
| enabled 过滤 | disabled model 不参与候选 | 测试覆盖 enabled=false |
| rating 消费 | `select_model_for_task` 必须读取 foreman_rating | rating 变化影响 suggest 结果 |
| override 留痕 | 显式 `--runtime claude` 不硬拦，但必须记录 override reason 和 selector-bypass event | 复盘可审计 |
| E2E 验证 | 跑实际 workflow，看 worker runtime 分布 | 默认执行 worker 应主要为 codex |

### M2-C（WORKFLOW_EVALUATION / 复盘：空章节阻断 workflow.completed）—— 核心阻断已 behavior-verified，迁入 full 归档

空/不实质 EVALUATION 阻断 `workflow.completed` 已 behavior-verified，迁入
[full 归档（2026-06-07 v62）](./问题清单-v5-ralph-full.md#代码修复归档2026-06-07-v62-第二阶段批量dg-3--dg-4--m2-cux-23--m2-bbehavior-verified)：
`_check_section_substantive(content, *, min_chars=40)` + 八维维度（writer 生成 `## 维度` 子标题 + parser 精确整行匹配，
修复改名前缀绕过）；complete_workflow 在 emit_workflow_terminal 之前阻断（守卫顺序满足 DG-4），空/占位/<40 字/八维缺失/
改名标题 → pending + `workflow.evaluation_incomplete`，不 emit completed（真实 complete_workflow 双独立验证）。
**仍开放**：下表「rating 真执行（registry 时间戳/usage 记录）」「复盘影响下一轮 suggest」两子项（属 M2-B rating 闭环），
以及 step-7 E2E flow 的 review-adoption 检查（M5-2），本批未覆盖。

### UX-23（WORKFLOW_EVALUATION 定性章节持续为空）—— 已 behavior-verified，迁入 full 归档

由 M2-C 的 min_chars=40 实质化 + 八维 writer/parser 一致 + 精确标题行匹配（改名绕过 CLOSED）覆盖，已 behavior-verified，
迁入 [full 归档（2026-06-07 v62）](./问题清单-v5-ralph-full.md#代码修复归档2026-06-07-v62-第二阶段批量dg-3--dg-4--m2-cux-23--m2-bbehavior-verified)。

---

## 第三阶段：M4 回归场景 + M5 Flow 关口升级

<!-- v67 批次（第三阶段开篇：M4-1 harness + M5-1 solve step-1/2 门 + M5-2 e2e step-7 八维门）
     step-3 Codex 设计评审（verdict=incomplete）暴露的**新** detection-capability 缺口：DG-30/DG-31。
     本批落地 M4-1/M5-1/M5-2 各自第一可落地子集（见 plan.yaml finding_refs 三态裁决），step-5/step-6
     behavior-verify 后回填证据束。M4-1 反 tautology 重设计（scenario.command=真实主路径命令而非被测规则
     单测）已采纳 F-T1-a。 -->

#### DG-30（validate/flow 无法检测「flow step 产出门用 keyword-presence 判定、且 producer instruction 与 checker 词表同源 → 填词即可过闸的弱门」）

v67 M5-1/M5-2 step-3 Codex review（F-kw-gameable，minor）确认：本批 M5-1 step-1 understand 三概念门
（症状/活跃路径假设/行为变化）与 M5-2 step-7 retrospective 八维门均以**关键词出现**（同义词 presence）
判定产出实质性，且 checker 词表与 flow 给 producer 的 instruction_text 近同源——填入相应关键词即可过闸，
不保证产出真有实质内容。这是 RV-51（文本关键词可被同义/填词绕过）与 DG-29（parity 两端同源 tautology）
家族在 **flow step 产出门**维度的延伸。`ralph validate` / flow 无 rule 检测「某 step 完整性门是否仅靠
keyword presence、其判定词表是否与 producer 提示同源（自证）、是否要求每概念/每维引用独立可核验 evidence」。
**修复方向**：把 step 产出门从 keyword presence 升级为结构化 section/字段解析 + 每维要求引用独立 evidence
（如每维须引 ledger 事件 / artifact 路径 / 具体 task_id），并对自指类门做来源独立性分析。本批仅落地
keyword-presence 第一道弱门，通用结构化产出门 + 词表来源独立性检测仍缺。
- issue_id: DG-30
- detection_type: flow-step-output-gate-keyword-gameability（flow step 产出门 keyword-presence/词表同源/缺独立 evidence 的健康度 rule）
- description: validate/flow 无法检测 flow step 完整性门仅靠 keyword presence、判定词表与 producer 提示同源、不要求独立 evidence 导致填词过闸的弱门

#### DG-31（validate 无法检测「回归场景 harness 的 scenario.command 是否为真实主路径命令，还是退化为被测代码自身的单测 → tautology 回归」）

v67 M4-1 step-3 Codex review（F-T1-a，major）发现：原 plan 把 RS-V62-1~4 每个回归场景的 `command`
降级为各自 `regression_lock` 的 pytest 命令，使「真实假完成症状是否在主路径消失」退化为「该检测规则自身的
单测是否还绿」的**自证循环（tautology）**——回归集看似覆盖、实则只在重跑被测代码的单测。`ralph validate` /
flow 无 rule 检测「某回归场景集的 scenario.command 是否为真实主路径命令（CLI / orchestrator driver），
还是与被测 detection rule 的单测同一文件（command==regression_lock 且指向被测规则自身测试）」。属 DG-28
「以触发某 code 为正向证据但被自我抵消」家族在 **回归场景命令真实性**维度的延伸。本批据评审重设计为
cli-validate（`ralph validate <fixture>` + issue-code 断言）/ orchestrator-driver（直接驱动生产
WorkflowOrchestrator）两类真实主路径 command，regression_lock 降为辅证；但**通用「场景命令真实性 /
command≠被测规则自测」检测规则仍缺**。
- issue_id: DG-31
- detection_type: regression-scenario-command-authenticity（回归场景 command 是否真实主路径 vs 被测规则自测 tautology rule）
- description: validate 无法检测回归场景 harness 的 scenario.command 退化为被测检测规则自身单测（command==regression_lock），使回归集成为自证循环

> DG-30/DG-31 均由 v67 step-3 Codex review（verdict=incomplete）发现、本批落地各自第一道防线（keyword
> presence 产出门 / 真实主路径 command 重设计）后仍放行 → 纳入 DG 规则族 detection-capability 缺口；
> 通用结构化产出门 + 场景命令真实性检测规则待后续专项。

<!-- v68 批次（第三阶段收尾：M4-1 10 场景 + M5-1 adoption/advisory + M5-2 section/orphan/global）
     step-3 Codex 设计评审（verdict=incomplete，6 finding 全采纳，见 plan.yaml finding_refs）暴露的
     detection-capability 缺口：DG-32（section 解析器与 canonical checker 漂移）、DG-33（task 粒度无门检测）。 -->

#### DG-32（validate/flow 无法检测「e2e flow 的 section 实质化 parser 与 daemon 侧 canonical checker（workflow_evaluation_empty_sections）漂移 → 双标准判定」）

v68 M5-2 step-3 Codex review（T3-EVALUATION-CANONICAL-DRIFT，high）发现：本批在 `flow_steps_e2e.py`
的 `_check_workflow_evaluation` 中新增的 `_evaluation_section_substantive_details` 按 5 个
REQUIRED_WORKFLOW_EVALUATION_KEYWORDS 关键词切 section + ≥40 chars 判定，但 daemon 主路径
（`workflow_evaluation_io.py` → `workflow_evaluation_empty_sections` → `_check_section_substantive`）
已有 13 个精确 heading + min_chars=40 的 canonical checker。两套 parser 对同一文档的标题集合、
切割逻辑、实质化阈值可能漂移（flow gate 判 pass 但 daemon 判 block，或反之）。`ralph validate` /
flow 无 rule 检测「同一文档的两个 parser/checker 实现（e2e flow vs daemon）标题集合与判定逻辑
是否一致」。属 DG-15 writer↔checker parity 家族在 **flow-gate↔daemon-gate 双实现**维度的延伸。
本批选择独立实现（避免 flow→daemon 循环依赖），但 **canonical 统一 deferred**。
- issue_id: DG-32
- detection_type: flow-gate-daemon-gate-parity（e2e flow 与 daemon 同文档检测逻辑一致性 rule）
- description: validate/flow 无法检测 e2e flow step-4 的 section 实质化 parser 与 daemon 侧 canonical workflow_evaluation checker 标题集合/判定逻辑漂移导致的双标准

> DG-32 由 v68 step-3 Codex review（T3-EVALUATION-CANONICAL-DRIFT）发现 → 纳入 DG 规则族；
> 本批选择独立 section parser 避免循环依赖，canonical 统一待后续。

#### DG-33（validate/flow 无法检测「plan 把大量独立工作压缩到少数 task → estimated_parallelism 人为降低 → 并行度门被绕过」）

v68 实测暴露：本批把第三阶段全部剩余工作（M4-1 六场景 + flow hookup、M5-1 四 step 改进、M5-2
四 step + 全局断言）压缩进 T1/T2/T3 三个 task（按文件归属而非行为变化拆分），导致
`estimated_parallelism=3`、并行度门 `D>=min(3,2)=2` 轻松通过。但真实独立行为变化 ≥8 个（每个
新场景、每个 step gate 升级都是独立可验证单元），合理 task 粒度应产出 E≥6。`ralph validate` /
flow 无 rule 检测「plan task 数量 / 粒度是否与 required_issues 覆盖范围、goal_behavior 复杂度、
claimed_paths 修改点数量匹配——即 task 是否被过度压缩」。属 FL-73 并行度门的**上游盲点**：
FL-73 检测"E 个独立任务是否并行派发"，此处是"E 本身是否被 plan 设计人为降低"。
- issue_id: DG-33
- detection_type: task-granularity-compression（plan task 过度压缩使 estimated_parallelism 人为降低的检测 rule）
- description: validate/flow 无法检测 plan 把大量独立工作压缩到少数 task 导致 estimated_parallelism 人为降低、并行度门被绕过

> DG-33 由 v68 实测（用户指出）暴露 → 纳入 DG 规则族；属 FL-73 并行度门上游盲点，
> 本批不修，待后续 plan 粒度校验规则专项。

### v67 本批已 behavior-verified（第三阶段开篇：M4-1 / M5-1 / M5-2 各第一可落地增量，solve flow 全 6 步完成）

**behavior 证据（真实 CLI/装配 + 全量回归）**：
- **M4-1（T1）**：新增 `src/cccc/ralph/regression_scenarios.py`（RegressionScenario + RS-V62-1~4 REGISTRY +
  subprocess runner + evidence bundle 含 logs/events）+ `ralph regression run/list` CLI 主路径（cli.py
  dispatch 仿 audit/guide）。**反 tautology（采纳 step-3 F-T1-a）**：scenario.command 为真实主路径——RS-V62-1/2
  是 `ralph validate <committed fixture>` + issue-code 断言（RS-V62-1 实报 W_SILENT_FALLBACK+
  W_GUARD_AFTER_SIDE_EFFECT；RS-V62-2 实证目标文件无 W_SILENT_FALLBACK），RS-V62-3/4 是直接驱动生产
  WorkflowOrchestrator 的 driver pytest，**无任一场景以被测规则自身单测充当 command**。真实
  `ralph regression run --format json` → overall_pass=true、exit 0（RS-V62-1 rc=1 但按 codes 断言判 pass，
  符合 cli-validate 设计）；fail-closed 双向（缺码/命令失败 → pass=false、exit 1）经单测翻转。committed
  fixture 于 tests/fixtures/regression/。
- **M5-1（T2）**：`flow_engine.py` 新增 `_check_understand`（要求 .ralph-flow/step-1-understand/ 非空 .md
  且覆盖三概念：原始症状/活跃路径假设/需证明的行为变化），并把 `_build_solve_steps()[0].check_fn` 由 None
  接到 `_check_understand`（step-1 不再恒过）；`_check_plan` 追加 behavior-verification 子判定（batch_e2e_command
  或主路径命令存在才过，纯 pytest-only fail）真正合取进 CheckResult.passed。fixture 正反翻转，
  test_flow_solve_gates.py 7 passed。**dogfood**：本 solve flow 即在新 step-1 门下完成（已写合规 understand.md）。
- **M5-2（T3）**：`flow_steps_e2e.py` 新增 RETRO_DIMENSIONS 八维 + `_check_retrospective` 追加八维覆盖子判定
  （缺任一维 fail-closed），保留既有 agent≥2/rating/runtime/registry 判定不变。fixture 正反翻转 +
  既有门未削弱，test_flow_e2e_gates.py 5 passed。
- **集成脊柱（T4）**：tests/ralph/test_phase3_spine.py 真实 import+调用三处生产符号（run_scenarios /
  _check_understand+_build_solve_steps / _check_retrospective+E2E_STEPS）汇合断言装配可达 + 行为翻转，3 passed。
- **回归**：全量 `pytest` **3874 passed / 120 skipped / 0 failed**。step-5 并行度门 satisfied **E=3, D=5**
  （FL-73 强制门对本批 T1/T2/T3 三个 claimed_paths 两两不相交任务真实生效，真并行 fan-out）。
- **step-5 全量门连带抓出并修复 1 个跨文件回归**（采纳 step-3 F-width-semantic 预警）：T2 新增 step-1 门
  破坏 tests/e2e/test_v46_integration.py::test_hmac_persists_across_step_transitions（它直接 engine.next()
  期望 Step 2/6）——按门真实要求补 step-1-understand 产物修复（非绕过门），tests/e2e 99 passed/20 skipped。
- **step-3 Codex 评审 verdict=incomplete** 5 个真实设计 finding 全裁决（见 plan.yaml finding_refs 三态）：
  F-T1-a/F-T1-b accepted（M4-1 反 tautology + bundle logs/events）、F-T2-detector-reuse partially-accepted、
  F-kw-gameable accepted（→ DG-30）、F-width-semantic accepted（→ 真实回归已修）。评审多数 blocker 实为
  「plan 已写、实现未落」的 step-5 待执行态，已由本批 step-5 落地兑现。

**仍开放（第三阶段未完，本批仅开篇增量）**：
- M4-1：6 个标准场景（AF 默认启用 / AF runtime 缺失 / 模型选择 backend / Foreman override / 空 EVALUATION /
  假集成 fixture）多需活体 daemon/workflow，未写成可执行 bundle；M4-1 是开放集，后续每批新缺陷回灌为 RS-* 场景。
  「每次 solve flow 后自动跑」的编排接线（把 `ralph regression run` 挂进 flow 收尾）尚未落地。
- M5-1：step-3/4/5/6 改进（多已由既有 codex/gap/FL-73/guide 关口覆盖，但未逐条按 M5-1 表升级验收）。
- M5-2：step-4/6/8 + 全局自动断言（AF 是否执行 / 模型选择 / silent fallback）需活体 group 状态，未做。
- DG-30（产出门 keyword 可绕过，需结构化 section/独立 evidence）、DG-31（场景命令真实性检测）待后续专项。
- 第三阶段完整退出标准「6 个假完成回归场景全自动通过；flow 每步都有行为证据」需多批迭代。

### M4-1（建立固定 E2E 回归场景）

不再每轮临时设计 E2E。建立一组"假完成回归场景"，每次 solve flow 后自动跑。

**回归场景集（至少 6 个）**：

| 场景 | 预期 |
|------|------|
| AF 默认启用 | 日志显示 `execution_engine: af`，出现 `[af] execution done`，无 legacy fallback |
| AF runtime 缺失 | fail-closed 或明确 `af.execution_unavailable` event，不允许静默 legacy |
| 模型选择 backend task | `cccc model suggest backend → codex`，actor runtime 主要为 codex |
| Foreman override runtime | 允许但必须有 selector-bypass event 和复盘说明 |
| 空 WORKFLOW_EVALUATION | workflow.completed 被阻断 |
| 假集成 fixture | 新模块存在但主路径不可达时，DG-1 失败 |

**evidence bundle 结构**：

```yaml
scenario_id:
  command:
  expected:
  actual:
  pass:
  logs:
  events:
  regression_lock:
```

归档时引用 bundle，而不是引用自然语言结论。

#### M4-1 候选回归场景（来自 v62 批次独立对抗验证抓到的 4 个「pytest 绿但主路径假完成」缺陷）

> 来源：v62（DG-3/DG-4/M2-C/M2-B）批次。这 4 个缺陷在 flow step-5 全量 pytest（3770 passed）下**全部放行**，
> 仅由事后人肉独立对抗验证（真实 CLI 临时工程 + 直接驱动 orchestrator 读 ledger）抓出 → 正是 M1-5/FL-66/RV-48
> 预言的「组件级 pytest 绿 ≠ 主路径行为对」。已在 v62 修复并各自加单测（regression_lock），但**尚未纳入
> M4-1 自动回归集**——M4-1 自动化落地时应优先固化以下 4 条。证据束：
> .ralph-flow/step-5-execute/adversarial_verify.json、reverify.json。

```yaml
RS-V62-1:  # DG-3/DG-4 claimed-paths 盲区（仅在 claimed_paths、不在 plan_scope 的生产文件被漏扫）
  command: "ralph validate <tmp>/plan.yaml --project-root <tmp> --format json --no-agent  # 目标 src/*.py 仅入某 task 的 claimed_paths，不入 plan_scope"
  expected: "issue codes 含 W_SILENT_FALLBACK（静默 except 文件）与 W_GUARD_AFTER_SIDE_EFFECT（守卫倒序文件）"
  actual_before_fix: "valid:true，无任何告警（规则只扫 plan_scope → 完全失明）"
  actual_after_fix: "两类告警均出现（扫描集 = plan_scope ∪ claimed 生产 .py）"
  pass: "判据=codes 含目标告警；注意 warning 不翻 valid:true（设计本意），不可用 exit≠0 当判据"
  events: "n/a（validate 返回 JSON issue codes）"
  regression_lock: "python -m pytest tests/ralph/test_observable_fallback.py tests/ralph/test_guard_ordering.py -v（claimed-only 用例）"

RS-V62-2:  # DG-3 自违例（新增代码自身的 except 是静默 fallback）
  command: "ralph validate <plan 指向 src/cccc/daemon/foreman/workflow_evaluation_io.py>"
  expected: "workflow_evaluation_io.py 上 W_SILENT_FALLBACK 命中数 = 0（except 分支已 logger.warning，可观测）"
  actual_before_fix: "workflow_evaluation_io.py:104 / :125 各报 1 个 W_SILENT_FALLBACK（自违例）"
  actual_after_fix: "命中数 0"
  pass: "目标文件无 W_SILENT_FALLBACK"
  regression_lock: "真实 CLI 复核 + tests/ralph/test_observable_fallback.py"

RS-V62-3:  # M2-C 改名标题前缀绕过（renamed heading 仍满足完成 gate）
  command: "直接驱动 WorkflowOrchestrator.complete_workflow，WORKFLOW_EVALUATION.md 把 '## runtime 选择' 改成 '## runtime 选择（改名）'"
  expected: "返回 {status:pending, reason:workflow_evaluation_incomplete, empty_sections 含 'runtime 选择'}；ledger workflow.completed=0"
  actual_before_fix: "complete_workflow 直接完成并写 workflow.completed（find('## '+heading) 前缀子串匹配被改名标题冒充）"
  actual_after_fix: "pending + workflow.evaluation_incomplete=1，无 completed（精确整行标题匹配）"
  pass: "改名标题→不完成"
  events: "workflow.evaluation_incomplete=1, workflow.completed=0"
  regression_lock: "python -m pytest tests/test_workflow_evaluation_substantive.py -v（改名用例）"

RS-V62-4:  # M2-B pool-path 留痕缺失（事件只挂显式分配分支，pool 主路径不写）
  command: "直接驱动 WorkflowOrchestrator.process_batch_suggestion（无显式 assignments 的 pool-path suggestion）"
  expected: "ledger 含 model.selection_decision（data: task_id / chosen_runtime / chosen_model_key）"
  actual_before_fix: "pool path 分配成功（如 codex-backend-worker）但 ledger 无 model.selection_decision / selector_bypass"
  actual_after_fix: "pool path 也写 model.selection_decision（chosen_runtime=codex）"
  pass: "pool path 有 model.selection_decision 事件"
  events: "model.selection_decision=1（pool path）"
  regression_lock: "python -m pytest tests/test_model_selection_main_path.py -v（pool-path 用例）"
```

> 这 4 条目前是**候选**（已有 regression_lock 单测兜底，但未接入「每次 solve flow 后自动跑」的 M4-1 编排）。
> M4-1 落地时：(a) 把上述 command 包成不受 plan suppress_codes 控制的固定场景；(b) 用 evidence bundle 而非自然语言结论归档；
> (c) RS-V62-1 须注意「warning 不翻 valid」语义——回归判据是「告警是否出现」，不是 exit code（否则会误判为已拦截，正是 M5-1 Step5 要解决的「pytest 退出码 0 ≠ 行为对」）。
>
> **⚠️ 这 4 条只是部分候选，不是 M4-1 的完整集合，回归场景应持续设计扩充。** RS-V62-* 只是「本批刚好撞上、被独立对抗验证抓出」的 4 个，
> 远不足以覆盖所有假完成形态。M4-1 是**开放集**（至少 6 个，只会越来越多），后续每批 solve/E2E 抓到的新缺陷都应回灌为新 RS-* 场景。
> 可继续设计的方向（非穷举）：
> - 本节上方表格里的 6 个标准场景（AF 默认启用 / AF runtime 缺失 / 模型选择 backend / Foreman override / 空 EVALUATION / 假集成 fixture）尚未全部写成可执行 bundle。
> - 已记录但未覆盖的检测能力缺口：DG-15（writer↔checker 标题 parity）、DG-16（跨函数守卫支配）、DG-17（兜底信号可达性）各应配一个「能复现漏报/误报」的回归场景。
> - 已知局限族（RV-49~RV-61：文本关键词绕过、import 存在性代替调用路径、AF gate bypass 等）中，凡能构造主路径复现的，都应升级为 RS-* 场景而非停留在「已知局限」。
> - 其它假完成模式：FL-67（override 完成任务漏登记 state）、RV-39（状态码漂移 410 vs 404）、RV-54（claim 并发竞争）等——凡 pytest 绿但主路径可证伪的，皆为候选。

### M5-1（Solve Flow 通过条件改造）

| Step | 当前 | 改进 |
|------|------|------|
| Step 1 Understand | 无检查 | 必须产出"原始症状、活跃路径假设、需要证明的行为变化" |
| Step 2 Plan | plan.yaml 存在 + validate 0 error | plan 必须含 behavior verification，不得只含 pytest |
| Step 3 Codex Review | JSON 格式正确 + success=true | review findings 必须被采纳、显式拒绝或登记为 deferred；增加 call-chain/fallback/guard-ordering/default-drift 四类审查维度 |
| Step 4 Gaps | tracker 有新增 | 缺口必须生成 validate rule 或 flow check 任务 |
| Step 5 Execute | pytest 退出码 0 | pytest + 主路径命令 + 日志断言全部通过；**+ 并行度强制门（见 FL-73）** |
| Step 6 Guide | guide 文件存在 | guide 只能记录已由规则/证据证明的内容，不能作为完成依据 |

> Step 5 的「并行度强制门」详见第二阶段 **FL-73**（本来在此节，已按优先级上移到第二阶段）。

### M5-2（E2E Flow 通过条件改造）

| Step | 当前 | 改进 |
|------|------|------|
| Step 4 Review | 关键词存在 + ≥500 字节 | WORKFLOW_EVALUATION 每个章节必须实质化，空章节失败 |
| Step 6 Improvement | 关键词匹配 | verified 项必须引用 evidence bundle |
| Step 7 Retrospective | 关键词 + registry 时间戳 | 检查八维复盘完整性，验证 rating 真写入且被读取 |
| Step 8 Cleanup | group stop 退出码 0 | 额外确认无 orphan actor / repeated dispatch / stale lease |
| 全局 | 无 | 自动断言 AF 是否执行、模型选择是否符合预期、是否有 silent fallback |

---

## 第四阶段：M3 蓝图中间层

> 先从一个 task 类型试点（如 model selection 或 WORKFLOW_EVALUATION），验证闭环后再推广。

<!-- v69 批次（第四阶段开篇：M3-1~M3-4 全量 + DG-33）step-3 Codex 设计评审（plan_design_review.json，
     verdict=adjust，2 blocker + 5 major，7 finding 全采纳，见 plan.yaml finding_refs）暴露的**新**
     detection-capability 缺口：DG-34（声明强制门实为 advisory）、DG-35（新门 verdict 无状态通路接入终态）。
     F4/F5/F6 分别为既有 DG-29/DG-27/DG-28 的实例（不另记）；F3/F7 为一次性计划修正（不记）。 -->

#### DG-34（validate/flow 无法检测「声明为强制阻断门的新机制实际只是 advisory——门 helper 执行/留痕了，但被它治理的副作用（task 完成 / 终态推进）的真实控制流根本不读门结果」）

v69 M3-2 step-3 Codex review（F1 blocker）暴露：计划一边说 module 黑盒验收要"enforced"，一边把
`verify_task_modules` 定义成 `verification_gate` 的 advisory 留痕，而 validator 本身是无副作用结构层
（不能跑 subprocess 黑盒）。结果：真实完成路径 `verification_gate.py` 只要原 verification 通过就完成 task，
module 黑盒 fail 根本不阻断——"声明强制、实为 advisory"的假门。`ralph validate` 无 rule 检测「某声称为
blocking gate 的验收，其判定结果是否真正接入被治理副作用的控制流（gate verdict → 是否完成/推进的输入），
还是只写了 helper/留痕而副作用独立发生」。属 DG-1 write-without-consumer / DG-22 decision-recorded-but-not-consumed
家族在**门强制性（enforcement reality）**维度的延伸——不是"决策没人消费"，而是"门的否决没人执行"。
本批 M3-2 改为 verification_gate blocking + `ralph module verify` CLI 复用同一引擎（subprocess 不进 validator），
但**通用「声明强制门是否真 blocking」检测规则仍缺**。
- issue_id: DG-34
- detection_type: declared-gate-actually-advisory（声明强制门的 verdict 是否真接入被治理副作用控制流 rule）
- description: validate 无法检测声称 blocking 的验收门实际为 advisory（门结果未接入 task 完成/终态推进的控制流），假门放行假完成

#### DG-35（validate/flow 无法检测「新增 gate 的 verdict 缺少进入下游 auto-complete 决策的状态通路，或时序排在被治理副作用之后 → 门算了但拦不住」）

v69 M3-4 step-3 Codex review（F2 blocker）暴露：把 `_run_batch_e2e_if_configured` 由后台改同步**仍不够**——
`assignment_completion` 先 `_check_batch_completion()` 再无条件 `_check_workflow_completion_after_terminal()`，
orchestrator 先 `reporter.on_batch_completed()` 再跑 batch_e2e，`workflow_terminal` 只看 task 是否 terminal。
即"批次 E2E 门的 verdict 没有任何状态字段/返回值进入 on_batch_completed / workflow 终态推进的判定输入，
或时序上副作用（推进）已先于门结果产生"。`ralph validate` 无 rule 检测「某新增 gate 计算出的 pass/blocked
verdict 是否有状态通路（返回值 / 持久化 status 字段）被下游 terminal/complete 决策真正读取，且门判定时序
先于被治理副作用」。属 DG-9 register-before-side-effect / DG-22 家族在**门 verdict→完成决策状态通路**维度的延伸。
本批 T3 让 `_check_batch_completion` 返回 pass|blocked|none + 存 workflow 级 batch_e2e_status、仅 pass/managed
才推进，但**通用「门 verdict 是否被完成路径状态化消费」检测规则仍缺**。
- issue_id: DG-35
- detection_type: gate-verdict-no-state-path-into-completion（门 verdict 是否经状态通路被下游终态决策消费 + 时序 rule）
- description: validate 无法检测新增 gate 的 verdict 缺状态通路接入 auto-complete 决策（或时序在副作用后），门算出 blocked 仍被 auto-complete 绕过

> DG-34/DG-35 均由 v69 M3 step-3 Codex review（verdict=adjust，2 blocker）发现、本批在 M3-2/M3-4 具体实例上
> 修复（blocking gate + 状态通路），通用「声明强制门是否真 blocking / 门 verdict 是否被完成路径状态化消费」
> 检测规则待后续专项 → 纳入 DG 规则族 detection-capability 缺口。F4/F5/F6 为既有 DG-29/27/28 实例。

<!-- v70 批次（A 类标准 bug：RV-54/RV-62/FL-63/FL-70/FL-64/FL-71/FL-72/RV-63/FL-67/RV-39）step-3 Codex
     设计评审（.ralph-flow/step-3-review/，verdict=adjust，1 blocker + 3 major + 1 minor，5 finding 全采纳，
     见 plan.yaml finding_refs）暴露的**新** detection-capability 缺口：DG-36/DG-37/DG-38。F4 的 silent-no-op
     子项为既有 DG-27 实例；F5 的 CLI vs helper 接线测试为既有 DG-31 家族实例（不另记）。 -->

#### DG-36（validate 无法检测「独立性/权限类分类由 task 定义（role/title/mode）推出，而非由持久化的真实执行者身份证据驱动 → 自审冒充独立」）

v70 RV-62 step-3 Codex review（F1 blocker）暴露：`_task_has_independent_review_semantics` 仅看 task **定义**
（verification_mode/role/标题 token）判 `independently_reviewed`，而代码中根本不存在 `tracked['agent_id']` 这类
现成执行者字段（grep 证实）；若按定义判定，worker-1 自己执行的 review task 会被标"独立审查"，且测试只要塞一个
不存在的 actor_id 字段即可 pytest 绿、真实 evaluation 仍误判 → 典型假完成。`ralph validate` 无 rule 检测
「某独立性/权限/authority 类判定是否由真实运行时执行者证据（持久化 agent_id / completing_agent / completer-mismatch
warning）驱动，还是仅凭 task 定义/声明推断」。属 DG-26（审计字段来源真实性）+ authority 家族（RV-55/57）在
**分类决策来源真实性**维度的延伸——不是字段反查，而是"用定义冒充执行者身份"。本批 RV-62 改为从
covers_tasks/depends_on + 持久化执行者证据取证、无证据保守降级，但**通用「分类决策须由运行时身份证据而非定义驱动」
检测规则仍缺**。
- issue_id: DG-36
- detection_type: classification-from-definition-not-executor-evidence（独立性/权限判定来源须为真实执行者证据 rule）
- description: validate 无法检测独立性/权限类分类由 task 定义推断而非真实执行者身份证据驱动，导致自审冒充独立（假完成）

#### DG-37（validate 无法检测「证据/标记扫描器只覆盖 verification.checks[*].command，遗漏语义等价的顶层 verification.command → command-only 主路径静默逃逸」）

v70 FL-63（F2 major）+ FL-64（F4 major）step-3 Codex review 共同暴露：运行时 schema 同时允许顶层
`verification.command` 与 `verification.checks[*].command`，但多个 checker/收集器（`_workflow_evaluation_verification_checks`
随机化启用判定、`_verification_check_commands`/`_untested_forbidden_flow_fields` forbidden_flow 负向断言扫描）
**只汇总 checks、忽略顶层 command**；于是只写 `verification.command: pytest -p randomly ...` 或 command-only 验收的
真实任务会被误判"无证据/未覆盖"，症状仍在而 pytest 绿。`ralph validate` 无 rule 检测「某 detection/evidence 扫描器
是否覆盖了同一语义输入在 schema 中的所有等价承载字段（checks vs 顶层 command）」——属 DG-12（adapter 字段 parity）/
DG-15（writer↔checker parity）家族在**checker 输入字段表面完整性**维度的延伸。本批 FL-63/FL-64 各自补扫顶层 command，
但**通用「checker 输入字段表面 parity」检测规则仍缺**。
- issue_id: DG-37
- detection_type: checker-input-field-surface-parity（检测器输入字段是否覆盖 schema 等价承载字段集 rule）
- description: validate 无法检测证据/标记扫描器只覆盖 verification.checks 而遗漏语义等价的顶层 verification.command，command-only 主路径静默逃逸

#### DG-38（validate 无法检测「受锁保护的共享可变状态存在绕过 canonical 守卫 setter 的旁路写点 → 并发不变量在某 writer 失效」）

v70 RV-54 step-3 Codex review（F3 major）暴露：即使 `assign_agent` 自身加锁原子化，`AssignmentFallbackMixin.
sync_busy_agents_to_pool()` 仍直接 `pool._active_assignments[agent_id]=task_id`（assignment_fallbacks.py:79-80，
未持锁，且在 batch 主路径先于 pool 评估执行）→ 锁外写旁路使并发不变量在该 writer 失效，单测过但线上仍有竞态窗口。
`ralph validate` 无 rule 检测「某受 threading.Lock 保护的共享可变状态（如 pool._active_assignments）是否存在不经
canonical 受锁 setter/helper 的直接写点（含跨类 mixin/旁路）」——属 DG-9（register-before-side-effect 并发时序）
家族在**共享状态 writer 收敛性**维度的延伸（DG-9 查唤醒注册时序，此处查"所有 writer 是否都走受锁通道"）。
本批 RV-54 把 assignment_fallbacks 写路径收敛到受锁 helper，但**通用「共享状态所有 writer 须经受锁守卫」检测规则仍缺**。
- issue_id: DG-38
- detection_type: shared-state-writer-lock-convergence（受锁共享状态所有写点是否经 canonical 受锁守卫 rule）
- description: validate 无法检测受锁共享可变状态存在绕过受锁 setter 的旁路写点（含跨类 mixin），并发不变量在该 writer 失效

> DG-36/DG-37/DG-38 均由 v70 A 类批次 step-3 Codex review（verdict=adjust）发现、`ralph validate` 当前放行 →
> 纳入 DG 规则族 detection-capability 缺口；本批仅在各自具体实例（RV-62 取证降级 / FL-63·FL-64 补扫顶层 command /
> RV-54 写路径收敛）修复，通用检测规则待后续专项。F4 silent-no-op 子项为既有 DG-27 实例、F5 CLI 接线测试为 DG-31 家族实例。

<!-- v71 批次（B 类多层契约专项 + 蓝图不变量/盲点：FL-74/BPA-3/MSE-NS/BPA-4）step-3 Codex 对抗设计评审
     （.ralph-flow/step-3-review/design_review.json，verdict=adjust，2 blocker + 3 major + 1 minor，6 finding
     全采纳，见 plan.yaml finding_refs）暴露的**新** `ralph validate` detection-capability 缺口：DG-39/DG-40/DG-41。
     F4（MSE-NS peer-reuse 绕过 selector）为既有 DG-13（dual-path-decision-parity / group-peer 旁路）实例；
     F5（BP-5 非 ledger-backed plan-version stamp = dormant bookkeeping）为既有 DG-1 write-without-consumer 家族实例；
     F6（合同变更漂移既有 MonitorConfig/apply_event 测试契约面）为既有 DG-11（contract-change 未枚举 regression surface）实例。
     这三者不另记，仅在此标注其反复印证。 -->

#### DG-39（validate 无法检测「新增守卫/门所消费的证据字段在所有真实生产入口都无 producer → 守卫休眠或全量误杀」）

v71 BPA-3 step-3 Codex review（F2 blocker）暴露：拟新增 INV-7 完成守卫消费 `evidence.self_test`，但所有真实
completion 入口都不产出该字段——REST `TaskCompletedRequest`（ports/web/routes/workflow.py:76）无 self_test/attempt_id；
AF 桥 `convert_af_results_to_completion_events`（af_gateway_bridge.py:405）只发 exit_code/interim_statuses；
`verification_gate.process_completed_event`（:207）重建 evidence dict 时丢弃 payload 内的 self_test。后果是该守卫一旦
开启即**两难**：默认 OBSERVE/不消费=休眠门（DG-6 镜像），WARN=把所有真实完成误判违例，BLOCK=死锁完成主路径。
`ralph validate` 无 rule 检测「某新增 guard/gate 消费的输入/证据字段，是否在其全部真实生产入口（所有 producer 调用点）
都被写入」——属 DG-6（gate/consume-without-producer）家族的**多入口 producer 覆盖**维度延伸（DG-6 查单一 gate 无 writer，
此处查"字段被消费但跨所有真实入口零 producer"）。本批 BPA-3 先建齐 REST/AF/透传 producer 再开守卫，但**通用
「守卫消费字段的全入口 producer 覆盖」检测规则仍缺**。
- issue_id: DG-39
- detection_type: guard-consumed-field-producer-coverage（守卫消费字段是否被全部真实生产入口写入 rule）
- description: validate 无法检测新增守卫消费的证据字段在所有真实生产入口均无 producer，导致守卫休眠或全量误杀/死锁主路径

#### DG-40（validate 无法检测「证据/关联字段声称的来源值只在消费点的下游才生产 → 时间倒流式反查伪证据」）

v71 BPA-3 step-3 Codex review（F1 blocker）暴露：草案让完成守卫的 `self_test.source = verification_id`，但
completion 上报（verification_gate.process_completed_event:207 调 report_worker_completion）**早于** verification 运行
（verification_id 要到 ralph_service._verification_result:1095 才生成）。即证据字段在守卫触发点声称的来源值在该点
**尚不存在**，只能反查/回填 → 时间倒流式 reverse-inferred 伪证据。`ralph validate` 无 rule 检测「某证据/关联字段
声称取自某 producer，但该 producer 在生产调用链上位于该字段消费点的**下游**（时序上消费早于生产）」——属 DG-26
（审计字段来源真实性）+ DG-9（register-before-side-effect 时序）家族在**证据来源时序可用性**维度的交叉延伸。本批改为
worker 原生上报 self_test（不引用尚未生成的 verification_id），但**通用「证据来源时序可用性」检测规则仍缺**。
- issue_id: DG-40
- detection_type: evidence-source-temporal-availability（证据字段来源是否在其消费点已生产 rule）
- description: validate 无法检测证据字段声称的来源值只在消费点下游才生产（时序消费早于生产），导致反查/回填伪证据

#### DG-41（validate 无法检测「守卫/hook 抛出的异常类型被中央处理器映射到与其意图不符的语义类别 → 拒绝/审计语义被误标」）

v71 BPA-3 step-3 Codex review（F3 major）暴露：草案让 INV-7 monitor 型守卫 BLOCK 时抛 `PreTransitionVetoed`，但
`apply_task_event`（workflow_orchestrator.py:1879）对 `PreTransitionVetoed` 一律按 `plan_digest_divergence` 返回码/
审计语义处理；而既有 monitor hooks（workflow_monitor.py:241 create_completer_mismatch_hook）统一抛 `TransitionRejected`。
若 INV-7 借用 veto 类型，其拒绝会被误标成"计划摘要漂移"，污染返回码/审计契约并打坏相关测试。`ralph validate` 无 rule
检测「某 guard/hook 抛出的异常类型，是否与其语义类别（monitor 拒绝 vs plan-digest veto）匹配——即中央 handler 对该
异常类型的分派语义是否与守卫意图一致」。属「证据/语义存在性≠语义正确性"家族新维度（异常类型↔处理器语义 parity）。
本批 INV-7 改用 TransitionRejected，但**通用「守卫异常类型↔处理器语义一致性」检测规则仍缺**。
- issue_id: DG-41
- detection_type: guard-exception-type-semantics-mismatch（守卫异常类型与中央处理器分派语义一致性 rule）
- description: validate 无法检测守卫/hook 抛出的异常类型被中央处理器映射到与意图不符的语义类别，拒绝/审计语义被误标

> DG-39/DG-40/DG-41 均由 v71 B 类批次 step-3 Codex review（verdict=adjust，2 blocker + 3 major + 1 minor）发现、
> `ralph validate` 当前放行 → 纳入 DG 规则族 detection-capability 缺口；本批仅在各自具体实例（BPA-3 建 producer +
> 原生证据 + TransitionRejected）修复，通用检测规则待后续专项。F4→DG-13 / F5→DG-1 / F6→DG-11 为既有缺口的反复印证（不另记）。

### v71 本批已 behavior-verified（B 类多层契约专项 + 蓝图不变量/盲点，solve flow 全 7 步完成）

**FL-74 / BPA-3 / MSE-NS 已 behavior-verified；BPA-4 = BP-2 已 behavior-verified、BP-5 诚实 DEFERRED。**
全量回归 **3995 passed, 120 skipped**；step-5 并行度 dogfood `E=3, D=5`；step-7 regression `overall_pass=True`；
step-3 Codex 对抗评审 6 finding（2 blocker + 3 major + 1 minor）全采纳（见 plan.yaml finding_refs）。

- **FL-74（T1）**：`Agent.model_runtime` 合同默认 `claude→codex`（agent.py）+ `_load/_save_agent_yaml` 兜底同步
  `codex`（agent_ops.py:119/146，与 `model_dump(exclude_defaults=True)` round-trip 自洽）。**behavior 证据**：
  隐式 runtime Agent round-trip 读回 `codex`、显式 `claude/gemini/amp` round-trip 不变；真实仓库 DG-20
  `W_SEMANTIC_DEFAULT_VALUE_DRIFT` 在 agent_ops.py **消失**（修复前报、修复后 `issues==[]`）。
  `test_bclass_fl74_runtime_default.py` 5 passed + 受影响既有用例 14 passed。
- **BPA-3（T2）**：先建 **self-test producer**（REST `TaskCompletedRequest` 增 attempt_id+self_test → AF 桥
  `convert_af_results_to_completion_events` evidence 带 self_test → `verification_gate.process_completed_event`
  透传 `payload['self_test']`），再落 **INV-7 monitor-style guard** `create_fresh_self_test_hook`（注册到完成主路径，
  缺失/陈旧 self_test（attempt_id 不匹配）→ WARN emit `KIND_MONITOR_VIOLATION`，BLOCK 抛 **`TransitionRejected`**
  非 PreTransitionVetoed）。证据取 worker 原生上报，非反查 verification_id。`test_bclass_bpa3_inv7.py` + 回归 48 passed。
- **MSE-NS（T3）**：`TaskRef.type`/`TaskSpec.type` 枚举扩 `security_review`；新增 `ralph/task_typing.py
  infer_task_type`（单一 token 源，coverage.py 复用），`TaskSpec.to_task_ref` 上游定型（词表**可达**非休眠）；
  采纳 F4 把 `_find_group_peer_agent` 做成 security_review-aware（纯 codex peer 跳过/降权），使 new-agent 与
  peer-reuse 两条路由都收敛 claude。**behavior 证据**：安全审查 TaskSpec→`to_task_ref().type=='security_review'`→
  `select_model_for_task` 解析到 claude runtime。`test_bclass_msens_task_type.py` + 回归 61 passed。
- **BPA-4（T4）**：**BP-2 liveness 强制约束** behavior-verified——`check_liveness_deadline` + `MonitorConfig.liveness`
  接入 orchestrator stall 巡检主路径，超硬截止无推进 → WARN emit ledger `KIND_MONITOR_VIOLATION(liveness)`，
  BLOCK 走 `retry_task` 强制升级使任务脱离无限挂起。`test_bclass_bpa4_liveness.py` + 回归 46 passed。
  **BP-5（动态 DAG 版本治理）= 诚实 DEFERRED**（step-3 F5）：运行时无动态拆分路径可治理、static unknown-dep 已由
  E_DEP_UNKNOWN 覆盖，非 ledger-backed 的 plan-version stamp 即 dormant bookkeeping → 本批不落地，见下方 BPA-4 条目。
- **T5**：跨任务回归脊 `test_bclass_regression_spine.py` 9 passed（四项主路径正反锁，真实数据模型不塞造）。

> FL-74 / BPA-3 / MSE-NS 三项可迁入 full 归档；BPA-4 仅 BP-2 闭合，条目降为「BP-5 动态 DAG 版本治理专项（P3，待动态拆分特性）」。

### v69 本批已 behavior-verified（第四阶段 M3-1~M3-4 全量 + DG-33，solve flow 全 7 步完成）

**behavior 证据（真实 CLI + 端到端 pilot + 全量回归）**：
- **M3-1（T1）**：`ModuleSpec` 扩为蓝图全结构（purpose/interface.provides·consumes/mock_inputs/expected_outputs/
  black_box_tests{command,selector}/integration_contract/completion_evidence）+ `normalize_module()` 归一层
  （legacy-flat 与 blueprint 两路产出一致 canonical）+ TaskRef 投影透传；**单 oracle 不变量**（black_box_tests
  无 expected 键，期望唯一来自 expected_outputs，采纳 F4）。10 passed。
- **M3-2（T2+T6）**：`src/cccc/ralph/module_acceptance.py` 共享黑盒验收引擎
  `verify_task_modules(task, *, workspace_root, recorder)`——真实子进程跑 black_box_tests、按 selector 比对
  expected_outputs；缺 black_box_tests → fail-closed；拼接契约引用不存在 module → fail；workspace_root 缺失 →
  `W_MODULE_ACCEPTANCE_SKIPPED_MISSING_CONTEXT`（非静默，采纳 F5/DG-27）。`ralph module verify` CLI 主路径
  + **verification_gate blocking gate**（采纳 F1，非 advisory，置于终态 emit 前）。**pilot 端到端满足 M3 退出标准**：
  `tests/fixtures/m3_pilot/plan.yaml`（一真实 Task 拆 2 Module，mock I/O + 拼接）→ `ralph module verify` exit 0；
  `plan_bad.yaml`（缺 black_box_tests + 拼接断裂）→ exit 1 + `ralph validate` 报
  `W_MODULE_NO_BLACKBOX_EVIDENCE`/`W_MODULE_INTEGRATION_CONTRACT_UNRESOLVED`（unsuppressed CLI check，采纳 F6）。6+ passed。
- **M3-3（T4）**：`prompt_builder.py` worker 输入收窄——经 normalize_module 渲染结构化收窄块（模块目标/接口/
  模拟输入/预期输出/验收命令/允许·禁止路径/失败上报格式）；无 modules 不渲染。10 passed（含既有 prompt 测试）。
- **M3-4（T3）**：`workflow_orchestrator._check_batch_completion` 返回 pass|blocked|none + workflow 级
  `batch_e2e_status`（采纳 F2 blocker 状态通路）；仅 pass/managed 豁免才调 `on_batch_completed` +
  `_check_workflow_completion_after_terminal`，失败 → `batch.e2e_failed` + **阻断 auto-complete**；普通 suppress_codes
  含 E_BATCH_E2E_FAILED 不放行、仅 managed suppress_instance 豁免。9+75 passed。
- **DG-33（T5）**：`validation_rules/task_granularity.py` `_check_task_granularity` + `W_TASK_GRANULARITY_COMPRESSION`
  ——钉死常量（_MIN_ADDRESSES=4/_MIN_COMPONENTS=3/_MIN_BEHAVIOR_SEGMENTS=4）+ 组件归类 normalization
  （tests/·fixture 不计组件，integration/verification role 豁免，采纳 F7）+ cohesive negative fixture 防误伤。
  经 T6 接入 `validator._collect_structural_issues`（`ralph validate` 活跃路径，非死代码）。5 passed。
- **接线/集成脊柱（T6）**：`_check_module_structure`（3 新码，纯结构无 subprocess，采纳 F1）+ DG-33 规则
  均注册进 `get_all_rules` + `validator`；`test_m3_spine.py` 真实 import+调用生产符号汇合断言。6 passed。
- **回归**：全量 `pytest` **3937 passed / 120 skipped / 0 failed**；`ralph regression run` **10/10 场景 overall_pass=true**；
  step-5 FL-73 并行度门 **satisfied E=5, D=7**（5 个 claimed_paths 两两不相交任务真并行 fan-out + 1 fix pass）。
- **step-3 Codex 设计评审 verdict=adjust，7 finding（2 blocker + 5 major）全采纳**（见 plan.yaml finding_refs）；
  step-5 全量门连带修复 2 个跨文件回归（validator.py 行数门 + module_acceptance 复杂度）+ 1 个 v68 遗留
  RS-STD-2 expect_valid 不一致。新留存 detection-capability 缺口 **DG-34/DG-35**（上方）。

> **第四阶段（M3 蓝图中间层）核心闭环已落地**：module 分解从 advisory（只进 prompt）升为 enforced
> （`ralph validate` 结构门 + `ralph module verify` 黑盒主路径 + verification_gate blocking + batch_e2e 阻断），
> 一个真实 Task 拆 ≥2 Module 的 mock I/O 黑盒验收 + 拼接通过 Task verify gate（满足退出标准）。DG-33 任务粒度
> 检测一并落地。**仍开放（待后续专项）**：M3-2 全活体 daemon blocking 分布、M3-1 全 task 类型推广、DG-34/DG-35
> 通用元检测规则。

### M3-1（引入 module_specs）

每个 Task 先被 Foreman 拆成多个 Module，每个 Module 必须有固定结构：

```yaml
tasks:
  - id: T1
    goal: ...
    modules:
      - id: T1.M1
        purpose:
        interface:
          provides:
            name:
            input_schema:
            output_schema:
          consumes:
            - name:
              schema:
        mock_inputs:
          - name:
            value:
        expected_outputs:
          - name:
            value:
        black_box_tests:
          - command:
            expected:
        integration_contract:
          upstream:
          downstream:
        completion_evidence:
          required:
            - module_io_passed
            - schema_contract_passed
            - self_test_fresh
```

### M3-2（四层验收体系）

| 层级 | 谁负责 | 验收方式 | 不允许通过的情况 |
|------|--------|---------|--------------|
| Module 级 | Worker | 给定 mock input，输出 expected output | 只提交代码、无 I/O 证据 |
| Task 级 | Foreman / Ralph | 模块拼接 + consumes/provides 契约测试 | 模块各自通过但拼不上 |
| Batch 级 | Orchestrator / Ralph | 当前 frontier 全部完成后跑批次 E2E | 单个 task 绿但批次行为不变 |
| Global 级 | E2E Flow | 全流程场景验证 | tracker 归档但症状仍复现 |

### M3-3（Worker 输入收窄）

Worker 不应拿到"修整个系统"的大任务，而应拿到：

```
模块目标
接口规范
模拟输入
预期输出
允许修改路径
禁止修改路径
验收命令
失败时上报格式
```

减少"自己理解需求、自己定义完成、自己写测试证明自己完成"的空间。

### M3-4（批次级行为断言）

批次完成后的 E2E 不受 plan suppress_codes 控制：

```yaml
batch_e2e:
  commands:
    - "cccc model suggest backend"
    - "cccc workflow run sample-af-task"
  assertions:
    - "model_runtime == codex"
    - "execution_engine == af"
    - "workflow.completed emitted only after verification_passed"
```

**假完成拦截映射**：

| 假完成类型 | 蓝图中间层如何拦截 |
|-----------|------------------|
| AF 组件写好但 orchestrator 不调用 | Task 级拼接验证失败 |
| compile 了但没有 execute | Module/Task 验收缺少 expected output |
| model rating 只写不读 | Batch E2E 中 `model suggest` 输出不符合预期 |
| WORKFLOW_EVALUATION 空章节 | 黑盒输出对照失败 |
| 默认 runtime 改一处漏一处 | interface/default registry consistency 失败 |
| guide 改了但行为没变 | Batch E2E 行为断言失败 |

---

## 未归入里程碑的既有问题 —— A 类 P1/P2/P3 全部已 behavior-verified（v70），归档

> **v70 批次（2026-06-07，solve flow 全 7 步完成）**：A 类 10 个独立 bug（FL-72/FL-63/FL-64/FL-67/
> FL-71/RV-62/RV-63/FL-70/RV-39/RV-54）全部 behavior-verified。step-3 Codex 设计评审 verdict=adjust
> （1 blocker + 3 major + 1 minor）5 finding 全采纳（见 plan.yaml finding_refs）；衍生检测能力缺口
> DG-36/DG-37/DG-38 已记入 DG 规则族。证据束见 `.ralph-flow/step-3-review/` + `.ralph-flow/step-5-execute/`。
> 全量 `pytest` **3959 passed / 120 skipped / 0 failed**；`ralph regression run` overall_pass=true；
> step-5 并行度门 **satisfied E=5, D=6**（T1~T5 claimed_paths 两两不相交真并行 fan-out + T6 spine）。

**behavior 证据（真实主路径 + 全量回归，逐项）**：
- **RV-54（P3，T1）**：`AgentPoolManager` 增 `_assignment_lock`，`assign_agent`/`release_agent` 及
  `assignment_fallbacks.sync_busy_agents_to_pool` 旁路写全部收敛到受锁 helper（采纳 F3 消除锁外写旁路）。
  并发压力测试：多线程并发 assign 同一 agent 恰好一个生效；无锁反证 24 个线程都"领取成功"→ 可证伪。3 passed。
- **RV-62 + FL-63（P2，T2）**：`independently_reviewed` 改由真实运行时证据驱动——被审目标取
  `TaskRef.verification.covers_tasks`/`depends_on`，执行者身份取持久化 completion/warning 证据，无可证独立证据
  保守降级 passed（采纳 F1 blocker，不靠塞造字段）；`test_stats_reliable` 随机化启用判定扩到顶层
  `verification.command` + checks（采纳 F2，command-only 主路径不再误判）。7 passed + 13 既有回归不破。
- **FL-70（P3，T3）**：`extract_friction_events` 补识别 `KIND_MONITOR_VIOLATION`(alert_type=W_WORKER_EXCEEDED_SCOPE)
  → friction 记录 scope_warning；既有 task_failed/deferred/override 识别不变。3 passed。
- **FL-64（P2，T4）**：forbidden_flow 字段负向断言覆盖——`project_root is None` 不再静默放行，产出真实
  `W_FORBIDDEN_FLOW_FIELD_TEST_UNVERIFIABLE` ValidationIssue（采纳 F4，非日志侧信道）；扫描集纳入顶层
  `verification.command`（command-only task 不再绕过）。5 passed + 既有 forbidden_flow 回归 10 passed。
- **FL-71 + FL-72（P2/P1，T5）**：认证链路测试改用真实受鉴权探针 `/api/v1/__test__/principal`（缺/坏 token→401、
  有效 token→200+principal），不再以 `/health` 200 作认证证据；新增 `test_aclass_fl72_notify_isolation.py`
  经 `system_notify`+inbox 主路径断言两 actor inbox disjoint（合并返回即失败，可证伪）；复核未发现真实泄漏，源未改。14 passed。
- **RV-63 + FL-67 + RV-39（P2/P2/P3，T6 verification）**：CLI 级正反回归锁（采纳 F5，经
  `ralph.main(["validate", ...])` 入口）——RV-63 consume-without-dep→W_CONSUME_WITHOUT_DEP/补 dep 不报；
  RV-39 goal 410 vs 实现 404→W_STATUS_CODE_IMPLEMENTATION_DRIFT/一致不报；FL-67 override 完成态经真实
  `sync_plan_state` 进 completed_task_ids。3 passed。

> RV-63/FL-67/RV-39 核心实现于 v60–v69 未提交工作中已落地，v70 复核并补 CLI 级回归锁固化；
> FL-64 的 assertion-level 覆盖、FL-67 的 override sync 亦同。**A 类全部清空，无 P1/P2/P3 标准 bug 遗留。**
> 残留检测能力缺口（内容级/函数级/跨函数等）见 DG 规则族（DG-36/37/38 等待后续专项）。

---

## 蓝图对齐缺口（工作流蓝图 v0.3 vs 现状，v69 三方审计）

> 来源：v69 用户要求审计「完成的里程碑 vs 工作流蓝图 vs v60 执行计划」。结论：里程碑严格按 v60 完成，
> 但 v60 是蓝图的「假完成修复」子集；以下为蓝图（理想全量工作流）相对现状的对齐缺口。
> **偏差1（M3-3 worker 收窄泄漏 oracle）已在 v69 修复**（按蓝图盲验证收口：worker 只见 mock_inputs+接口，
> expected_outputs/验收命令对 worker 隐藏，与 `prompt_builder.py` 既有「mock_tests must never be rendered
> to workers」不变量一致；v60 M3.3 文档同步修正）。其余记为开放项：

#### BPA-1（M3 落地的是 schema + 验收门，蓝图的运行时两阶段执行模型未落地）

蓝图 4.2/4.3 核心运行时循环——Foreman 在**运行时**把 Task 拆成 Module → 并行派发 module-worker
（模拟 I/O 不等依赖）→ **自动拼接** → Task verify gate → Batch E2E——在 live daemon **未实现**
（foreman 无运行时模块拆分/派发/拼接代码）。`modules` 目前只被 prompt_builder 渲染 +
`ralph module verify` CLI/validate + verification_gate 阻断 hook 消费。M3 退出标准是用 CLI + pilot
fixture（plan/CLI 层）达成，非 daemon 运行时达成。**完成 M3 里程碑 ≠ 蓝图运行时模型落地**。
- 优先级 P2（中间层 schema/验收已就绪，运行时编排为下一主攻方向；属蓝图「试点先行」的预期边界）

#### BPA-2（Ralph Agent = Gemini Flash 与「不用 gemini」方向冲突——gemini 确认不用）

蓝图 1.1/3.4 规定 Ralph Agent 用 Gemini CLI Flash、默认启用；代码 `src/cccc/ralph/agent.py:31-33`
确为 `gemini-cli`/`flash`。但用户方向明确**仅 claude+codex、gemini 不用**（v69 再次确认「依旧不用 gemini」），
flow 实践一律 `--no-agent`（纯静态）。→ 蓝图语义审查 agent 层在「默认启用 gemini」这点与现行方向不一致。
**决议：gemini 不用**；Ralph Agent 层保持 `--no-agent`（或后续换 claude 模型，待定）。蓝图该条待更新为
「agent 层暂缓 / 换模型，不用 gemini」。
- 优先级 P3（当前纯静态模式可用；语义审查暂由 step-3 Codex review 在 solve flow 内承担）

#### BPA-3（蓝图 7 不变量只落地 6 条——INV-7 NO_COMPLETE_WITHOUT_FRESH_SELF_TEST 未作命名引擎守卫）—— ✅ 已 behavior-verified v71

> **v71 已闭合**：先建 self-test producer（REST/AF/verification_gate 透传，使守卫输入经真实完成主路径可达），
> 再落 monitor-style guard `create_fresh_self_test_hook`（缺失/陈旧 self-test → WARN emit KIND_MONITOR_VIOLATION，
> BLOCK 抛 TransitionRejected），证据取 worker 原生上报非反查。证据见上「v71 本批已 behavior-verified」。待迁 full 归档。

蓝图 3.3 列 7 条 engine pre-transition guard，第 7 条 INV-7（DI-10 前移）要求 worker complete 必须附
当次 attempt 的 fresh self-test；代码 grep 无此命名守卫。相关开放症状 **FL-63**（test_stats_reliable
自动判定缺失）与蓝图盲点 **BP-4**（self-test 真实性）同源——worker 可复用旧结果/跑弱自测骗过 gate。
- 优先级 P2（与 FL-63 合并：作为 INV-7 fresh-self-test 引擎守卫专项）

#### BPA-4（蓝图 5.3 盲点：BP-2 ✅ 已 behavior-verified v71；BP-5 动态 DAG 版本治理专项 DEFERRED）

蓝图 5.3 五盲点中：BP-1(async 幂等)≈AF-07 已修、BP-3(统一 assignment contract)≈M2-A 已修、
BP-4(self-test 真实性) 由 BPA-3 INV-7 闭合（v71）。
- **BP-2（liveness）✅ v71 已闭合**：`check_liveness_deadline` + `MonitorConfig.liveness` 接入 orchestrator stall
  巡检主路径，超硬截止无推进 → ledger-backed KIND_MONITOR_VIOLATION，enforce 走 retry_task 强制升级使 workflow
  脱离无限挂起（不再「只有 gap 检测无强制约束」）。证据见上「v71 本批已 behavior-verified」。
- **BP-5（动态 DAG 变更版本治理）DEFERRED**（step-3 Codex F5 诚实收缩）：探查证实**运行时无动态拆分路径**可治理，
  static unknown-dep 已由 E_DEP_UNKNOWN 覆盖；非 ledger-backed 的 per-task plan-version stamp 即 dormant bookkeeping
  → 本批不落地任何 BP-5 代码，待**运行时动态拆分特性落地后**专项（含拆分后 depends_on/claimed_paths 重算 + 版本治理设计）。
- 优先级 P3（BP-5：需动态拆分特性 + DAG 版本治理设计；属已知边界）

> BPA-1~BPA-4 由 v69 三方审计发现；属「蓝图运行时模型 / agent 层 / 引擎不变量 / 盲点」对齐缺口，
> 与 DG 规则族（validate 检测能力）正交。偏差1 已修，其余记为开放项待后续专项。

---

## E2E v70 实战验证（真实 daemon 收口，2026-06-08）

> 注：此处「E2E v70」指 E2E 报告序列（v58→v70），与 tracker 中 solve 批次标签 v70/v71 不同源，勿混淆。
> 报告：[e2e-实战评估报告-v70.md](./e2e-实战评估报告-v70.md)。项目：FastAPI 短链接服务。综合 3.5/5。
> 团队 foreman(claude)+exec-a/b/c(codex)+sec-rev(claude)，8 tasks 全完成（passed=5/overridden=3），execution_engine=af，约 52min。

**v60–v69 大量 in-process 验证的机制首次在真实 daemon E2E 下全面活体背书（全部 ✅ 生效）：**
- **模型选择保真**（FL-74/MSE/AF-09）：foreman 按能力指南给执行者全选 codex、安全审查选 claude；实时监控确认 3 codex + 1 claude 执行。
- **FL-73 并行度门**：estimated_parallelism=3 → 建 3 codex，B2 实测 run=3 并行 fan-out，无串行退化。
- **AF 真异步**（AF-07/08）：execution_engine=af，8/8 完成，无死循环/无 deferred 卡死。
- **反假完成/AEGIS evidence gate**：T1 compile+6/6 pytest 全绿仍被 E_AEGIS_EVIDENCE_MISSING 拦下（缺 --evidence）。
- **章节实质化门**（M2-C/UX-23 修复）：step-4 检查逐项 PASS（正面 833/负面 1248/手工干预 837/Worker 563/评分 599 chars），**UX-23 未复现**。
- **诚实测试统计**：自动采集失败→test_stats_reliable=false + 手动复核，未伪造绿。

**E2E v70 实战新发现（Codex results=adjust/74 + process=revise/43 + foreman 负面反馈）：**

| ID | 描述 | 来源 | 优先级 |
|----|------|------|--------|
| RV-64 | canonical `state.tasks` 不覆盖全部任务（8 任务仅记 5），缺 override/attempts/independently_reviewed 字段；override 证据散落 `.cccc/task_contexts` 而非 state——评估文档"记入 state"声称与现状不符（FL-67 仅部分闭合） | process F1/F2 | **P0** |
| DG-43 | `.cccc/performance/model_usage.jsonl` 记 `model_key=claude-sonnet-4-20250514` 配 `runtime=codex`（T3_ratelimit）——实际 runtime 正确（活体已确认），但 **model_key 默认值仍漂移为 claude**，FL-74/DG-20 默认漂移修复未覆盖 usage 日志路径；validate 检测盲点 | process F5 | **P0** |
| FL-76 | 负载均衡无视 foreman `--assignments`，把实现任务 T5 派给 claude 审查者 sec-rev，破坏 runtime/角色隔离（FC-1 未落派发层） | foreman 负面反馈 | **P0** |
| FL-77 | verifier 不经 shell 执行 check（argv 直切），行内 `#` 注释被当 pytest 参数→exit4；与 `ralph validate` 静态覆盖词诉求冲突（两次 override 共同根因） | foreman + process F3 | **P1** |
| FL-78 | retry/reassign 状态机死锁：T5 retry 后卡 ready/无 assignment，worker task complete 报 invalid_state_transition，submit no-op，"干完无法上报" | foreman 负面反馈 | **P1** |
| FL-79 | 路由日志非 per-attempt（8 任务+retry 仅 1 条 model_usage 记录），且无独立 assignment/dispatch 事件日志，模型/角色路由不可独立审计 | process F5 | **P1** |
| RV-65 | independently_reviewed 应一等化进 state（reviewer_actor/runtime/signoff_path/timestamp），并强制 sign-off 文件入 claimed_paths（当前实质独立但 state 无字段支撑） | process F4 | **P1** |
| DG-42 | plan 应支持结构化 `forbidden_flows` + 非可执行 `coverage_hints` 字段，使"满足静态校验器"不必污染可执行命令；review-only 任务产出文档也须入 claimed_paths | process F3 | **P1** |
| RV-66 | 交付代码缺陷 validate/verify 未拦——点击分析非原子部分提交（且测试断言锁死 bug，analytics.py:50-58 / test_analytics_coverage.py:62-80）；SSRF 只拦字面量 IP 不解析 DNS（main.py:110-134）。检测盲点 | results F1/F2 | **P2** |
| UX-24 | 定向派发缺原语（只能 stop/start actor 挤）；scope_warning 误伤审查者产文档；`[SUSPICIOUS: Nms]` 对快测试普遍误报；自动 test 采集不可靠（collection failed vs 手动 51 passed） | foreman + results F3 | **P2** |

**下一批主线**：状态可审计性闭环（RV-64/DG-43/FL-79/RV-65：让 state 成唯一可信、可审计终态记录）+ 派发层保真（FL-76/FL-78：尊重显式指派、修 retry 死锁）+ 静态校验/运行时冲突解构（FL-77/DG-42）。

---

## 已知局限（不修复，仅记录）

| ID | 描述 |
|----|------|
| RV-38 | non-required signoff check 可满足规则（风险低：required=false 仍有 evaluation 记录） |
| RV-41 | AF node completion 绕过 VerificationGate（需 AF 实际集成后结构化检测） |
| RV-43b | agent prompt 直接变更绕过 promotion（promotion 机制尚未实现） |
| RV-47 | AgentFlow/评价闭环新不变量检测（需代码实现后逐步添加） |
| RV-49 | forbidden_flow 字段覆盖检测仅查命令文本，不查测试断言 |
| RV-50 | 集成证据检测以 import 存在性代替调用路径 |
| RV-51 | AF/promotion 绕过检测依赖文本关键词，可被同义表达绕过 |
| RV-52 | FL-66 gap check 关键词改动不新增检测能力 |
| RV-55 | 安全审查独立性规则与 independent review 规则证据面脱节 |
| RV-56 | forbidden_flow 字段三态检测仍有正向出现绕过风险 |
| RV-57 | AF gate bypass 和 authority 两条规则证据源不一致 |
| RV-58 | auth 边界检测与现有 RBAC 规则共用证据面，存在误判风险 |
| RV-59 | 并发安全检测仅查证据文本，可被填写关键词绕过 |
| RV-60 | PlanCompiler TaskRef adapter 缺少 expected_input/expected_output 字段 |
| RV-61 | engine_preference 全链路传播缺少对称校验 |
| RV-AF-05 | PlanCompiler 保存 raw dict 丢失 TaskRef 语义 |
| RV-AF-06 | AF→legacy 自动 fallback 与架构红线冲突 |

---

## 待调研

#### Modal 集成

将 Modal 集成到 CCCC 系统中。具体集成方案和优先级待后续讨论确定。

---

## 完成标准（适用于所有问题）

```
1. 原始症状被重新复现或明确记录
2. 修改点从当前默认 entrypoint 可达
3. 运行时条件在 E2E 环境中满足
4. 主路径行为发生可观察变化
5. fallback 不静默
6. 失败用例会失败，修复后会通过
7. 归档项引用具体 evidence bundle
8. Codex review 发现已采纳、拒绝或转成 tracker item
```

核心判断标准只有一个：不要再问"代码有没有写完"，只问"原始症状是否在真实主路径中消失"。
