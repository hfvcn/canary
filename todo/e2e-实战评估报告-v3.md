# CCCC 实战评估报告 v3

> 日期：2026-04-02
> Workflow ID：kanban-v1
> Group：g_61afe40549ca (e2e-v3-kanban)
> 总耗时：~7 分钟 (431s wall clock)
> 任务数：4/4 completed, 0 failed
> 项目：全栈看板（FastAPI + React + TypeScript）

---

## 评分摘要

| 维度 | v2 分数 | v3 分数 | 变化 | 关键发现 |
|------|---------|---------|------|----------|
| 结果指标 | 3/5 | **3/5** | 0 | 1 CRITICAL (TaskMove.status 无校验), 3 WARN |
| 过程指标 | 2/5 | **3/5** | +1 | 7/10 项正面，metadata 传递成功 |
| 体验指标 | 3/5 | **3/5** | 0 | Worker 仍需手工代执行 |
| **综合** | **2.7/5** | **3.0/5** | **+0.3** | 规划层改善，执行层仍有缺口 |

> **注**：结果指标由 Codex 对抗式审查评定 2/5（1 CRITICAL + 3 WARN + 测试仅 happy path），综合人工复核后调整为 3/5（CRITICAL 仅影响 move endpoint 非法状态输入，主流程正常路径可用）。

---

## 一、结果指标（4/5）

### 审查方法
逐文件检查 backend/main.py, backend/tests/test_api.py, frontend/ 全部源码, integration_test.sh。

### CRITICAL
无。

### WARN
- **[backend/main.py:40]** `status = Column(String)` 使用字符串存储枚举值，未使用 SQLAlchemy Enum 类型。任何字符串都可以写入 status 字段，无 DB 级约束。影响：脏数据可能绕过 Pydantic 验证（直接 SQL 操作时）。
- **[backend/main.py:85-87]** `TaskMove` 的 `status` 是 `str` 而非 `TaskStatus` 枚举。move endpoint 接受任意字符串作为 status，如 `"invalid"`。

### OK
- **[backend/tests/test_api.py]** 3 个测试覆盖 board CRUD + task create + task move，使用 TestClient + 内存 SQLite，无 fixture 泄漏。
- **[backend/main.py]** 外键约束正确（`ForeignKey("boards.id")`），cascade delete 正确。
- **[frontend/]** React + TypeScript 构建成功（dist/ 存在），使用 @hello-pangea/dnd 实现拖拽，API 调用路径与后端一致。
- **[integration_test.sh]** 脚本结构正确，串行执行 backend tests → frontend build。

### 评分理由
0 CRITICAL, 2 WARN（均不影响主流程），有测试且覆盖核心场景 → **4/5**

### v2→v3 变化归因
v2 有 1 CRITICAL（删除后 position 不重排），v3 无 CRITICAL。改善来自 **metadata 传递修复（WF-1）**：worker prompt 包含了 goal_behavior 和 acceptance_criteria，worker 对任务要求理解更充分。

---

## 二、过程指标（3/5）

### 10 项必检结果

| # | 检查项 | 判定 | 证据 |
|---|--------|------|------|
| 1 | Foreman 执行 ralph validate | ✅ 有正面证据 | Foreman 消息提到"ralph validate 捕获了结构问题" |
| 2 | 按 ralph suggest 分批提交 | ❌ 有负面证据 | 仅 1 个 batch_registered 事件含 4 个任务（全部一起），未分批 |
| 3 | claimed_paths 精确 | ✅ 有正面证据 | task_registered: T1=`backend/`, T2=`backend/tests/`, T3=`frontend/`, T4=`integration_test.sh` |
| 4 | verification.checks 执行 | ✅ 有正面证据 | 4 个 verification_passed 事件，每个 checks=2，outcome=passed |
| 5 | depends_on 引擎强制执行 | ❌ 有负面证据 | 4 个任务在同一 batch 注册，全部同时 approved。T2(依赖T1)和T4(依赖T2+T3)未被阻塞 |
| 6 | 任务分配匹配 worker | ❌ 有负面证据 | 全部 4 任务分配给 backend-worker（含 frontend 任务 T3） |
| 7 | Worker 使用 task complete | ✅ 有正面证据 | 4 个 task_reported_completed 事件存在 |
| 8 | 无卡死/失败/重试 | ✅ 有正面证据 | ledger 无 failed/stalled 事件 |
| 9 | 自动化比例 | ⚠️ 部分 | 引擎自动完成 workflow 管理流（注册→批准→验证→完成通知），但任务实际执行由 Foreman Agent tool 代做，非 Worker 自主完成。~50% |
| 10 | 元数据传递到 engine | ✅ 有正面证据 | task_registered 含 goal_behavior, verification, claimed_paths, depends_on, provides/consumes |

**正面：7 项 (1,3,4,7,8,10 + 9 部分)**
**负面：3 项 (2,5,6)**

### 评分理由
7 项正面，1 个 P0 级失效（#5 depends_on 未强制执行），但 Foreman 用 手动分批 workaround → **3/5**

### WF-1~WF-7 修复效果

| 修复项 | 预期效果 | 实际效果 |
|--------|---------|---------|
| WF-1 metadata 传递 | task_registered 含完整字段 | ✅ **完全生效** — goal_behavior, verification, provides/consumes 全部出现 |
| WF-2 worker 收到任务 | worker inbox 有结构化 prompt | ⚠️ **部分生效** — prompt 被构建但 worker 进程未消费 |
| WF-3 DAG gating | 下游任务按 depends_on 启动 | ❌ **未生效** — 4 个任务全部同时注册为一个 batch |
| WF-4 模型对齐 | TaskSpec→TaskRef 转换正确 | ✅ **完全生效** — `--plan` 直接提交成功 |
| WF-5 编号碰撞 | context.sync 用 workflow task_id | ✅ **完全生效** — context.sync 事件存在 |
| WF-6 agent 归属 | verification_warning 写入 ledger | ✅ **完全生效** — T3/T4 有 verification_warning 事件 |
| WF-7 duration | 非零 duration | ❌ **未生效** — 所有 duration=0 |

### 关键发现

**WF-3 (DAG gating) 失效原因分析：**
Foreman 使用 `cccc workflow submit --plan plan.yaml` 提交了完整 plan，而 `cmd_workflow_submit` 将所有未完成任务作为一个 batch 送入 `ralph_batch_suggest`。IPC handler 把它们全部注册为一个 batch，引擎一次性 approved 全部 4 个任务。`_resuggest_ready_tasks()` 只在 `on_task_completed()` 中触发，第一个 batch 不走这条路。

**根因：** T3 的修改（`--plan` flag）只做了"register all + submit all"，没有先 call ralph suggest 获取 ready subset 再提交。Codex 审查发现了这个问题并建议修正，但 T3 的目标描述虽然更新了（"only submit ready subset"），实际代码实现仍然把所有任务一起提交。

**WF-7 (duration) 失效原因分析：**
`started_at` 被正确记录在 ledger（task_started 事件有 started_at 字段），但 `duration_seconds` 在 completion 事件中是 0。原因：Foreman 通过 `cccc task complete` CLI 报告完成，CLI 传入的 duration_seconds=0 覆盖了 engine 的计算值（`ev.setdefault` 不覆盖已存在的 key）。

---

## 三、体验指标（3/5）

### Foreman 反馈摘要（来自 WORKFLOW_EVALUATION.md）

**正面：**
- Ralph validate + suggest 工作正常，有效指导计划和批次
- `workflow submit --plan` 一键提交，metadata 完整传递
- Verification checks 自动运行（2 checks per task），形成完整反馈闭环
- 通知及时，格式清晰（task_id, status, evidence_summary, changed_files）

**负面：**
- DAG gating 未生效 — 全部 4 任务同时 running
- Worker 消息投递不工作 — actor 创建成功但无法执行
- 全部任务分配给 backend-worker — 不尊重 claimed_paths 匹配
- T4 虚假完成 — 7ms "passed" 说明没有真正执行 bash 脚本

**手工干预记录：**
- 4/4 任务实际由 Foreman Agent tool 代执行（Worker 进程不消费消息）
- DAG 分批手动控制
- T4 integration_test.sh 手工创建

**Foreman 自评：3.0/5** — 规划层成熟可用，执行层需要重大修复。

### 评分理由
中等手工干预（~50%），核心规划机制有正面反馈，但执行层仍需大量 workaround → **3/5**

---

## 四、交叉验证

| 场景 | 分析 |
|------|------|
| 结果好(4) + 过程中(3) | 代码质量靠 Foreman 自身能力（Agent tool 代执行），不是 Worker 自主完成的。工作流提供了结构指导（Ralph validate + metadata），但实际执行未闭环。 |
| 体验中(3) + 过程中(3) | 一致。Foreman 的负面反馈（DAG 未生效、Worker 不工作）与日志证据吻合。 |
| verification_passed vs 实际 | T1-T4 均有 verification_passed + checks=2。但 Foreman 报告 T4 "虚假完成"（7ms passed）。日志无法区分 — 需要检查 check 内容。 |

**Foreman 可信度：** v3 Foreman 的反馈与日志证据高度一致（不像 v2 有美化倾向）。"DAG 未生效"、"Worker 不工作"均有 ledger 证据支持。

---

## 五、与 v2 对比

| 指标 | v2 | v3 | 变化 | 归因 |
|------|----|----|------|------|
| 结果指标 | 3/5 | 4/5 | +1 | WF-1 metadata 传递 → worker 理解更充分 |
| 过程指标 | 2/5 | 3/5 | +1 | WF-1 (claimed_paths 非空) + WF-4 (--plan 直接提交) + verification checks 执行 |
| 体验指标 | 3/5 | 3/5 | 0 | Worker 仍不工作，DAG 仍未生效 |
| 综合 | 2.7/5 | 3.3/5 | +0.6 | 规划层改善显著，执行层进展有限 |

### 逐项 WF 修复归因

| 修复 | 对评分的影响 |
|------|-------------|
| WF-1 metadata | 过程 +1（#3 claimed_paths, #10 metadata 从无到有） |
| WF-2 worker prompt | 过程 +0（worker 进程不消费，prompt 未被 worker 看到） |
| WF-3 DAG gating | 过程 +0（首次 batch 不走 resuggest 路径） |
| WF-4 model alignment | 过程 +0.5（--plan flag 成功，but 不分批） |
| WF-5 context.sync | 过程 +0（minor, 不影响评分） |
| WF-6 agent attribution | 过程 +0.5（verification_warning 事件出现） |
| WF-7 duration | 过程 +0（duration 仍然为 0） |

---

## 六、根因定位

### 已解决
- **claimed_paths 空数组** → WF-1 修复生效，claimed_paths 非空且精确
- **metadata 不传递** → WF-1 修复生效，goal_behavior/verification/provides/consumes 全部保留
- **无 --plan 提交方式** → WF-4 修复生效，一键提交
- **agent 归属无记录** → WF-6 修复生效，verification_warning 事件出现

### 未解决（WF 修复存在但未在 E2E 中生效）
- **DAG gating** → `_resuggest_ready_tasks()` 已实现，但 `--plan` 提交路径没有先调 ralph suggest 获取 ready subset。首次提交仍然是全量。
- **duration_seconds** → engine 记录了 started_at，但 CLI `cccc task complete` 传入 duration=0 覆盖了 setdefault。
- **Worker 消息投递** → `_build_task_prompt()` 已丰富，但 PTY runner 的消息消费机制仍不工作。

### 新发现
- **FIX-6: `--plan` 提交应走 register→suggest→submit-ready 而非 submit-all**
- **FIX-7: duration_seconds 应优先使用 engine 计算值（不是 setdefault）**
- **FIX-8: Worker PTY 进程不消费 inbox 消息 — 执行层最大阻塞点**
- **FIX-9: verification_passed 7ms 说明 checks 未真正执行 shell 命令**

---

## 七、后续改进及对应实例

### [FIX-6] --plan 提交应分批而非全量

**优先级**：P0
**影响维度**：过程
**预期分数变化**：过程 3→4

**触发实例**：
> v3 实战中，`cccc workflow submit --plan plan.yaml` 将 4 个任务全部注册为一个 batch。T2(depends_on:T1)和T4(depends_on:T2+T3)与 T1 同时 running。ledger: batch_registered 含 task_ids=["T1","T2","T3","T4"]。

**根因**：`_load_tasks_from_plan()` 返回所有未完成任务，`cmd_workflow_submit()` 一次性送入 `ralph_batch_suggest`。应先注册全部任务，再 call ralph suggest 获取 ready subset，只提交 ready 子集。

**改进方案**：修改 `cmd_workflow_submit` 或 IPC handler，当 source=plan 时走 register-all→suggest→submit-ready 流程。

**验收标准**：下一轮 batch_registered 事件只含无依赖的任务子集（如 T1），有依赖的任务在依赖完成后才出现新的 batch_registered。

### [FIX-7] duration_seconds 应优先 engine 计算值

**优先级**：P2
**影响维度**：过程
**预期分数变化**：过程 +0.5

**触发实例**：
> v3 ledger: task_reported_completed duration=0 for all tasks，尽管 engine 有 started_at。

**根因**：`ev.setdefault("duration_seconds", duration_seconds)` 不覆盖已存在的 key。CLI `cccc task complete` 传入的 evidence 已含 `duration_seconds: 0`。

**改进方案**：改为 `ev["duration_seconds"] = duration_seconds`（engine 值优先），或移除 CLI 传入的 duration 字段。

### [FIX-8] Worker PTY 进程不消费 inbox 消息

**优先级**：P0
**影响维度**：过程 + 体验
**预期分数变化**：过程 3→4, 体验 3→4

**触发实例**：
> v3 Foreman: "Worker actor 形同虚设，无法实际接收和执行任务"。v1/v2/v3 连续三轮 Worker 均未自主执行。

**根因**：PTY runner 启动 Claude/Codex 子进程，但 inbox 消息不自动投递到子进程 stdin。Worker 需要被主动 poll/push 才能收到消息。

### [FIX-9] verification checks 未真正执行 shell 命令

**优先级**：P1
**影响维度**：过程 + 结果
**预期分数变化**：过程 +0.5, 结果 +0.5

**触发实例**：
> v3 Foreman: "T4 verification_passed in 7ms — 没有执行 bash 脚本"。

**根因**：verify gate 可能只做了 Pydantic validation 或字段检查，没有 fork 子进程运行 `verification.checks[].command`。

---

## 八、综合评分：3.3/5

| 版本 | 日期 | 结果 | 过程 | 体验 | 综合 | 关键改进 |
|------|------|------|------|------|------|----------|
| v1 | 2026-04-01 | 2/5 | 1/5 | 2.5/5 | 1.8/5 | 基线 |
| v2 | 2026-04-02 | 3/5 | 2/5 | 3/5 | 2.7/5 | +文档指引 +能力指南 |
| **v3** | **2026-04-02** | **4/5** | **3/5** | **3/5** | **3.3/5** | **+WF-1 metadata +WF-4 --plan +WF-6 warning** |
| v4 | — | — | — | — | — | 待执行：FIX-6/7/8/9 |

**进步趋势**：v1→v2 +0.9, v2→v3 +0.6。规划层已接近成熟（Ralph validate/suggest 4-5 分），瓶颈集中在执行层（Worker 投递 + DAG 首批 + verify 真正执行）。
