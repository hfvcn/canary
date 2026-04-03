# CCCC 工作流实战流程规范

> 版本：v1.0（2026-04-02）
> 来源：v1/v2 两轮实战经验提炼
> 用途：后续每轮实战按此规范执行（启动→运行→审查→评估→改进），保证可比性

---

## 〇、目标

验证 CCCC 工作流系统在真实项目中的端到端效果。评估对象不是项目本身，而是**工作流系统帮助 Foreman 完成项目的能力**。

---

## 一、评估框架：三维度独立审查

每轮实战从三个独立维度审查，分别由不同审查者（Codex）执行，互相交叉验证。

### 1.1 结果指标 — 产出物质量

**审查者**：Codex（对抗式代码审查）

**审查什么**：最终交付的项目代码是否可工作、是否有真实 bug。

**审查方法**：
- 逐文件静态审查：后端路由/模型/schema、前端组件/API/类型、测试、构建脚本
- 可执行验证：`tsc --noEmit`、`pytest`、`npm run build`（沙箱允许时）
- 最小复现：对可疑逻辑构造反例验证是否真的会坏

**报告格式**：
```
CRITICAL: [文件:行号] 问题描述 + 复现路径
WARN:     [文件:行号] 问题描述 + 影响范围
OK:       [审查区域] 未发现问题
```

**评分标准**：
| 分数 | 含义 |
|------|------|
| 5/5 | 0 CRITICAL, ≤2 WARN, 有测试且覆盖核心场景 |
| 4/5 | 0 CRITICAL, 有 WARN 但不影响主流程, 有测试 |
| 3/5 | ≤1 CRITICAL（非主流程）或无测试但代码基本可用 |
| 2/5 | 有 CRITICAL 影响主流程，或无测试 |
| 1/5 | 多个 CRITICAL，项目不可用 |

**为什么需要这个维度**：
工作流的最终价值体现在产出物质量上。无论过程多完美，如果代码有 CRITICAL bug，工作流就没有达到目的。

> **v1 实例**：外键约束未启用（CRITICAL），可创建指向不存在 board 的 column。verify gate 跳过，此 bug 完全未被拦截。
> **v2 实例**：删除任务后 position 不重排（CRITICAL），拖拽排序在删除后失效。虽然 plan.yaml 声明了 verification.checks，但 checks 未传递到引擎，verify gate 同样跳过。

### 1.2 过程指标 — 工作流机制遵守度

**审查者**：Codex（工作流日志分析）

**审查什么**：工作流各机制是否按设计运行。

**数据源**：`cccc tail --group GROUP_ID -n 500` 导出的 ledger 全文。

**必检项**（逐项给出"有证据/无证据"判定）：

| # | 检查项 | 证据来源 |
|---|--------|----------|
| 1 | Foreman 是否在提交前执行 `ralph validate` | ledger 中有无 validate 相关事件或 Foreman 消息 |
| 2 | 是否按 `ralph suggest` 分批提交 | batch_registered 事件数量和时间间隔 |
| 3 | claimed_paths 是否精确（非 `"/"`） | workflow.task_registered 事件中的 claimed_paths 字段 |
| 4 | verification.checks 是否在 engine 运行时执行 | verification_passed 事件中 checks 是否非空、outcome 是否非 skipped |
| 5 | depends_on 是否被引擎强制执行 | 有依赖的任务是否在依赖完成前就变成 running |
| 6 | 任务是否分配给正确的 worker | batch_approved 中 assignment 与任务类型是否匹配 |
| 7 | Worker 是否使用 `cccc task complete` | task_reported_completed 事件是否存在 |
| 8 | 有无卡死/失败/重试事件 | ledger 中有无 failed/timeout/stalled 事件 |
| 9 | 自动化比例（自动闭环的任务数 / 总任务数） | 综合判断 |
| 10 | plan.yaml 元数据是否传递到 engine 运行时 | 对比 plan.yaml 内容与 task_registered 事件内容 |

**评分标准**：
| 分数 | 含义 |
|------|------|
| 5/5 | 全部 10 项有正面证据 |
| 4/5 | 8-9 项正面，无 P0 级机制失效 |
| 3/5 | 6-7 项正面，或有 1 个 P0 级失效但有 workaround |
| 2/5 | 4-5 项正面，有多个机制失效 |
| 1/5 | ≤3 项正面，核心机制（verify/depends_on/dispatch）全部失效 |

**为什么需要这个维度**：
Foreman 的主观反馈可能有遗漏或美化。日志是客观的——事件要么发生了要么没发生，时间戳不会说谎。

> **v1 实例**：Foreman 没提到 claimed_paths 全是 `"/"`，但日志分析发现所有 task_registered 事件的 claimed_paths 都是 `["/"]`，直接解释了为什么 Ralph 无法做并行调度优化。
> **v2 实例**：Foreman 声称"validated by ralph (0 errors)"，但日志中无 validate 执行痕迹——要么是在 CLI 中执行但未产生 ledger 事件（设计缺陷），要么是 Foreman 虚报（可靠性问题）。
> **v2 实例**：plan.yaml 有精确 claimed_paths，但 task_registered 事件中变成空数组。这揭示了"计划层 vs 执行层断裂"的根因——`cccc workflow submit` 的 JSON 格式没有传递 plan.yaml 的结构化字段。

### 1.3 体验指标 — Foreman 实践反馈

**审查者**：Foreman 自身（WORKFLOW_EVALUATION.md）

**审查什么**：Foreman 作为工作流的唯一使用者，使用过程中的实际体验。

**要求 Foreman 在任务完成后输出 WORKFLOW_EVALUATION.md，必须包含**：

1. **正面反馈**：哪些机制帮上了忙，具体在哪个环节
2. **负面反馈**：哪些机制没按预期工作，被迫用什么 workaround
3. **手工干预记录**：哪些步骤是 Foreman 手工完成的（应该由引擎自动完成）
4. **Worker 可靠性评估**：每个 runtime 的完成率和表现
5. **自评分 + 改进建议**

**评分标准**：
| 分数 | 含义 |
|------|------|
| 5/5 | Foreman 反馈全正面，无手工干预，工作流"透明"到 Foreman 不需要考虑它 |
| 4/5 | 少量手工干预（<20%），主要机制有正面反馈 |
| 3/5 | 中等手工干预（20-50%），核心机制有正面反馈 |
| 2/5 | 大量手工干预（50-80%），Foreman 抱怨多于肯定 |
| 1/5 | Foreman 基本在手工编排，工作流形同虚设 |

**为什么需要这个维度**：
日志告诉你"发生了什么"，但不告诉你"这个体验好不好"。Foreman 是这套工具的唯一用户，它的主观感受直接决定工作流是否值得使用。而且 Foreman 能发现日志分析不易察觉的体验问题——比如"批次门控过严"这个问题，日志上只显示 deferred 状态，但 Foreman 能解释这导致了多大的摩擦。

> **v1 实例**：Foreman 自评 2.5/5，核心抱怨是"状态追踪可用，执行自动化缺失"——它发现自己 80% 在手工中继消息。
> **v2 实例**：Foreman 最正面的反馈给了 ralph validate（"caught a real issue before execution"），最负面的给了 batch 门控（"rigid, should be dependency-aware, not batch-aware"）。这条反馈直接指导了 P0 改进方向。
> **v2 实例**：Foreman 报告 Codex worker "stalled silently, 0/1 tasks"。这是日志分析也能看到的（T2 长时间无进展），但 Foreman 补充了关键细节："无超时、无错误、无进度报告，只能人工判断"——直接说明了 stall detection 机制的缺失。

---

## 二、实战流程（启动→运行→审查→评估→改进）

### Phase 1：环境准备

```bash
# 变量
VERSION=vN                              # 本轮版本号
PROJECT_DIR=/tmp/cccc-e2e-${VERSION}
CCCC_ROOT=/path/to/cccc-main-git        # CCCC 源码目录

# 1. 创建隔离的测试项目
mkdir -p ${PROJECT_DIR}/docs && cd ${PROJECT_DIR} && git init

# 2. 复制文档到项目目录（Foreman 的 scope 是项目目录，只能读项目内文件）
cp ${CCCC_ROOT}/todo/ralph-foreman-workflow.md  ${PROJECT_DIR}/docs/
cp ${CCCC_ROOT}/todo/findings.md                ${PROJECT_DIR}/docs/
cp ${CCCC_ROOT}/todo/e2e-实战评估规范.md          ${PROJECT_DIR}/docs/  # 本文件
# + 能力指南（如有更新）

# 3. 生成能力指南（反映当前代码状态，而非旧文档）
# → 见 Phase 2 的模板，能力指南内容嵌入在 Foreman 任务提示词中

# 4. 启动 daemon + 创建 group + 添加 Foreman
cccc daemon start
cccc attach ${PROJECT_DIR}
cccc use <GROUP_ID>
cccc actor add planner --title "Foreman-${VERSION}" --runtime claude --scope ${PROJECT_DIR}
```

**检查清单**（进入 Phase 2 前确认）：
- [ ] daemon running
- [ ] group created + attached
- [ ] Foreman actor running
- [ ] docs/ 目录包含最新版文档（不是旧版）
- [ ] 文档版本与当前代码一致（不含已完成但文档未更新的能力）

> **v1 教训**：发送了 `docs/ralph-foreman-workflow.md`（3/25 旧版）而非 `todo/` 下的更新版，且 Foreman scope 是空项目目录读不到任何文档。v2 改为复制到项目目录内解决。

### Phase 2：任务下发

使用以下标准化提示词模板。**每轮实战必须使用同一模板**，仅替换 `{{变量}}` 部分，确保可比性。

```bash
cccc send --to planner --group <GROUP_ID> "$(cat <<'TASK_EOF'
# 实战任务：{{项目名称}}

## 项目要求
在 {{PROJECT_DIR}} 中实现{{项目描述}}。

## 必读文档（已放在项目目录中）
1. **docs/foreman-capability-guide.md** — 最新能力指南
2. **docs/ralph-foreman-workflow.md** — 工作流架构参考
3. **docs/findings.md** — 实践教训

**请先阅读文档，再开始规划。**

## 工作流强制要求

### 计划阶段
1. 写 plan.yaml，包含所有任务
2. claimed_paths 精确到文件/目录（不要用 "/"）
3. 用 depends_on 表达真实依赖，用 provides/consumes 声明契约
4. 每个任务必须有 verification.checks[]（至少 compile + test 两步）
5. 声明 critical_flows
6. 运行 `ralph validate plan.yaml --project-root .` 直到 0 error
7. 用 `ralph suggest plan.yaml` 查看可并行批次

### 执行阶段
1. 创建 Worker actor（按需选择 runtime：claude/codex/gemini）
2. 按 ralph suggest 的批次分批提交（cccc workflow submit）
3. {{已知限制说明}}
4. Worker 完成后使用 cccc task complete TASK_ID --changed-file PATH
5. 每批完成后重新 ralph suggest，提交下一批
6. 用 ralph verify plan.yaml --task TASK_ID 验证任务

### 验收标准
{{项目具体验收标准}}

### 完成后
输出 WORKFLOW_EVALUATION.md，包含：
1. 正面反馈：哪些机制帮上了忙
2. 负面反馈：哪些机制没按预期工作，被迫用什么 workaround
3. 手工干预记录：哪些步骤应该自动但实际手工完成
4. Worker 可靠性：每个 runtime 的完成率
5. 评分 + 改进建议
TASK_EOF
)"
```

**模板变量说明**：

| 变量 | 说明 | 示例 |
|------|------|------|
| `{{项目名称}}` | 简短项目名 | 全栈看板项目 |
| `{{PROJECT_DIR}}` | 项目目录绝对路径 | /tmp/cccc-e2e-v3 |
| `{{项目描述}}` | 一句话描述项目 | 一个任务管理看板（FastAPI 后端 + React 前端） |
| `{{已知限制说明}}` | 当前版本的已知限制 | "引擎不自动下发任务，需手工发送" 或 "引擎已支持自动下发" |
| `{{项目具体验收标准}}` | 可测试的验收条件 | "backend: CRUD + move endpoint; frontend: drag-and-drop; 有测试" |

> **为什么用模板**：v1 和 v2 的提示词差异很大（v1 没有"已知限制说明"，v2 加了能力指南），导致无法精确归因改进效果是来自代码修复还是提示词优化。模板固定后，每轮差异仅来自 `{{已知限制说明}}` 的更新和文档内容的更新。

### Phase 3：监控运行

Foreman 接收任务后自主运行，人工不干预。通过以下命令监控：

```bash
# 查看最新消息
cccc tail --group <GROUP_ID> -n 20

# 查看工作流进度
cccc workflow status --group <GROUP_ID>

# 查看 actor 状态
cccc actor list --group <GROUP_ID>

# 跟踪实时输出
cccc tail --group <GROUP_ID> -f
```

**完成判定**：当 workflow status 显示所有任务 completed 或 Foreman 发出"完成"消息时，进入 Phase 4。

### Phase 4：三维度审查

**并行启动 3 个独立审查**，审查者之间不共享信息：

```bash
# 0. 导出日志
cccc tail --group <GROUP_ID> -n 500 > ${PROJECT_DIR}-ledger.txt

# 1. 结果指标：Codex 对抗式代码审查
codex_bridge.py --cd ${PROJECT_DIR} --sandbox read-only \
  --PROMPT "对抗式代码审查... [见 1.1 节审查方法]"

# 2. 过程指标：Codex 工作流日志分析
codex_bridge.py --cd ${CCCC_ROOT} --sandbox read-only \
  --PROMPT "分析工作流日志 ${PROJECT_DIR}-ledger.txt... [见 1.2 节必检项]"

# 3. 体验指标：读取 Foreman 的 WORKFLOW_EVALUATION.md
cat ${PROJECT_DIR}/WORKFLOW_EVALUATION.md
```

### Phase 5：报告合成

综合三个维度 + 交叉验证，输出最终评估报告。

**输出文件**：`todo/e2e-实战评估报告-vN.md`

**报告结构**：

```markdown
# CCCC 实战评估报告 vN

> 日期 / Workflow ID / 总耗时 / 任务数

## 评分摘要
| 维度 | 分数 | 关键发现 |
|------|------|----------|

## 一、结果指标（X/5）
  ### CRITICAL / WARN / OK 列表

## 二、过程指标（X/5）
  ### 10 项必检结果

## 三、体验指标（X/5）
  ### Foreman 反馈摘要

## 四、交叉验证
  ### 维度间不一致的解释

## 五、与上一版对比（vN vs vN-1）
  ### 逐项变化 + 归因

## 六、根因定位
  ### 已解决 / 未解决 / 新发现

## 七、后续改进及对应实例
  ### 新增 FIX 条目（按格式）

## 八、综合评分：X/5
```

### Phase 6：改进登记

将本轮发现的新问题登记为改进条目（格式见第四节），更新版本历史评分表（第五节）。

**改进→重测循环**：完成改进后回到 Phase 1 启动下一轮实战。

---

## 三、交叉验证规则

三个维度的结论必须互相一致，不一致时需要解释原因：

| 场景 | 处理方式 |
|------|----------|
| 结果好 + 过程差 | 说明：代码质量靠 Foreman/Worker 自身能力，不是工作流保障的 |
| 结果差 + 过程好 | 说明：工作流机制运行正常但未能拦住质量问题（verify 规则不够强） |
| 体验好 + 过程差 | 说明：Foreman 可能美化了体验，以日志证据为准 |
| 体验差 + 过程好 | 说明：机制在运行但体验有摩擦（如 batch 门控过严） |

> **v2 实例**：Foreman 声称"6/6 tasks completed and verified by ralph"（体验好），但日志显示 verification 全部 skipped（过程差）。交叉验证暴露了 Foreman 的汇报不实——verify gate 没有真正运行，Foreman 把 worker 口头证据当成了 Ralph 验证证据。

---

## 四、后续改进追踪

每条改进必须关联到具体的实战实例，说明"为什么要改"和"改了之后预期在哪个维度上看到分数提升"。

### 改进登记格式

```markdown
### [改进编号] 改进标题

**优先级**：P0/P1/P2
**影响维度**：结果 / 过程 / 体验
**预期分数变化**：过程 2→4, 体验 2→3

**触发实例**：
> vN 实战中，[具体现象]。日志证据：[event_id/时间戳]。
> Foreman 反馈："[原文引用]"。

**根因**：[为什么会出现这个问题]

**改进方案**：[具体做什么]

**验收标准**：下一轮实战中，[具体可观测的变化]
```

### 当前改进清单（基于 v1+v2 实战）

---

#### [FIX-1] plan→engine 元数据传递

**优先级**：P0
**影响维度**：过程 + 体验
**预期分数变化**：过程 2→3, 体验 3→4

**触发实例**：
> v2 实战中，plan.yaml 声明 `claimed_paths: ["backend/"]`，但 workflow.task_registered 事件中 claimed_paths 变成空数组 `[]`。同样，`verification.checks` 在 plan.yaml 中有 compile+test 两步，但 verification_passed 事件显示 `overall_outcome: "skipped", checks: []`。
> Foreman 反馈："All 6 tasks passed ralph verification" — 实际是 skipped 被误认为 passed。

**根因**：`cccc workflow submit` 接受的 JSON batch 格式与 plan.yaml 的 TaskSpec 格式不同。submit 只传递 id/title/type/depends_on/claimed_paths 等基础字段，不传递 verification.checks、provides/consumes、goal_behavior 等扩展字段。

**改进方案**：修改 workflow submit 的 TaskRef 解析逻辑，从 plan.yaml 中提取 verification spec 并传递给 engine。或直接支持 `cccc workflow submit --plan plan.yaml` 模式，让 engine 直接读取 plan 文件。

**验收标准**：下一轮实战中，task_registered 事件的 claimed_paths 非空且与 plan.yaml 一致；verification_passed 事件的 checks 非空且包含 compile/test 结果。

---

#### [FIX-2] 引擎自动下发任务给 Worker

**优先级**：P0
**影响维度**：过程 + 体验
**预期分数变化**：过程 2→4, 体验 3→4

**触发实例**：
> v1 实战中，5 个任务全部由 Foreman 手工通过 `cccc send` 转发给 Worker。v2 同样如此，6 个任务的说明全部由 Foreman 手工撰写并发送。
> v1 Foreman 反馈："Workers received no messages in their inbox after workflow submission. The foreman had to manually send task descriptions via cccc send."
> v2 Foreman 反馈："The engine does not auto-dispatch task instructions to workers."

**根因**：WorkflowOrchestrator.process_batch_suggestion() 中的 _start_assigned_agents() 只创建 agent actor 并标记为 running，但不向 worker inbox 发送任务描述。

**改进方案**：在 _start_assigned_agents() 中，创建 actor 后自动发送任务 prompt（包含 goal_behavior、acceptance_criteria、claimed_paths、verification 信息）到 worker inbox。

**验收标准**：下一轮实战中，Foreman 不需要手工 `cccc send` 任务描述。Worker inbox 在 task 被分配后自动收到结构化任务说明。自动化比例从 ~17% 提升到 ≥60%。

---

#### [FIX-3] 改 batch 门控为 DAG 门控

**优先级**：P0
**影响维度**：过程 + 体验
**预期分数变化**：过程 2→3, 体验 3→4

**触发实例**：
> v2 实战中，T3（CRUD routers）依赖 T1（backend scaffold），T1 在 ~90s 内完成。但 T3 被 batch 边界阻塞（T2 还在 Codex 上卡着），Foreman 不得不绕过引擎直接发任务。
> v2 Foreman 反馈："The batch gating logic should be dependency-aware, not batch-aware. A task should become eligible when its actual consumes dependencies are satisfied, regardless of whether other unrelated tasks in the previous batch are still running."

**根因**：WorkflowOrchestrator 按 batch 整体判断完成，而非按单任务依赖关系判断 readiness。一个 batch 中的任何任务未完成，整个下一批都被阻塞。

**改进方案**：batch_completed 检查改为 per-task readiness 检查。当一个任务完成时，检查它解锁了哪些下游任务（depends_on 全部满足 + claimed_paths 无冲突），立即将它们标记为 ready 并分配。

**验收标准**：下一轮实战中，T1 完成后 T3 立即变为 ready（不等 T2），deferred 任务数为 0。

---

#### [FIX-4] Codex worker 超时 + stall detection

**优先级**：P1
**影响维度**：过程 + 体验
**预期分数变化**：过程 +0.5, 体验 +0.5

**触发实例**：
> v2 实战中，Codex worker 在 T2（前端 scaffold）上卡死 5+ 分钟，无超时、无错误消息、无进度报告。Foreman 只能人工判断并重新分配。
> v2 Foreman 反馈："Silent failures are worse than loud failures — there was no timeout, no error, no partial status. A worker health-check or timeout mechanism is needed."

**根因**：orchestrator.check_stalled_tasks() 已实现但未在自动化循环中定期触发。且 Codex runtime 不发 heartbeat，所以 last_heartbeat 永远是 null。

**改进方案**：在 automation engine 的 heartbeat sweep 中，对 running 任务检查 last_heartbeat。超过阈值（如 300s 无 heartbeat）标记为 stalled 并通知 Foreman。

**验收标准**：下一轮实战中，worker 卡死 5 分钟内触发 stalled 告警，Foreman 收到通知并可决定重试/重分配。

---

#### [FIX-5] verification_passed 事件语义修正

**优先级**：P1
**影响维度**：过程
**预期分数变化**：过程 +0.5

**触发实例**：
> v2 日志分析发现所有 verification_passed 事件的内容是 `overall_outcome: "skipped", checks: []`。事件名叫 "passed" 但内容是 "skipped"，语义矛盾。
> 交叉验证时发现 Foreman 声称"all tasks verified by ralph"——它把 skipped 误读为 passed，因为事件名就叫 verification_passed。

**根因**：workflow engine 对 verification 结果的事件命名没有区分 passed/skipped/failed，统一发 verification_passed。

**改进方案**：当 outcome 为 skipped 时，事件类型改为 verification_skipped；当 outcome 为 failed 时，事件类型改为 verification_failed。

**验收标准**：下一轮实战中，skipped verification 不会产生 verification_passed 事件。

---

## 五、版本历史评分追踪

每轮实战的综合评分记录在此，观测改进趋势。

| 版本 | 日期 | 结果 | 过程 | 体验 | 综合 | 关键改进 |
|------|------|------|------|------|------|----------|
| v1 | 2026-04-01 | 2/5 | 1/5 | 2.5/5 | 1.8/5 | 基线 |
| v2 | 2026-04-02 | 3/5 | 2/5 | 3/5 | 2.7/5 | +文档指引 +能力指南 |
| v3 | 2026-04-02 | 3/5 | 3/5 | 3/5 | 3.0/5 | +WF-1 metadata +WF-4 --plan +WF-6 warning |
| v4 | 2026-04-03 | 2/5 | 4/5 | 4/5 | 3.3/5 | +FIX-8 auto-dispatch +FIX-6 DAG gating +FIX-10 path scoring |
| v5 | — | — | — | — | — | 待执行：FIX-12 FK + verification 质量提升 |
