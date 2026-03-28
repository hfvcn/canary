# CCCC Workflow Fix Plan — 2026-03-26 (Rev.2)

> 由 Claude (Opus) 与 Codex (GPT-5.4) 协作分析，经三份独立审查 (gpp/gro/gedt) 后修订。
> 基于 `todo/workflow-issues.md` 问题清单和 `docs/ralph-foreman-workflow.md` 架构设计。

---

## 0. 共同根因分析

三类问题背后的共同模式是 **"状态模型分裂 + 契约漂移 + 控制面缺少单一事实源"**：

1. **数据管线断裂**（第一类）：重构后 workflow/progress 路由丢失 `project_root` 参数，返回结构嵌套了多余的 `progress` 层，前端期望的扁平结构与后端不匹配。各 route 分别解析 group context 导致遗漏易复发。
2. **UI 渲染遗漏**（第二类）：Tab 架构迁移到 AppShell 时遗漏了 board/workspace/panorama 的渲染分支。根因是 prop drilling 模式下重构时接线断裂。
3. **Actor 状态模型混用**（第三类）：`enabled` 字段同时承载"用户期望状态"、"自动恢复决策"、"调度控制"三种语义。权限模型面向"人机聊天"而非"调度控制面"。调度层缺少执行约束模型（依赖、文件作用域、heartbeat）。缺少 assignment_id/generation 导致迟到事件可覆盖新状态。

### 伴随 bug（新发现）

`workflow/task/completed` HTTP 路由当前只转发到 `ralph_actor_status`，后者仅写入 `_RALPH_STATE["actor_statuses"]`，**不会调用** `orchestrator.on_task_completed()`。

---

## 1. 方案决策记录

### 1.1 API 响应结构：kind + reason_code + snapshot

> 采纳自 gpp/gedt 审查。不把 `orchestrator_not_found` 伪装成 idle。

**Workflow Progress Response 统一结构**：

```json
{
  "kind": "idle | running | stalled | unavailable | error",
  "reason_code": "no_active_orchestrator | project_root_missing | ...",
  "snapshot": {
    "batches": {"total": 0, "completed": 0},
    "tasks": {"total": 0, "completed": 0, "failed": 0, "running": 0, "pending": 0},
    "duration": {"workflow_seconds": 0, "batch_seconds": 0},
    "recent_events": [],
    "assignments": []
  },
  "workflow_id": "",
  "active": false
}
```

- `snapshot` 保持固定 shape，前端永远只消费 snapshot，不会因字段缺失崩
- UI 按 `kind` 分流：`idle/unavailable/error` 走引导态，`running/stalled` 走统计面板
- 同时引入 `resolve_group_runtime_context(group_id)` 统一入口，所有 workflow route 从此获取 project_root/orchestrator/flags，避免各 route 分散解析

### 1.2 Task 事件入口：统一 ralph_task_event

> 采纳自 gpp 审查。替代原方案的分立 completed/failed op。

**新增统一 daemon op：`ralph_task_event`**

Wave 1 最小字段：
```python
{
    "event_type": "completed | failed",  # Wave 2+ 扩展 stalled/blocked/cancelled
    "task_id": str,
    "assignment_id": str,
    "actor_run_id": str,        # 防止迟到事件覆盖新 assignment
    "idempotency_key": str,
    "occurred_at": str,         # ISO timestamp
    "payload": {}               # event_type specific data (changed_files, error, etc.)
}
```

Orchestrator 内部 `apply_task_event()` 做：
1. 幂等去重（idempotency_key）
2. assignment 有效性检查（assignment_id + actor_run_id 匹配）
3. 状态迁移
4. snapshot 重建

**为什么不分立 op**：后续 stalled/blocked/cancelled/retry 都是事件流问题，不应为每种事件开新 op。assignment_id + actor_run_id 确保 stop 后旧 worker 的迟到 completed 不会覆盖新 assignment。

### 1.3 Actor Hold 机制：admin_hold

> 采纳审查建议，将 `hold_reason` 重命名为 `admin_hold`，与目标三层状态模型对齐。

**Wave 2 — admin_hold 字段**：

```python
# contracts/v1/actor.py — Actor model
admin_hold: Literal["none", "manual", "policy"] = "none"
```

- 持久化到 `group.yaml`（需要跨 daemon 重启存活）
- `actor.stop` → `enabled=false` + `admin_hold="manual"`
- `actor.start/restart` → 清除 `admin_hold` 为 `"none"`
- `auto_wake_recipients()`、`group_start`、所有自动 restart 路径 → 检查 `admin_hold != "none"` 则跳过并记日志
- UI 显式展示 hold 状态

**Wave 2 同步引入 run_id/generation**：

```python
# Actor 运行时状态（或 assignment 级）
run_id: int = 0  # 每次 start/restart 递增
```

- `ralph_task_event` 携带 `actor_run_id`，orchestrator 校验匹配
- stop 后旧进程的迟到上报被丢弃（run_id 不匹配）

**Wave 3+ — 完整三层状态（目标模型）**：
- `desired_state: running | stopped`
- `runtime_state: starting | running | stopping | stopped | crashed`
- `admin_hold: none | manual | policy`
- admin_hold 自然取代 Wave 2 的字段，无需再改名

### 1.4 文件写入安全：single_writer → claimed_paths + publish barrier → worktree

> 维持原方案路线，审查的 OCC/worktree 作为长期方向记录。

**Wave 2 — Single Writer 安全模式**：
- 执行粒度：`WorkflowOrchestrator.process_batch_suggestion` / decision 阶段
- 同组同 repo 同一时间只批准一个可写 worker
- 未批准的任务标为 `deferred`（理由 `single_writer_active`）
- 前提：在 claimed_paths 落地前，所有 workflow task 默认视为"可写"

**Wave 3 — Claimed Paths + Publish Barrier**：
- `TaskRef` 增加 `claimed_paths: List[str]`（Wave 2 先加字段但不强依赖）
- 与 `assignment_id/generation` 一起落地，publish barrier 不被旧 assignment 的迟到提交绕过
- Orchestrator admission control 从"全局单写者"升级为"claimed_paths 冲突检测"

**Wave 4+ — Git Worktree 隔离**：
- 高风险写任务启用临时 worktree / patch merge
- 长期 writer 全量 worktree 化

**否决近期采纳项**：
- OCC 乐观并发（gedt）：把正确性外包给模型的 diff 处理能力，不可靠
- Git worktree 作为止血方案（gro）：改动链路太长，不适合本周止血

### 1.5 Heartbeat：双时钟 + 被动 IO 探针

> 采纳 gpp/gedt 审查的双时钟方案和被动 IO 探针。

**双时钟模型**：
- `last_seen_at`：被动 IO 探针刷新 — daemon 的 tool executor 感知 worker 在调用工具即自动刷新
- `last_progress_at`：显式任务推进信号 — agent_state update、progress ping、task event 回写

**状态区分**：
- `blocked`：worker **显式声明**受阻（不靠超时推断）
- `stalled`：worker 还活着（last_seen_at 正常）但长期无进展（last_progress_at 超时）
- `offline`：连心跳都断了（last_seen_at 超时）
- `failed`：任务明确执行失败

**后台触发器**：daemon 侧周期任务（`automation/engine.py`），不依赖前端轮询。

**否决近期采纳项**：
- Poke 机制（gedt）：当前 runner 无干净的外部 prompt 注入通道
- 断路器（gedt）：好主意，适合后续迭代（Wave 3+）

### 1.6 权限模型：受限服务主体

> 采纳 gpp 审查方案。替代原方案的泛化 `by="system"`。

**短期实现**：`by="service:workflow_orchestrator"`
- `permissions.py` 对 `service:*` 前缀做专门处理
- 验证 `allowed_actions` + `scope(group_id/workflow_id)`
- 审计日志记录 `requested_by=foreman_id` + `reason=workflow_scheduler`

**长期目标**：结构化 principal（不是字符串协议）
```python
principal_type = "service"
principal_name = "workflow_orchestrator"
allowed_actions = ["reassign_task", "suspend_actor", "retire_actor"]
scope = "group/{group_id}"
```

**否决项**：
- 泛化 `by="system"`（原方案）：太容易变成万能后门
- 直接扩 actor 权限矩阵（C1）：foreman 会变成高权限主体

### 1.7 前端架构：Tab Registry + Store 直连

> 采纳 gpp/gedt 审查。替代原方案的 prop drilling。

**AppShell 退回纯壳层**：
- 不感知 tasks 的具体 shape，只感知"当前 tab 是谁"
- 每个 tab 自己做 container，从 store 直连

**Tab Registry 防回归**：
```typescript
const TAB_REGISTRY: Record<string, React.LazyExoticComponent<...>> = {
  chat: lazy(() => import('./pages/chat/ChatTab')),
  workflow: lazy(() => import('./pages/WorkflowTab')),
  board: lazy(() => import('./pages/BoardTabContainer')),
  workspace: lazy(() => import('./pages/WorkspaceTabContainer')),
  panorama: lazy(() => import('./pages/PanoramaTabContainer')),
  // actor tabs 走动态 registry
}
```

- 新增/重构 tab 只改 registry，不会再出现"按钮有了但渲染没接上"
- Wave 1.5 直接用 registry/container 模式实现，不走过渡的 prop drilling

---

## 2. 修复波次

### Wave 1 — 可观测面（修好数据管线）

**目标**：让 Workflow Tab 能显示真实状态，为后续验收提供可信观测。

| 编号 | 修复项 | 改动文件 | 改动要点 |
|------|--------|----------|----------|
| BUG-01 | workflow route 统一入口 | `ports/web/routes/workflow.py` | 新增 `resolve_group_runtime_context(group_id)` 统一获取 project_root/orchestrator/flags |
| BUG-01b | handler 获取 orchestrator | `daemon/ralph_ipc_handler.py:643` | `get_orchestrator(group_id, project_root=...)` |
| BUG-02/03/04 | API 响应结构 | `daemon/foreman/workflow_orchestrator.py:635`<br>`daemon/foreman/progress_report.py:182`<br>`daemon/ralph_ipc_handler.py:663` | 统一 `kind + reason_code + snapshot` 结构，idle/unavailable/error 各有语义 |
| 伴随 | 统一 task 事件入口 | `daemon/ralph_ipc_handler.py` (新增) | 新增 `ralph_task_event` daemon op（瘦版：completed/failed），带 assignment_id + actor_run_id + idempotency_key |

### Wave 1.5 — Board Tab 接线（可与 Wave 1 并行）

**目标**：前端架构修正 + 接线回归修复。

| 编号 | 修复项 | 改动文件 | 改动要点 |
|------|--------|----------|----------|
| KB-BUG-01~03 | Tab Registry + Container 模式 | `web/src/components/app/AppShell.tsx`<br>`web/src/App.tsx`<br>新增 `BoardTabContainer`/`WorkspaceTabContainer`/`PanoramaTabContainer` | AppShell 退回纯壳层 + Tab registry；各 tab container 从 store 直连取数据 |

### Wave 2 — 止血（防止多 Agent 相互破坏）

**目标**：停止的 Actor 不会复活、并发写不会互踩、卡死的 Worker 能被发现。

| 编号 | 修复项 | 改动文件 | 改动要点 |
|------|--------|----------|----------|
| WF-01 | Actor admin_hold + run_id | `contracts/v1/actor.py`<br>`kernel/actors.py`<br>`daemon/actors/actor_lifecycle_ops.py`<br>`daemon/messaging/chat_support_ops.py`<br>`daemon/group/group_lifecycle_ops.py`<br>`web/src/types.ts`<br>`web/src/components/AgentTab.tsx` | `admin_hold: none\|manual\|policy` 持久化；`run_id` 递增防迟到覆盖；UI 显式展示 hold badge；group_start/auto-wake 结果带 `skipped_held` |
| WF-02 | Single writer 安全模式 | `daemon/foreman/workflow_orchestrator.py` | orchestrator decision 层拦截，同一时间只批准一个可写 worker，其余 deferred (single_writer_active) |
| WF-04 | 双时钟 Heartbeat | `daemon/foreman/workflow_orchestrator.py`<br>`daemon/foreman/progress_report.py`<br>`daemon/automation/engine.py`<br>`ports/im/templates/progress_card.py`<br>`web/src/services/api.ts`<br>`web/src/stores/useWorkflowStore.ts`<br>`web/src/components/WorkflowActivityBar.tsx` | 双时钟 (last_seen_at + last_progress_at)；状态区分 blocked/stalled/offline/failed；daemon 周期 sweep |

### Wave 3 — 治理（权限与调度优化）

**目标**：Foreman 拿到完整的调度控制权，任务按依赖执行，文件冲突检测精细化。

| 编号 | 修复项 | 改动文件 | 改动要点 |
|------|--------|----------|----------|
| WF-05/06 | 受限服务主体 | `daemon/foreman/workflow_orchestrator.py`<br>`daemon/context/context_ops.py`<br>`kernel/permissions.py`<br>`daemon/actors/actor_membership_ops.py`<br>`daemon/actors/actor_lifecycle_ops.py` | `by="service:workflow_orchestrator"` + allowed_actions + scope；审计 requested_by |
| WF-03 | 依赖门控 | `contracts/v1/ralph_ipc.py`<br>`daemon/foreman/workflow_orchestrator.py` | TaskRef 加 depends_on，依赖未满足不批准 |
| WF-02b | Claimed paths + Publish barrier | `contracts/v1/ralph_ipc.py`<br>`daemon/foreman/workflow_orchestrator.py` | 与 assignment_id/generation 一起落地；admission control 升级 |
| 目标模型 | Actor 三层状态 | `contracts/v1/actor.py`<br>`kernel/actors.py`<br>全部 lifecycle ops | desired_state + runtime_state + admin_hold 完整重构 |

### 后续（Wave 4+）

| 编号 | 修复项 | 说明 |
|------|--------|------|
| WF-02c | Git Worktree 隔离 | 高风险任务临时 worktree，长期 writer 全量 worktree 化 |
| WF-04b | 断路器 | 连续 N 次相同报错自动中断 |
| WF-07 | Model Registry 强约束 + 结构化能力匹配 | 不靠 prompt 纪律，调度器做 score |
| WF-08 | Runtime-specific worker contract + adapter prompt | 统一 contract，runtime 分别包 adapter |
| WF-10 | Ralph 最小观察层 | Git diff snapshot + assignment 级 changed_files + 轻量 verification hook |
| KB-BUG-05 | Board 拖拽 | dnd-kit 集成 |
| 契约治理 | 前后端 Schema 共享/生成 | 后端 Pydantic schema → TS types；CI 契约漂移检测 |

---

## 3. 最小测试集

### Wave 1 测试

- [ ] `resolve_group_runtime_context()` 正确获取 project_root/orchestrator
- [ ] workflow/progress API 返回 `kind + reason_code + snapshot` 结构
- [ ] `kind=unavailable` 时 snapshot 仍有完整固定 shape（零值）
- [ ] `kind=running` 时 snapshot 包含真实 batches/tasks/assignments
- [ ] `ralph_task_event(completed)` 将 assignment 从 running 推进到 completed
- [ ] `ralph_task_event(failed)` 将 assignment 推进到 failed
- [ ] assignment_id 不匹配的迟到事件被丢弃（幂等）
- [ ] 前端按 `kind` 分流渲染（idle→引导态，running→统计面板）

### Wave 1.5 测试

- [ ] Tab registry 中所有 key 都有对应组件
- [ ] BoardTabContainer 从 store 直连取数据（无 prop drilling）
- [ ] AppShell 不感知 tasks/workspace 数据 shape

### Wave 2 测试

- [ ] `actor.stop` 设置 `admin_hold="manual"` 且 `enabled=false`
- [ ] `auto_wake_recipients()` 遇到 `admin_hold != "none"` 跳过
- [ ] `group_start` 跳过 held actor，结果带 `skipped_held`
- [ ] `actor.start/restart` 清除 `admin_hold` 为 `"none"`，递增 `run_id`
- [ ] 旧 run_id 的 task_event 被丢弃
- [ ] single_writer 模式下同一批只批准一个可写任务，其余 deferred
- [ ] last_seen_at 被工具执行自动刷新（被动 IO 探针）
- [ ] last_progress_at 超时 → stalled（非 failed）
- [ ] last_seen_at 超时 → offline
- [ ] `blocked` 只由 worker 显式声明，不靠超时推断

### Wave 3 测试

- [ ] `service:workflow_orchestrator` 身份可 reassign/remove，审计记录 requested_by
- [ ] 普通 foreman actor 身份仍不能越权
- [ ] 依赖未满足的任务不被批准执行
- [ ] `claimed_paths` 冲突时任务不同时批准
- [ ] 旧 assignment 的迟到提交被 publish barrier 拦截
- [ ] 状态迁移测试：什么事件允许从什么状态到什么状态
- [ ] 并发恢复测试：daemon 重启后 admin_hold/desired_state 保留

---

## 4. 风险评估

| 风险 | 说明 | 缓解措施 |
|------|------|----------|
| kind 语义增加前端复杂度 | 前端需按 kind 分流渲染 | snapshot 保持固定 shape，UI 只需 switch(kind) |
| resolve_group_runtime_context 单点 | 所有 route 依赖此入口 | 单元测试覆盖各异常分支 |
| admin_hold 导致 "起不来" | 新状态如果 UI 不展示，用户困惑 | 强制 UI 显式展示 hold badge + tooltip |
| run_id 溢出/跨进程 | 极端情况 run_id 不唯一 | 用递增整数 + daemon 重启时从持久化恢复 |
| single_writer 降并行度 | 所有任务视为可写，吞吐下降 | 短期可接受代价，Wave 3 claimed_paths 恢复并行 |
| 被动 IO 探针覆盖面 | 不是所有 worker 活动都经过 tool executor | 保留显式 progress ping 作为补充 |
| stalled 误判 | 慢任务被误标 stalled | 按任务类型设超时；stalled 先通知 Foreman 再处置 |
| service:* 前缀滥用 | 如果其他代码也用 service: 绕权限 | allowed_actions 白名单 + scope 限制 + CI 审计 |
| 超时扫描依赖后台触发器 | 触发器不运行则超时永不发生 | daemon 启动时确保周期任务注册 |
| held actor 不可见 | group_start/auto-wake 跳过但用户不知 | 返回结果带 skipped_held；UI 展示 |
| 迟到事件覆盖 | stop 后旧 worker completed 覆盖新 assignment | assignment_id + actor_run_id 双重校验 |

---

## 5. 审查采纳记录

> 记录三份审查 (gpp/gro/gedt) 中哪些建议被采纳、哪些被否决、理由是什么。

### 采纳项

| 来源 | 建议 | 采纳位置 | 说明 |
|------|------|----------|------|
| gpp | kind + reason_code + snapshot 响应结构 | §1.1, Wave 1 | 替代"扁平 idle + reason" |
| gpp | 统一 ralph_task_event + assignment_id | §1.2, Wave 1 | 替代分立 completed/failed op |
| gpp | assignment_id + run_id/generation | §1.3, Wave 2 | 防迟到事件覆盖，是方案盲点 |
| gpp | resolve_group_runtime_context() | §1.1, Wave 1 | 防各 route 分散解析 project_root |
| gpp | 受限服务主体替代泛化 system | §1.6, Wave 3 | service:workflow_orchestrator + allowed_actions |
| gpp | 双时钟 heartbeat | §1.5, Wave 2 | last_seen_at + last_progress_at |
| gpp | blocked/stalled/offline/failed 状态区分 | §1.5, Wave 2 | blocked 由 worker 显式声明 |
| gpp/gedt | Tab registry + store 直连替代 prop drilling | §1.7, Wave 1.5 | 防重构时接线断裂 |
| gpp/gedt | hold_reason → admin_hold 命名对齐目标模型 | §1.3, Wave 2 | 后续只需补 desired_state/runtime_state |
| gedt | 被动 IO 探针 (tool executor 自动刷新) | §1.5, Wave 2 | 作为 last_seen_at 数据源 |
| gpp | Wave 3+ 完整三层状态模型 | §1.3, Wave 3 | desired_state + runtime_state + admin_hold |
| gpp | publish barrier | §1.4, Wave 3 | 与 claimed_paths 一起防迟到提交 |

### 否决项

| 来源 | 建议 | 否决理由 |
|------|------|----------|
| gro | SSE/WebSocket 替代轮询 | 当前 5s 轮询足够，引入成本不justified |
| gro | Git worktree 作为 Wave 2 止血方案 | 改动链路太长（cwd/验证/合并/UI），不是本周止血方案 |
| gedt | OCC 乐观并发 + LLM 自动解冲突 | 把正确性外包给模型的 diff 处理能力，不可靠 |
| gedt | Poke 机制（外部注入 prompt） | 当前 runner 无干净的外部注入通道 |
| gpp | Phase A→F 全量波次重排 | 会延迟止血时间，不务实 |
| gro | OpenAPI 契约优先 | 方向对但不是止血阶段做的事，记入 Wave 4+ |
| gedt | desired_state 完整重构替代 admin_hold | Wave 2 改动面太大，分步走（先 admin_hold，后三层重构） |

### 记录但延后项

| 来源 | 建议 | 计划时间 |
|------|------|----------|
| gpp | 完整 actor 三层状态机 | Wave 3 |
| gro | Git worktree 隔离 | Wave 4+ |
| gedt | 断路器 (连续相同报错中断) | Wave 3+ |
| gpp | 前后端 Schema 共享/CI 契约漂移检测 | Wave 4+ |
| gpp | 结构化 principal (非字符串协议) | Wave 3+ (长期目标) |
| gpp | Ralph 最小观察层提前 | Wave 4+ (部分可前移到 Wave 3) |
| gro | Prometheus + Grafana 监控 | Wave 4+ |
| gpp | retire/decommission 替代 hard remove | Wave 3 (与服务主体一起) |

---

## 6. 关键文件索引

```
修改面（按改动量排序）：
daemon/foreman/workflow_orchestrator.py  — Wave 1 + 2 + 3 核心
daemon/ralph_ipc_handler.py              — Wave 1 ralph_task_event + kind/reason_code
daemon/foreman/progress_report.py        — Wave 1 snapshot 补全 + Wave 2 stalled/offline
contracts/v1/actor.py                    — Wave 2 admin_hold + run_id
contracts/v1/ralph_ipc.py                — Wave 1 TaskEvent + Wave 3 TaskRef 扩展
ports/web/routes/workflow.py             — Wave 1 resolve_group_runtime_context + 薄转发
daemon/actors/actor_lifecycle_ops.py     — Wave 2 stop/start hold/run_id + Wave 3 service 身份
daemon/actors/actor_membership_ops.py    — Wave 3 service 身份 remove 入口
daemon/messaging/chat_support_ops.py     — Wave 2 auto_wake admin_hold 检查
daemon/group/group_lifecycle_ops.py      — Wave 2 group_start admin_hold 检查
daemon/automation/engine.py              — Wave 2 heartbeat timeout sweep 触发器
daemon/context/context_ops.py            — Wave 3 service 身份放行
kernel/permissions.py                    — Wave 3 service:* 处理 + allowed_actions
kernel/actors.py                         — Wave 2 admin_hold/run_id 在 add/update 中处理
ports/im/templates/progress_card.py      — Wave 2 stalled/offline 飞书卡片
web/src/components/app/AppShell.tsx      — Wave 1.5 Tab registry 纯壳层
web/src/App.tsx                          — Wave 1.5 简化（移除 prop drilling）
web/src/types.ts                         — Wave 2 Actor 类型 admin_hold/run_id
web/src/services/api.ts                  — Wave 1 kind + snapshot 类型 + Wave 2 状态类型
web/src/stores/useWorkflowStore.ts       — Wave 1 按 kind 消费 + Wave 2 状态类型
web/src/components/WorkflowActivityBar.tsx — Wave 2 stalled/offline UI
web/src/components/AgentTab.tsx          — Wave 2 hold 状态 badge
新增 web/src/pages/BoardTabContainer.tsx — Wave 1.5 store 直连
新增 web/src/pages/WorkspaceTabContainer.tsx — Wave 1.5 store 直连
新增 web/src/pages/PanoramaTabContainer.tsx — Wave 1.5 store 直连
```
