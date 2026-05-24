# CCCC 问题清单 v5 (未解决) — Ralph 改进专项

> 日期：2026-04-04（v5.2 蓝图对齐更新）
> 已完成（E2E 验证通过）：RO-7n/12/13n/14n/15/16/17/18/19/20/21/22/23/24/25/26/27/28/29/30/32/33/34/35/37/38/39/40/41/42/43/44/47/48/49/50/51/52/54/55/72、RA-1/2/3/4、RF-1/2/3/4/5、RL-3/5
> 已完成（v24 确认）：RO-61（structural digest）
> 已完成（v26 确认）：RO-62（force-complete→verification_skipped）/RO-69（CORS 验收标准+集成测试双重拦截）
> 已完成（v28 确认）：RO-51（scope 目录匹配）/RO-52（Gemini JSON）/RO-70（prompt 引导零命令变形）/RO-73（claude runtime 零 stall）
> 已完成（v29 计划审查确认）：RO-57（resubmit reject, 12 tests）/RO-65（challenge degradation, 4 tests）/RO-67（--compact, 14 tests）/RO-68（cleanup_patterns, 5 tests）/RO-71（completer_mismatch verification, 4 tests）
> 已完成（v30 代码修复）：RO-74/RO-75/RO-76、RL-21、BP-1/BP-3
> 已完成（v31 代码修复）：RO-77/RO-78/RO-79、BP-2/BP-4/BP-5
> 已完成（v32 E2E 验证）：RO-77 ✅/RO-78 ✅/BP-2 ✅/BP-4 ✅
> v34 计划分析确认已修复：RO-80/RO-81/UX-2
> 代码已修复，场景未触发（迁入 full 归档）：RO-45/46/53/56/58/59/60/63/64、RL-11
> 已完成（v36 代码修复）：RO-82/83/85/86、UX-1/4/7/9、AD-5/6、FL-1/3、RL-23/24
> 已完成（v38 E2E 验证）：RO-103
> 已完成（v39 代码修复，全量 42 项）：RO-84/89/90/91/92/93/94/95/97/98/99/100/101/102、FL-4/5/6/7/8/9/10/11/12/13/15、UX-5/8/11/12、AD-1/2/3/4/7/8/9/11、SL-1/2/3、RL-22/25、PLR-1/2、DOC-1/2、REG-1/REG-2
> 已验证（v39 E2E 确认）：AD-1~3（Aegis discipline 规则实战生效）、RO-84（validate ledger 事件确认）
> v39 新发现：FL-17b（solve flow state.json 清除仍未生效）/FL-18（step-6 归档迁移应为 blocking 非 advisory）/UX-13（foreman 未在 workflow.completed 后自动生成 evaluation）/UX-14（T1 冷启动 stall 300s+ 需放宽首任务阈值）
> 已完成（v40 代码修复）：FL-17b/FL-18/FL-16/PLN-1/UX-14/UX-13 + Codex 审查追加修复 _check_cleanup TimeoutExpired + advisory print 残留清理
> 已验证（v40 E2E 确认，归档至 full）：RO-96/E2E-1/E2E-2/E2E-3（相对路径 attach + challenge mode + temporal_pattern）
> v40 新发现（共 10 项）：RO-104（合同漂移检测）/RO-105（token type 混用漏检）/RO-106（temporal_pattern 只查声明不查集成）/RO-107（foreman 自评不一致）/FL-20（**P1** flow 表述+内容指导+check 机制三重缺陷）/RV-1（task 职责重叠）/RV-2（covers.tasks 满足 glue）/RV-3（race TOCTOU 深度）/UX-16（**P1** actor 崩溃 4 次）/UX-17（scrollback 丢失）
> v41 新发现（共 4 项）：FL-21（**P1** Codex check 伪造 JSON 蒙混）/FL-22（**P1** solve step-4 gap check 只查形式）/RV-4（validate 不检测 goal 引用文件未 claim）/RV-5（validate 不比对 acceptance 与 issue 覆盖度）
> v41 代码修复（12 项）：FL-20/FL-21/FL-22/FL-14/UX-16/UX-17/RO-104/RO-105/RO-106/RO-107/RV-1/RV-2
> 已验证（v42 solve flow 确认，归档至 full）：FL-14（并行 dispatch + skill 引导生效）/FL-22（step-4 gap check 要求 #### 标题+关键词匹配）/RV-3/RV-4/RV-5/RO-99/AD-11/FL-19/E2E-4
> v42 未生效：FL-21（HMAC 签名——CODEX_BRIDGE_SECRET 未配置，所有 JSON 验证回退到 UUID 格式检查）
> 代码已修复，场景未触发（迁入 full 归档）：RO-104/105/106/107、RV-1/2、UX-15/16/17
> v42 新发现（共 5 项）：FL-23（**P1** step-4 gap recording 指导不足，agent 记录无价值内容）/FL-24（step-5 未禁止直接编辑）/RV-6（validate 不检查 plan 前提与代码一致性）/RV-7（validate 不检查 claimed_paths 是否为真实控制层）/RV-8（validate 不检查算法对目标数据可行性）
> 已完成（2026-05-24 代码修复，5 项）：FL-23/FL-24/RV-6/RV-7/RV-8
> Codex review 发现（共 2 项）：RV-9（validate 不检测 check 注册到错误 phase）/RV-10（validate 不检测 plan 中描述的实现方案与现有代码重复）
> flow 执行漏洞发现（共 2 项）：FL-25（**P1** step-5 check 可被手写 JSON 绕过）/FL-26（step-5 不验证 git diff 与 Codex session 对应关系）
> 已完成（2026-05-24 代码修复，4 项）：FL-25/FL-26 + codex_bridge 路径解析 + instruction 动态注入完整路径
> 已完成（2026-05-24 代码修复）：FL-20/FL-21 — HMAC 签名全链路打通（codex_bridge.py 签名 + .env secret 配置 + flow_engine 从 .env 读取 + 未签名 JSON 强制 FAIL）
> 已知局限（归档至 full）：RV-9/RV-10/RV-11（语义级检查超出结构验证范围）
> 验证轮次（2026-05-24 修复后）：全量 pytest 2992 passed / 0 failed / 120 skipped
> 验证轮次（2026-05-20 v42 修复后）：全量 pytest 2978 passed / 0 failed / 120 skipped（+24 新测试）
> 验证轮次（2026-05-20 v41 修复后）：全量 pytest 2954 passed / 0 failed / 120 skipped
> 验证轮次（2026-05-17 v39 修复后）：全量 pytest 2913 passed / 0 failed / 120 skipped
> E2E v28 验证：综合 4.2/5（结果 3/5，过程 5/5，体验 4.5/5）
> E2E v29 验证：综合 3.3/5（结果 2/5，过程 4/5，体验 4/5）
> **E2E v32 验证：综合 4.3/5（结果 4/5，过程 5/5，体验 4/5）——历史新高**
> E2E v33 验证：综合 4.0/5 | E2E v34 验证：综合 3.7/5 | E2E v35 验证：综合 2.3/5 | E2E v35b 验证：综合 3.3/5
> E2E v36 验证：综合 4.0/5 | E2E v37 验证：综合 3.3/5 | **E2E v38 验证：综合 4.2/5**
> **E2E v39 验证（2026-05-17，FastAPI Bookmark Service）：综合 4.3/5（结果 4.5/5，过程 4.5/5，体验 4/5）——历史并列最高**
> E2E v40 验证（2026-05-19，Flask OAuth2 Resource Server）：综合 3.7/5（结果 3.5/5，过程 4/5，体验 3.5/5）
> **E2E v41 验证（2026-05-24，FastAPI Notes Service）：综合 3.8/5（结果 4/5，过程 3.5/5，体验 4/5）**
> v41 新发现（共 6 项，已全部归档至 full）
> **E2E v42 验证（2026-05-24，FastAPI Blog Platform）：综合 4.3/5（结果 4.5/5，过程 4/5，体验 4.5/5）——历史并列最高**
> v42 E2E 新发现（共 5+6+3+3 项）：RO-112/FL-29/FL-30/FL-31/RO-113 + 会话回顾：FL-32/FL-33/FL-34/FL-35/FL-36/FL-37 + 并行度/runtime 分析：FL-38/FL-39/FL-40 + agent 架构：FL-41/FL-42/FL-43
> 全量版本：[问题清单-v5-ralph-full.md](./问题清单-v5-ralph-full.md)
> 评估报告：[e2e-实战评估报告-v42.md](./e2e-实战评估报告-v42.md)（最新）| [v41](./e2e-实战评估报告-v41.md) | [v40](./e2e-实战评估报告-v40.md) | [v39](./e2e-实战评估报告-v39.md)
> **本文档只保留未解决的改进项和已知局限。已完成条目与历史实现记录保存在 full 版本中。**

---

## 未解决改进项

### v45 Codex review 新发现

#### RV-12（validate 不检测 discipline rule 注册遗漏）

discipline_security.py 中定义的规则函数不一定被注册到 discipline.py 的 `_DISCIPLINE_RULES` 列表。现有 validate 无法检测"规则定义了但未注册"的情况。需要：validate 规则自查——扫描 discipline_*.py 模块中 `_check_*` 函数签名符合 `DisciplineRule` 的函数，验证它们是否出现在 `_DISCIPLINE_RULES` 或被其内部调用。

#### RV-13（verification gate 与 validate 的 shallow check 判定不统一）

coverage.py 已有 `_is_compile_or_import_check` 等 shallow check 分类器，但 verification_gate.py 的 runtime gate 需要独立实现同样的判定逻辑。两套判定标准可能漂移，导致 validate 通过但 runtime gate 拒绝（或反之）。需要：抽取公共 shallow check classifier 到共享模块，让 validate 和 runtime gate 共用同一套判定。

#### RV-14（assignment_startup 不消费 actor_add 返回的 running/start_error 字段）

`_start_actor_for_assignment` 只检查 `resp.ok`，但 `actor_add_ops.py` 返回中包含 `running` 和 `start_error` 字段。不消费这些字段会丢失第一手失败原因，导致 actor 注册成功但实际未运行时无法及时发现。需要：消费 `running`/`start_error` 字段，对已注册但 stopped 的 actor 走 restart 语义。

### v42 E2E 新发现

#### RO-112（FTS5 中文查询走 LIKE fallback）

search.py 对含 CJK 的查询直接退回 `LIKE '%query%'`，FTS5 MATCH 不支持中文子串匹配。功能可用但未使用 FTS5 原生能力。需要：在 foreman-capability-guide 中增加 FTS5 中文搜索最佳实践（ICU tokenizer 或 jieba 自定义 tokenize），或在 plan template 中标注 CJK 限制。

#### FL-29（claimed_paths 越界修改）

v42 中 5 个任务（T03/T04/T05/T07/T11）修改了未声明的 app/main.py 和 tests/conftest.py。Codex process review 确认 ledger 记录了 W_WORKER_EXCEEDED_SCOPE。需要：workflow engine 在 task complete 时校验 changed_files ⊆ claimed_paths，越界时拒绝或要求 foreman 确认。

#### FL-30（实现任务 verification 偏浅）

实现任务（T03/T04/T05）的 verification.checks[] 主要是 import/router registration 检查，不验证 CRUD 行为或返回状态码。需要：plan template 强制实现任务包含至少一个行为验证（如 endpoint 调用返回正确状态码）。

#### FL-31（Worker 负载不均衡）

后半段 T07/T08/T09 全分给 worker-2，worker-1 闲置。需要：auto-dispatch 在批次分配时选择空闲最久的 worker，或支持动态 worker 负载均衡。

#### RO-113（默认 JWT 密钥硬编码）

config.py 默认 JWT 密钥 `change-me-in-production`。虽然非生产场景可接受，但 Aegis 应增加"检测默认密钥"规则，在 verification 阶段警告使用默认密钥。

### v42 E2E 会话回顾发现

#### FL-32（**P1** state.json 无完整性保护——可直接编辑跳过 flow 步骤）

`.ralph-flow/state.json` 存储 `current_step` 和 `steps_completed`，但无任何签名、校验和或加密保护。agent 可以直接 `Edit` 修改 state.json 的 `current_step` 和 `steps_completed` 字段来跳过任意步骤（本轮实际发生：step 6 被手动跳过）。这是与 FL-21（HMAC 签名绕过）同级别的完整性问题——HMAC 保护了 Codex 输出，但 flow 自身状态完全裸奔。
需要：state.json 增加 HMAC 签名字段，`ralph flow next` 每次验证签名后才执行 check，检测到篡改时拒绝推进并报告。

#### FL-33（**P1** Step 4 不预检 CODEX_BRIDGE_SECRET——浪费完整 Codex 调用后才报错）

Step 4 指令要求运行 Codex review，但不检查 `.env` 是否存在及 `CODEX_BRIDGE_SECRET` 是否配置。agent 跑完两轮 Codex（约 3 分钟 + API 费用）后 `ralph flow next` 才报 authenticity FAIL。本轮实际发生：两次 Codex review 白跑一轮后才发现要配密钥。
需要：step 4 的指令输出或 `ralph flow next` 在 step 3→4 过渡时增加 pre-flight check：检查 `.env` 存在且含 `CODEX_BRIDGE_SECRET`，不满足时直接 FAIL 并给出 fix 命令，避免浪费 Codex 调用。

#### FL-34（Step 6 归档删除检测基于 git diff，跨会话状态不一致导致误判）

Step 6 check 要求 `git diff` 中出现已完成项（FL-27/FL-28/RO-108~111）的删除行（`-` 行）。但这些 ID 是前几轮会话在工作区加入但从未 commit 的内容——它们不在 git HEAD 中，因此 diff 中不可能出现删除行。check 连续 3 次 FAIL，最终只能通过手动修改 state.json 跳过（触发了 FL-32）。
需要：step 6 的归档检测不应只依赖 git diff，应改为比较当前文件内容与已知完成项列表——如果短版 tracker 中不再包含已完成项的详细描述段落，则视为已归档。或者要求 flow 开始前先 commit 工作区变更，建立干净基准。

#### FL-35（Codex review 用 read-only sandbox 无法跑 pytest——review 分数失真）

Step 4 的 Codex review 使用 `--sandbox read-only`，但 pytest 的 conftest.py 需要 `tempfile.mkstemp()` 创建临时数据库，read-only sandbox 无可写临时目录。导致 41 个测试全部报 `FileNotFoundError`，Codex results review score 被拉到 2-3/5，但本地跑实际 41/41 全绿。
需要：E2E flow 的 Codex review 步骤应使用 `--sandbox workspace-write`（或至少在 prompt 中明确说明 sandbox 限制，让 Codex 不要因环境问题降分），否则 results review 的分数不反映真实代码质量。

#### FL-36（Step 2 需求模板缺少 .env 配置指引）

Step 2 输出的需求模板没有提醒在 workspace 中创建 `.env` 文件并配置 `CODEX_BRIDGE_SECRET`。这导致到 step 4 才暴露配置缺失问题。模板应增加一个"环境准备"步骤，或 flow engine 在 step 1（workspace prepare）阶段自动生成 `.env`。

#### FL-37（Step 6 "已完成项"来源不明确——check 如何确定哪些项需要删除？）

Step 6 check 判定 FL-27/FL-28/RO-108~111 需要从短版 tracker 删除，但没有明确说明这个"需要删除"列表的来源。是从 full tracker 的"已完成"标记中提取的？还是从短版 tracker header 的"已完成（v45 代码修复）"行解析的？如果来源是未 commit 的工作区内容，那 check 的可靠性取决于前几轮会话是否正确标记——一旦标记格式偏移，check 就会产生 false positive 或 false negative。
需要：check 逻辑应明确记录"需要删除"列表的推导路径，并在 FAIL 输出中展示来源，方便 agent 定位问题。

### v42 E2E 并行度分析发现

#### FL-38（**P1** auto-dispatch 只查 assignment-map 不做负载均衡——空闲 worker 被浪费）

auto-dispatch 的任务分配完全依赖 foreman 在 `cccc workflow submit --assignment-map` 中指定的静态映射。当 batch 中有 3 个可并行任务但 assignment-map 全指向同一个 worker 时，其余 worker 闲置。v42 Batch 5 实际发生：T07/T08/T09 全分给 worker-2，worker-1 从 09:15 到 09:22 完全空闲（7 分钟）。

**根因**：`assignment_batches.py:220-244` 的 `_build_explicit_assignment_result()` 只从 `suggestion.assignments` 查找预设映射，没有 fallback 到空闲 worker 的逻辑。`workflow_orchestrator.py:1040-1043` 的 `_auto_dispatch_ready_tasks()` 在构造 batch 时也不检查 worker 空闲状态。

**需要**：auto-dispatch 在分配任务时增加负载感知——当 assignment-map 中的目标 worker 已有 running 任务时，将新任务分配给空闲 worker。或者实现 round-robin / least-loaded 策略作为 assignment-map 的补充。

#### FL-39（Foreman 默认只创建 2 个 worker——未根据 DAG 最大并行度调整）

Foreman 固定创建 2 个 worker（worker-1 + worker-2），但 v42 plan 的 DAG 最大并行度为 3（Batch 4: T04/T05/T06 和 Batch 5: T07/T08/T09 都是 3 路并行）。`ralph suggest` 输出的 `estimated_parallelism` 字段是 informational only，foreman 没有利用它来决定 worker 数量。

**根因**：foreman prompt/guide 中没有"根据 `ralph suggest` 的 estimated_parallelism 创建对应数量 worker"的指引。`agent_pool.py` 的 AgentPoolManager 支持动态创建 worker（无上限），但 foreman 在规划阶段就固定了 2 个。

**需要**：
1. foreman-capability-guide 增加指引："运行 `ralph suggest` 后，根据 estimated_parallelism 创建至少该数量的 worker"
2. 或者 workflow engine 在 auto-dispatch 时自动按需创建 worker——当 batch 中任务数超过现有空闲 worker 时，调用 agent_pool 创建新 worker

#### FL-40（**P1** 模型选择全链路断裂——5 个断点导致 agent_pool 系统完全失效）

v42 所有 worker 全用 `--runtime claude`，agent_pool 的自动选模型系统完全没被调用。问题不是单个环节，而是 5 个断点叠加导致整个设计意图落空。

**系统代码实际状态**：agent_pool + select_model_for_task + ModelRegistry + ForemanWorkflow + agent 自动创建——**代码全部实现且通过测试**。但在实际 E2E 中没有一个环节被执行。

**5 个断点：**

| # | 断点 | 位置 | 影响 |
|---|------|------|------|
| 1 | Foreman 用 `--assignment-map` 绕过 agent_pool | `assignment_batches.py:211-212` — `suggestion.assignments` 非空时直接走 `_build_explicit_assignment_result()`，不调 `foreman.process_batch_suggestion()` | agent_pool 评分/创建逻辑完全跳过 |
| 2 | 全局 registry 的 `strengths` 字段全部为空 | `~/.cccc/.cccc/models/registry.yaml` — 7 个模型无一填充 strengths | 即使走 agent_pool，`select_model_for_task()` 所有模型得分=0，退化为随机选择 |
| 3 | `description` 有评价但 `select_model_for_task()` 不读 | `agent_ops.py:464` — 只匹配 `model.strengths`，不用 `model.description` | 用户写的丰富评价（"综合能力强,逻辑思维强"）完全浪费 |
| 4 | `foreman_rating` 从未被填充 | 所有模型 `foreman_rating=None` | agent_pool 评分中 rating bonus=0，评价反馈循环断裂 |
| 5 | workspace registry 不继承全局 registry | `/tmp/cccc-e2e-v42/.cccc/models/registry.yaml` 只有 1 个模型 | agent_pool 在 workspace 中看不到 codex/gemini |

**预期设计 vs 当前现实：**

```
预期流程：
  Foreman 决定需要的 agent 角色
    → agent_pool 根据 registry 建议每个 agent 的 runtime
      → Foreman 根据评价信息审核建议，做最终决策
        → 任务分配系统自动分发
        
当前现实：
  Foreman 手动 cccc actor add worker-1 --runtime claude
  Foreman 手动 cccc actor add worker-2 --runtime claude
  Foreman 传 --assignment-map → 完全绕过 agent_pool
```

**修复路径（按依赖顺序）：**

1. **registry 数据完善**（断点 2/3）— 填充所有模型的 `strengths`/`weaknesses` 结构化字段；或让 `select_model_for_task()` 同时参考 `description`（LLM 解析或关键词匹配）
2. **workspace registry 继承**（断点 5）— `cccc attach` 或 flow step-1 workspace 准备时，自动从全局 registry 复制/链接到 workspace
3. **foreman 引导不传 assignment-map**（断点 1）— E2E 模板和 foreman guide 引导 foreman 只提交 `cccc workflow submit --plan plan.yaml`（不传 `--assignment-map`），让 auto-dispatch 走 `foreman.process_batch_suggestion()` → agent_pool 路径
4. **评价反馈循环**（断点 4）— 在 `workflow.task_reported_completed` 事件中自动调用 `record_model_usage()`（函数已存在但从未被调用），任务完成后触发 `request_model_review()` 让 foreman 评分

### v42 E2E agent 架构缺陷

#### FL-41（**P1** Foreman 只创建"执行者" agent——缺少 reviewer/fixer 等多视角角色）

v42 foreman 创建了 2 个 worker，角色定义仅为"backend core"和"tests"，本质是同质化的执行者。没有创建 reviewer（代码审查）、bug fixer（缺陷修复）、security auditor（安全审计）等角色。这导致整个工作流是"写完就交"的单向流程，缺少真实团队中的交叉审查和多维度质量保障。

**对比真实团队**：一个 tech lead 不会只派 2 个 coder 写完代码就交付——会安排人 review、有人专门跑安全扫描、有人负责集成测试。Foreman 应该像真正的 tech lead 一样思考"这个项目需要哪些角色"，而不仅仅是"我要几个人写代码"。

**当前 agent_pool 的能力支持**：
- `role_type` 枚举已支持 `"worker" | "reviewer" | "specialist"`
- `create_agent_for_task()` 可以生成任意 worker_prompt
- `task_affinity` 可以标记 agent 的专长
- 但 foreman 不知道应该创建这些角色，因为 guide 和模板都只提到 "创建 Worker actor"

**需要**：
1. **foreman guide 增加"团队组建"指引**——明确列出可选角色及适用场景：executor（执行）、reviewer（审查关键路径的代码质量和安全）、fixer（验证失败后专门修复）、integrator（跨模块集成测试）
2. **plan.yaml 增加 `recommended_roles` 字段**——ralph suggest 根据 critical_flows/forbidden_flows 自动建议"建议为安全关键路径增加 reviewer agent"
3. **Foreman 规划阶段主动评估**——"11 个任务中有 security tests 和 XSS 防护需求，应该创建一个 security-reviewer agent 专门审查安全实现"

#### FL-42（评价系统需扩展为"评价+复盘+优化"闭环——含 E2E flow 步骤变更）

当前 `foreman_rating` 字段和 `record_model_usage()` 函数存在但从未被调用。即使接通了评分，也只是一个数字——缺少复盘和基于复盘的 agent prompt 优化。

**预期闭环**：

```
任务完成
  → 自动记录 model usage（调用 record_model_usage）
  → 触发 foreman 评分（1-5 分 + 文字评价）
  → 触发复盘（retrospective）：
      ① 对 agent prompt 的优化——"这个 worker 在处理 async 代码时犯了重复错误，应在 prompt 中增加 async 最佳实践提醒"
      ② 对团队组成的反思——"如果当时多创建一个 reviewer agent 对 FTS5 实现做交叉检查，就不会出现 unicode61 假通过的问题"
      ③ 将优化后的 prompt 写回 agent YAML（复用），将团队反思写入 foreman 知识库（下次参考）
  → 下一轮 E2E 时 foreman 参考历史复盘决策
```

**E2E flow 步骤变更**（`flow_steps_e2e.py`）：

当前 8 步（0-7）：code-verify → env-prepare → task-submit → monitor-wait → review → report-synthesize → improvement-register → cleanup

改为 9 步（0-8），在 improvement-register 和 cleanup 之间插入 retrospective：

```
Step 7 (new): agent-retrospective — Agent 复盘与优化
  指令：
    1. Foreman 对每个 agent 评分（cccc model rate）并记录评价
    2. 复盘 agent prompt 效果——哪些提示词帮助了任务完成、哪些导致了错误
    3. 复盘团队组成——是否缺少 reviewer/fixer/auditor 角色、是否需要为下次创建新 agent
    4. 将 prompt 优化建议写入 .ralph-flow/step-7-retrospective/
    5. 将优化后的 agent prompt 写回 .cccc/agents/*.yaml
  Check：
    - retrospective 目录下有产出文件
    - 至少覆盖 2 个 agent 的评价
    - foreman_rating 已更新到 registry
Step 8: cleanup（原 step 7）
```

同时 step 2 模板的"执行阶段"需更新：
- "1. 创建 Worker actor（按需选择 runtime）" → 增加角色多样性指引和 registry 参考
- 增加"不要传 --assignment-map，让 agent_pool 自动分配"的指引

**需要**：
1. **record_model_usage() 接入 workflow.task_reported_completed 事件**（代码存在未调用）
2. **任务完成后自动触发 foreman 评分请求**（request_model_review 已实现，需接入事件）
3. **flow_steps_e2e.py 新增 step 7 retrospective**——含 check 函数验证复盘产出
4. **step 2 模板更新**——agent 角色指引 + runtime 选择 + 不传 assignment-map
5. **优化后的 agent prompt 写回 .cccc/agents/*.yaml**——下次 create_or_reuse_agent 时直接复用

#### FL-43（模型描述需从 description 自然语言升级为结构化 strengths/weaknesses）

全局 registry（`~/.cccc/.cccc/models/registry.yaml`）中已有用户对模型的自然语言评价（description），但 `select_model_for_task()` 只读 `strengths` 字段（全部为空），导致评价信息完全浪费。

**当前用户评价（已存在于 description 但未被系统使用）**：

| 模型 | 用户评价 | 适用场景 |
|------|---------|---------|
| claude-opus-4-6 | 综合能力最强但偏贵，实现细节不如 gpt-5.4 | 方案讨论、复杂判断、指令遵循/工具调用、审美/前端 |
| codex-gpt-5.4 | 综合能力强，逻辑/debug 能力强 | 方案制定、漏洞发现、高复杂度执行、代码审查 |
| codex-gpt-5.3-codex | 比 5.4 弱但快 | 中等复杂度执行 |
| gemini-3-flash-preview | 速度快成本低，基础能力尚可，前端审美不错 | 代码库检索、低复杂度多 agent 并发 |
| gemini-3.1-pro-preview | 前端审美强 | UI 设计参考、前端审美问题 |

**需要**：
1. **将 description 中的评价提取为结构化 strengths/weaknesses**——可以手动填充，也可以让 LLM 从 description 自动提取
2. **select_model_for_task() 同时参考 description**——当 strengths 为空时 fallback 到 description 关键词匹配
3. **foreman 向 guide 注入模型选择参考**——把 registry 的模型对比表注入 foreman prompt，使其在创建 agent 时能做 informed decision
4. **定期由用户更新 description**——模型能力随版本变化，description 是最灵活的更新方式

### v41 E2E 新发现

> 已完成（v45 代码修复 + v42 E2E 验证）：RO-108/RO-109/RO-110/RO-111/FL-27/FL-28 — 详见 full tracker 归档

---

## 后续方向

### AgentFlow 整合（与 FL-38~43 大改关联）

> 源码：`/Users/vfch/Downloads/agentflow-master`
> 定位：多 agent 工作流编排框架（DAG 调度 + 可插拔 agent adapter + 多目标执行 + trace 收集 + agent 进化）

**CCCC 与 AgentFlow 核心概念对照：**

| CCCC 当前 | AgentFlow 对应 | 差距/整合点 |
|-----------|---------------|------------|
| Foreman（手动编排） | Orchestrator（async DAG 调度） | AF 的调度器更成熟：并发控制、retry backoff、取消/重跑、fanout/merge |
| Worker（同质化 claude actor） | Agent Adapter（codex/claude/kimi + 自定义） | AF 的 adapter 模式天然支持多 runtime，CCCC 缺这层抽象 |
| plan.yaml（ralph validate） | PipelineSpec（NodeSpec DAG） | 可共存：ralph 验证意图层，AF 验证执行层 |
| assignment-map（静态映射） | 无（调度器直接按 DAG 分派） | AF 不需要预分配，节点到达时按 agent kind 路由 |
| agent_pool（评分选模型，未激活） | ProviderConfig + model override | AF 每个 node 可独立指定 model/provider，更灵活 |
| 无 | Fanout/Merge 模式 | AF 原生支持：一个任务展开为 N 个并行节点 + 合并 |
| 无 | Jinja2 prompt 模板 + 上下文传递 | AF 节点可引用上游输出 `{{ nodes.plan.output }}`，CCCC 靠消息传递 |
| 无 | Success Criteria（output_contains/regex/file_exists） | AF 节点自带验收条件，对应 CCCC 的 verification.checks |
| 无 | Trace 收集 + NormalizedTraceEvent | AF 实时解析 agent stdout，CCCC 没有结构化 trace |
| 无 | TunedAgentVersion（agent 进化） | AF 从历史 trace 训练优化 agent，对应 FL-42 的复盘→优化需求 |
| 无 | Runner（local/ssh/ec2/ecs/container） | AF 支持远程执行，CCCC 仅本地 pty |

**整合策略：选择性合入（已确定）**

优先保留 CCCC 自有架构和前述设计思路（foreman 决定 agent 角色 → agent_pool 建议模型 → foreman 根据评价判断 → 任务系统自动分发）。AF 作为优化方向参考，选择性合入功能模块，不做整体替换。

**选择性合入清单（按优先级）：**

| 优先级 | AF 模块 | 合入目标 | 对应 FL |
|--------|---------|---------|---------|
| P1 | Agent Adapter 模式（`agents/base.py`, `agents/registry.py`） | 替换 CCCC 硬编码 pty runner，让 agent_pool 能按 adapter 路由到 codex/claude/gemini | FL-40 |
| P1 | Trace 收集（`NormalizedTraceEvent` + agent 输出解析） | 给 CCCC 增加结构化 trace，支撑复盘系统和 foreman 对 agent 表现的评估 | FL-42 |
| P2 | Success Criteria（`success.py`） | 与 CCCC verification.checks 对齐，统一验收标准定义 | FL-30 |
| P2 | Iterative Cycle（`on_failure_restart` 回边） | 让 verification 失败的任务自动重试，减少 foreman override | FL-38 |
| P3 | Jinja2 Prompt 模板（`context.py`） | 替换 CCCC 当前消息传递方式，支持 `{{ nodes.plan.output }}` 引用上游产出 | — |
| P3 | Fanout/Merge 模式（`specs.py` fanout 展开） | 参考设计，增强 ralph suggest 的并行批次能力 | FL-39 |
| 待评估 | TunedAgentVersion（agent 进化） | 从历史 trace 训练优化 agent prompt/配置，长期方向 | FL-42 |
| 待评估 | Runner 抽象（local/ssh/ec2） | 远程执行能力，与 Modal 集成方案可能重叠 | — |

### Modal 集成（待调研）

将 Modal 集成到 CCCC 系统中。具体集成方案和优先级待后续讨论确定。
