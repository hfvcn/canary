# CCCC Workflow Issues

Source: Kanban Board full-stack project stress test + CCCC source code analysis.

---

## 1. Workflow Tab (全为 0 / "no recent event")

### BUG-01 [CRITICAL] Workflow Progress API 缺少 project_root 参数

- **位置**: `src/cccc/ports/web/routes/workflow.py:170-182`
- **现象**: `/api/v1/groups/{group_id}/workflow/progress` 路由没有传递 `project_root` 给 daemon
- **原因**: `get_orchestrator(group_id)` 在 `_ORCHESTRATORS` 缓存中找不到时，若 `project_root is None` 直接返回 `None`，handler 返回 `orchestrator_not_found` 错误
- **对比**: `_try_process_batch()` 正确传递了 `project_root=Path(project_root)`
- **修复**: 从 group scope 配置中提取 project_root 传入 args

### BUG-02 [HIGH] 后端返回结构与前端 TypeScript 接口不匹配

- **位置**: `src/cccc/daemon/foreman/workflow_orchestrator.py:635-658`
- **现象**: `get_workflow_state()` 把数据包在嵌套的 `"progress"` 字段里
- **原因**: 后端返回 `{"workflow_id": "...", "progress": {...}, "active": true}`，前端 `WorkflowProgress` 接口期望 `status/tasks/duration/recent_events` 在顶层
- **修复**: 将 progress 字段解构到顶层返回，或前端解包 `resp.result.progress`

### BUG-03 [HIGH] Orchestrator 不存在时返回 error 而非 idle 状态

- **位置**: `src/cccc/daemon/ralph_ipc_handler.py:643-671`
- **现象**: 没有 Ralph daemon 运行时，orchestrator 不会被初始化，前端轮询拿到错误响应
- **修复**: 返回完整的 idle 状态结构体（所有计数为 0，recent_events 为空数组）

### BUG-04 [MEDIUM] summarize_progress() idle 返回缺少必要字段

- **位置**: `src/cccc/daemon/foreman/progress_report.py:171-205`
- **现象**: 无活跃工作流时只返回 `{"status": "idle", "message": "No active workflow"}`，缺少前端需要的 `batches/tasks/duration/recent_events/assignments`
- **修复**: 返回完整结构，所有数值字段为 0，数组字段为空

### BUG-05 [MEDIUM] 工作流端点零测试覆盖

- **位置**: `tests/`
- **现象**: `handle_ralph_workflow_progress()`、workflow progress 路由、整个数据管线无任何测试用例

---

## 2. 前端看板功能 (Board Tab 不显示)

### KB-BUG-01 [CRITICAL] AppShell 缺少 Board/Workspace/Panorama 标签页渲染逻辑

- **位置**: `web/src/components/app/AppShell.tsx:249-331`
- **现象**: 点击 Board 按钮，activeTab 变为 "board"，但内容区空白
- **原因**: AppShell 只有 chat/actor/workflow 的渲染分支，缺少 board/workspace/panorama
- **根因**: 似乎是一次重构中将 tab 架构迁移到 AppShell，但遗漏了三个 tab 的渲染逻辑
- **修复**: 在 AppShell 中添加 `activeTab === "board"` / `"workspace"` / `"panorama"` 渲染分支

### KB-BUG-02 [CRITICAL] BoardTab 组件从未接收到数据

- **位置**: `web/src/pages/BoardTab.tsx:6-11`
- **现象**: BoardTab 需要 `tasks/loading/isDark/onOpenTask` 四个 props，但 AppShell 没有提供
- **原因**: AppShell 中没有获取 tasks 数据的逻辑，没有创建 onOpenTask handler
- **修复**: 从 `useWorkspaceStore` 提取 tasks 数据传入 BoardTab

### KB-BUG-03 [HIGH] 数据管线完整但最后一环断裂

- **数据流**:
  - `✓ 后端: /api/v1/groups/{id}/workspace/tasks` → 返回任务数据
  - `✓ API 层: fetchWorkspaceTasks()` → 正确调用后端
  - `✓ Store: useWorkspaceStore.loadTasks()` → 加载并存储任务
  - `✗ App.tsx`: 从未将 tasks 传递给任何组件
  - `✗ AppShell`: 没有 board tab 的渲染代码
  - `✗ BoardTab`: 永远收不到 tasks prop

### KB-BUG-04 [MEDIUM] WorkspaceTaskInfo 类型不完整

- **位置**: `web/src/types.ts:587-594`
- **现象**: 只有 `title/status/task_ref/id/assignee/updated_at`，缺少 `outcome/blocked_by/parent_id/priority/waiting_on/checklist`

### KB-BUG-05 [LOW] BoardTab 无拖拽功能

- **位置**: `web/src/pages/BoardTab.tsx:70-83`
- **现象**: 任务卡片是 `<button>` 元素，没有 dnd-kit 集成（虽然已安装 @dnd-kit）

---

## 3. 多 Agent 协作工作流

### WF-01 [CRITICAL] 被 stop 的 Actor 可自动恢复

- **现象**: Foreman stop frontend-worker (codex) 后，它在 ~2.5 分钟后自动恢复为 enabled: true, running: true，继续执行并覆盖了已验收的代码
- **影响**: Foreman 对 Actor 生命周期的控制权被削弱，stop 不是终态
- **建议**: stop 应设置持久化标记阻止自动恢复，或提供 `force_stop` / `kill` 操作

### WF-02 [CRITICAL] 无文件锁/工作区隔离机制

- **现象**: backend-worker 和 frontend-worker 同时修改 `client/` 目录，codex worker 覆盖了已验收实现
- **影响**: 多 Worker 共享文件系统无冲突检测，后写入者覆盖先写入者
- **建议**: 每个 Worker 在独立 git branch 或 worktree 中工作，合并由 Foreman 控制

### WF-03 [HIGH] 并行 Worker 竞态条件

- **现象**: 前端 worker (codex) 在后端 worker 还在写代码时读取后端文件，看到不完整状态（只有 boards.js，缺 columns.js/cards.js/index.js），判定后端不完整而停滞
- **影响**: 有依赖关系的任务不应无条件并行
- **建议**: Ralph 的 batch 机制应强制按依赖图排序；Foreman 手动分配时也应遵循此原则

### WF-04 [HIGH] Worker 沉默失败无兜底

- **现象**: Codex worker 遇到 blocker 后既不上报也不继续，Foreman 只能通过轮询文件系统间接发现
- **影响**: Foreman 监控完全依赖 Worker 主动汇报，无被动检测机制
- **建议**: 实现 heartbeat 超时机制；Worker 超过 N 秒无活动自动标记为 stalled

### WF-05 [HIGH] Foreman 无法 reassign task

- **现象**: `cccc_task update` 设置 `assignee` 字段报 "peer cannot reassign task"，即使调用者是 foreman
- **影响**: Foreman 无法在 task 系统中正式跟踪任务归属
- **修复**: 权限检查应对 foreman role 放行 reassign 操作

### WF-06 [HIGH] Foreman 无法 remove Actor

- **现象**: `cccc_actor remove` 报 "foreman can only remove self"
- **影响**: 停止的 Worker 永久残留在列表中，无法清理
- **修复**: 允许 foreman 删除非活跃 actor

### WF-07 [MEDIUM] Foreman 未查 Model Registry 即分配模型 (流程引导不足)

- **现象**: System prompt 要求 "inspect model registry before assigning"，但 bootstrap 未将此标记为必需步骤
- **模型注册表内容**:
  - `claude-opus-4-6`: 适合讨论方案（Foreman）
  - `codex/gpt-5.4`: 逻辑强、debug 强，适合高复杂度任务（后端）
  - `gemini-3-flash`: 前端审美好、速度快、成本低（前端）
- **建议**: bootstrap 返回 model registry 摘要或列为 required next_call；`cccc_actor add` 时提示是否已查看 registry

### WF-08 [MEDIUM] 不同 Runtime Agent 行为差异大

- **现象**: Claude 直接写代码；Codex 先走内部流程（AGENTS.md → taskmaster → fast-context → 逐个读文件）
- **影响**: 统一的 Foreman task prompt 对不同 runtime 效果差异很大
- **建议**: task prompt 应针对不同 runtime 适配，或在 worker_prompt 中设置 runtime-specific 指令

### WF-09 [MEDIUM] capability_use activation_pending 状态误导

- **现象**: `pack:group-runtime` 启用后返回 `activation_pending` + `wait: relist_or_reconnect`，但工具实际已可用
- **影响**: 状态语义不清

### WF-10 [LOW] Ralph 观察层在实际运行中完全缺席

- **现象**: Git 监控、依赖图计算、ReadyBatchSuggestion、VerificationResult 等 Ralph 层功能未触发
- **影响**: Foreman 需手动完成 Ralph 的所有职责


# CCCC Workflow Fix Plan 

> 基于 `todo/workflow-issues.md` 问题清单和 `docs/ralph-foreman-workflow.md` 架构设计。


## 0. 共同根因分析

三类问题背后的共同模式是 **"状态模型分裂 + 契约漂移"**：

1. **数据管线断裂**（第一类）：重构后 workflow/progress 路由丢失 `project_root` 参数，返回结构嵌套了多余的 `progress` 层，前端期望的扁平结构与后端不匹配。
2. **UI 渲染遗漏**（第二类）：Tab 架构迁移到 AppShell 时遗漏了 board/workspace/panorama 的渲染分支。数据管线（后端→API→Store）完整但最后一环（组件接线）断裂。
3. **Actor 状态模型混用**（第三类）：`enabled` 字段同时承载"用户期望状态"、"自动恢复决策"、"调度控制"三种语义。权限模型面向"人机聊天"而非"调度控制面"。调度层缺少执行约束模型（依赖、文件作用域、heartbeat）。

### 伴随 bug（新发现）

`workflow/task/completed` HTTP 路由当前只转发到 `ralph_actor_status`，后者仅写入 `_RALPH_STATE["actor_statuses"]`，**不会调用** `orchestrator.on_task_completed()`。这导致即使数据管线修通，workflow UI 中的任务状态也可能永远停在 `running/pending`。

---

## 1. 方案决策记录

### 1.1 WF-01 止血：Actor Hold 机制

**选定方案：A1 — `hold_reason` 枚举字段，持久化到 Actor model**

```python
# contracts/v1/actor.py — Actor model
hold_reason: Literal["", "manual_stop", "policy_hold"] = ""
```

- **持久化位置**：`group.yaml`（与 enabled/runtime/runner 同层）
- **理由**：
  - 需要跨 daemon 重启存活
  - `group_start` 在 daemon 启动最早阶段就需要检查
  - 语义上是 actor 期望状态，不是运行时瞬态
- **否决 A2**（stopped_by_foreman 标记）：语义是"谁停的"而非"应不应该恢复"，会继续把策略塞进杂项字段
- **否决 A3**（调度层拦截）：auto_wake 在 `chat_support_ops.py` 直接调用 `update_actor(enabled=true)` + `start_actor_process()`，orchestrator 根本拦不住已启动的进程

**实现规则**：
- `actor.stop` → `enabled=false` + `hold_reason="manual_stop"`
- `actor.start/restart` → 清除 `hold_reason`
- `auto_wake_recipients()`、`group_start`、所有自动 restart 路径 → 检查 `hold_reason`，非空则跳过并记日志
- UI 显式展示 hold 状态，不静默
- 第一版不需 `hold_by/hold_at`，审计走 ledger 事件

### 1.2 WF-02 止血：文件写入安全

**选定方案：短期 B1 (single_writer) → 中期 B2 (claimed_paths)**

**Wave 2 — Single Writer 安全模式**：
- 执行粒度：`WorkflowOrchestrator.process_batch_suggestion` / decision 阶段
- 同组同 repo 同一时间只批准一个可写 worker
- 未批准的任务标为 `deferred`（理由 `single_writer_active`），不伪装成失败
- 这是策略层决策，不塞进 `AgentPoolManager`（它负责"能给谁"，不是"该不该并发"）

**Wave 3 — Claimed Paths**：
- `TaskRef` 增加 `claimed_paths: List[str]` 可选字段（Wave 2 先加字段但不强依赖）
- Orchestrator admission control 从"全局单写者"升级为"claimed_paths 冲突检测"
- 上层接口不需推倒重来

**否决 B3**（Git worktree 隔离）：长期最干净，但改动涉及 cwd、文件采用、验证、合并、冲突呈现全链路，当前阶段复杂度不划算。

### 1.3 WF-04：Heartbeat 超时

**选定方案：A+C — Worker 上报 + Orchestrator 超时策略**

- **A（任务级 heartbeat）**：Worker 通过现有 `cccc_agent_state` 更新 `last_progress_at`
  - 多个事件刷新 heartbeat：`agent_state update`、显式 progress ping、completion/failure 回写
  - 不把责任全压在 worker prompt 自觉性上
- **C（超时策略）**：Orchestrator 维护 `task_started_at / last_progress_at`
  - 超过阈值标为 **`stalled`**（新状态，不复用 `failed`，区分"执行报错"和"超时失联"）
  - 释放 assignment，通知 Foreman

**否决 B**（被动检测 runner 输出）：只能证明"进程有输出"，不能证明"任务在推进"。CLI 运行时长时间静默思考是正常的，误判面太大。

### 1.4 WF-05/WF-06：权限模型

**选定方案：C2 — 引入系统调度身份**

- Orchestrator/Foreman 调度操作以 `by="system"` 身份执行
- 审计日志记录 `requested_by=foreman_id` + `reason=workflow_scheduler`
- 不修改 actor 权限矩阵（不把 foreman actor 变成高权限主体）
- 当前代码已默认 `system/user` 是调度身份（`context_ops.py:907`），保留此分层

**否决 C1**（直接扩权限矩阵）：会把 foreman 变成高权限主体，控制面/互动面的边界会越来越糊。

### 1.5 伴随 bug：Task Completed/Failed 回写

**选定方案：新增 Daemon Op**

新增：
- `ralph_task_completed`
- `ralph_task_failed`

每个 op 统一做三件事：
1. 找 orchestrator → 调用 `on_task_completed()` / `on_task_failed()`
2. 同步更新 `_RALPH_STATE`（保留 actor status 视图）
3. 返回规范化 workflow progress delta

Web route 只做薄转发，给未来非 HTTP 调用留入口。

---

## 2. 修复波次

### Wave 1 — 可观测面（修好数据管线）

**目标**：让 Workflow Tab 能显示真实状态，为后续验收提供可信观测。

| 编号 | 修复项 | 改动文件 | 改动要点 |
|------|--------|----------|----------|
| BUG-01 | workflow/progress 缺 project_root | `ports/web/routes/workflow.py:170` | 从 group active scope 解析 project_root，传入 ralph_workflow_progress args |
| BUG-01b | handler 获取 orchestrator | `daemon/ralph_ipc_handler.py:643` | `get_orchestrator(group_id, project_root=...)` |
| BUG-02 | 返回结构嵌套 progress | `daemon/foreman/workflow_orchestrator.py:635` | 返回扁平结构：`status/workflow_id/batches/tasks/duration/recent_events/assignments/active` |
| BUG-03 | 无 orchestrator 返回 error | `daemon/ralph_ipc_handler.py:663` | 返回完整 idle payload（`active=false, reason="no_active_orchestrator"`），不返回 error |
| BUG-04 | idle 返回缺少字段 | `daemon/foreman/progress_report.py:182` | idle 分支补齐：batches/tasks/duration/recent_events/assignments 所有零值字段 |
| 伴随 | task completed/failed 不回写 orchestrator | `daemon/ralph_ipc_handler.py` (新增) | 新增 `ralph_task_completed` / `ralph_task_failed` daemon op；web route 改为薄转发 |

### Wave 1.5 — Board Tab 接线（可与 Wave 1 并行）

**目标**：前端接线回归修复，提升可见性和验收效率。

| 编号 | 修复项 | 改动文件 | 改动要点 |
|------|--------|----------|----------|
| KB-BUG-01 | AppShell 缺渲染分支 | `web/src/components/app/AppShell.tsx:319` | 补 `board/workspace/panorama` 渲染分支，继续 lazy/suspense |
| KB-BUG-02 | BoardTab 没收到 props | `web/src/components/app/AppShell.tsx` + `App.tsx` | AppShellProps 增加 workspace 相关 props，App.tsx 传入 |
| KB-BUG-03 | 数据管线最后一环断裂 | `web/src/App.tsx:335-388` | 从 `useWorkspaceStore` 取 tasks 传给 BoardTab；复用现有 `handleOpenWorkspaceFile()` |

### Wave 2 — 止血（防止多 Agent 相互破坏）

**目标**：停止的 Actor 不会复活、并发写不会互踩、卡死的 Worker 能被发现。

| 编号 | 修复项 | 改动文件 | 改动要点 |
|------|--------|----------|----------|
| WF-01 | Actor hold 机制 | `contracts/v1/actor.py`<br>`kernel/actors.py`<br>`daemon/actors/actor_lifecycle_ops.py`<br>`daemon/messaging/chat_support_ops.py`<br>`daemon/group/group_lifecycle_ops.py`<br>`web/src/types.ts`（Actor 类型加 hold_reason） | 见 §1.1。UI 必须显式展示 hold 状态，`group_start`/auto-wake 结果带 `skipped_held` |
| WF-02 | Single writer 安全模式 | `daemon/foreman/workflow_orchestrator.py` | orchestrator decision 层拦截，同一时间只批准一个可写 worker，其余 deferred。**前提**：在 claimed_paths 落地前，所有 workflow task 默认视为"可写"，吞吐会进一步下降但换取正确性 |
| WF-04 | Heartbeat 超时 | `daemon/foreman/workflow_orchestrator.py`<br>`daemon/foreman/progress_report.py`（stalled 状态）<br>`daemon/automation/engine.py`（timeout sweep 触发器）<br>`ports/im/templates/progress_card.py`（stalled 卡片）<br>`web/src/services/api.ts`（状态类型）<br>`web/src/stores/useWorkflowStore.ts`（状态类型）<br>`web/src/components/WorkflowActivityBar.tsx`（stalled UI） | 见 §1.3。`stalled` 是 assignment/task execution status，不是 Ralph ActorStatusType。**后台触发器**：挂到 `daemon/automation/engine.py` 周期任务，不依赖前端轮询 |

### Wave 3 — 治理（权限与调度优化）

**目标**：Foreman 拿到完整的调度控制权，任务按依赖执行，文件冲突检测精细化。

| 编号 | 修复项 | 改动文件 | 改动要点 |
|------|--------|----------|----------|
| WF-05/06 | 系统调度身份 | `daemon/foreman/workflow_orchestrator.py`<br>`daemon/context/context_ops.py`<br>`kernel/permissions.py`（审计增强 + `by="system"` 放行）<br>`daemon/actors/actor_membership_ops.py`（remove 入口）<br>`daemon/actors/actor_lifecycle_ops.py`（start/stop/restart 入口） | 见 §1.4。`require_actor_permission()` 当前不接受 `by="system"`，需要补充 |
| WF-03 | 依赖门控 | `contracts/v1/ralph_ipc.py`（TaskRef 加 depends_on）<br>`daemon/foreman/workflow_orchestrator.py` | 依赖未满足的任务不批准执行 |
| WF-02b | Claimed paths | `contracts/v1/ralph_ipc.py`（TaskRef 加 claimed_paths）<br>`daemon/foreman/workflow_orchestrator.py` | admission control 升级为 path 冲突检测 |

### 后续（Wave 4+）

| 编号 | 修复项 | 说明 |
|------|--------|------|
| WF-07 | Model Registry 强约束 | Registry 缺失时不回退硬编码，要求显式配置 |
| WF-08 | Runtime-specific task prompt | 不同 runtime 的 worker_prompt 适配 |
| WF-09 | capability_use activation_pending 语义 | 状态清理 |
| WF-10 | Ralph 观察层落地 | Git 监控、依赖图计算、验证等 |
| KB-BUG-04 | WorkspaceTaskInfo 类型补全 | 增加 outcome/blocked_by 等字段 |
| KB-BUG-05 | Board 拖拽 | dnd-kit 集成 |

---

## 3. 最小测试集

### Wave 1 测试

- [ ] `workflow/progress` 路由正确传递 `project_root` 到 daemon
- [ ] 无 orchestrator 时返回完整 `idle` 结构（不是 error），含 `active=false`
- [ ] `get_workflow_state()` 返回扁平 payload（无嵌套 `progress` 层）
- [ ] `ralph_task_completed` op 将 assignment 从 `running` 推进到 `completed`，写入 `duration_seconds/changed_files`
- [ ] `ralph_task_failed` op 将 assignment 推进到 `failed`
- [ ] 前端 `useWorkflowStore.refreshProgress()` 能正确读取扁平结构并更新 `assignments`

### Wave 1.5 测试

- [ ] `AppShell` 渲染 `board/workspace/panorama` 分支
- [ ] `BoardTab` 能收到 `tasks` prop 并展示
- [ ] 点击任务卡片能调用 `onOpenTask`

### Wave 2 测试

- [ ] `actor.stop` 设置 `hold_reason="manual_stop"` 且 `enabled=false`
- [ ] `auto_wake_recipients()` 遇到 held actor 不会 re-enable 也不会启动进程
- [ ] `group_start` 跳过 held actor
- [ ] `actor.start/restart` 清除 `hold_reason`
- [ ] single_writer 模式下同一批只批准一个可写任务，其余为 `deferred`（理由 `single_writer_active`）
- [ ] heartbeat 超时后任务变 `stalled`（非 `failed`），释放 assignment

### Wave 3 测试

- [ ] `by="system"` 身份可 reassign/remove，审计记录 `requested_by`
- [ ] 普通 foreman actor 身份仍不能越权
- [ ] 依赖未满足的任务不被批准执行
- [ ] `claimed_paths` 冲突时任务不同时批准

---

## 4. 风险评估

| 风险 | 说明 | 缓解措施 |
|------|------|----------|
| idle 掩盖真实问题 | `orchestrator_not_found` 改成 idle 可能静默吞掉错误 | 返回显式 `reason` 字段 + `active=false`，不伪装健康 |
| 扁平化破坏其他调用方 | workflow API 结构变化影响范围 | 当前主消费方就是前端，本身就期待扁平结构 |
| hold_reason 导致 "起不来" | 新状态如果 UI 不展示，用户会困惑 | 强制 UI 显式展示 hold 状态 |
| single_writer 降并行度 | 显著限制工作流吞吐 | 这是显式吞吐换正确性，短期合理代价 |
| heartbeat 误杀 | 阈值太短会误杀正常长时间思考的 worker | 按任务类型设超时；多事件刷新 heartbeat |
| system 身份扩权限面 | 如果管理不好，system 身份成为万能后门 | 审计日志 `requested_by` + `reason`；限定只在 orchestrator 调度路径使用 |
| 超时扫描依赖后台触发器 | 如果超时判断绑在 progress API 轮询上，系统正确性依赖 UI 在线 | daemon 侧周期任务独立 sweep，不依赖前端轮询 |
| single_writer 写能力判定缺失 | 在 claimed_paths 落地前，所有任务视为可写，吞吐进一步下降 | 短期可接受代价，文档明确标注 |
| held actor 不可见 | group_start/auto-wake 跳过 held actor 但用户看不出来 | 返回结果带 `skipped_held` 列表；UI 显式展示 hold 状态 |
| reportTaskCompleted 无调用者 | 仓库内未找到前端实际调用该 API 的代码 | 新 daemon op 作为唯一正确入口，不在 HTTP route 塞业务逻辑 |

---

## 5. 关键文件索引

```
修改面（按改动量排序）：
daemon/foreman/workflow_orchestrator.py  — Wave 1 + 2 + 3 核心 + 超时 sweep 触发器
daemon/ralph_ipc_handler.py              — Wave 1 新增 op + idle 返回
contracts/v1/actor.py                    — Wave 2 hold_reason 字段
contracts/v1/ralph_ipc.py                — Wave 3 TaskRef 扩展（depends_on + claimed_paths）
daemon/actors/actor_lifecycle_ops.py     — Wave 2 stop/start hold 逻辑 + Wave 3 system 身份入口
daemon/actors/actor_membership_ops.py    — Wave 3 system 身份 remove 入口
daemon/messaging/chat_support_ops.py     — Wave 2 auto_wake hold 检查
daemon/group/group_lifecycle_ops.py      — Wave 2 group_start hold 检查
daemon/foreman/progress_report.py        — Wave 1 idle 补全 + Wave 2 stalled 状态
ports/im/templates/progress_card.py      — Wave 2 stalled 飞书卡片
ports/web/routes/workflow.py             — Wave 1 project_root + 薄转发
daemon/context/context_ops.py            — Wave 3 system 身份放行
kernel/permissions.py                    — Wave 3 审计增强 + by="system" 放行
web/src/components/app/AppShell.tsx      — Wave 1.5 tab 渲染
web/src/App.tsx                          — Wave 1.5 props 传递
web/src/types.ts                         — Wave 2 Actor 类型 hold_reason
web/src/services/api.ts                  — Wave 2 stalled 状态类型
web/src/stores/useWorkflowStore.ts       — Wave 2 stalled 状态类型
web/src/components/WorkflowActivityBar.tsx — Wave 2 stalled UI 展示
kernel/actors.py                         — Wave 2 hold_reason 在 add/update 中处理
daemon/automation/engine.py              — Wave 2 heartbeat timeout sweep 触发器宿主（现有周期任务入口）
web/src/components/AgentTab.tsx          — Wave 2 hold 状态 badge 展示位（或 ActorTab）
```
