# Ralph-Foreman 工作流系统

## 1. 整体架构

系统由三个核心层组成：**Ralph（观察层）**、**Foreman（控制层）**、**Worker Agents（执行层）**。

```
┌─────────────────────────────────────────────────────────────────────┐
│                           用户 / 飞书                               │
│                   (需求输入 · 进度推送 · 人工介入)                    │
└────────────────────────────┬────────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────────┐
│                     CCCC Daemon (控制权威)                           │
│                                                                     │
│  ┌──────────┐   IPC    ┌───────────────────┐   lifecycle   ┌──────┐│
│  │  Ralph   │ ──────→  │ WorkflowOrchest-  │ ───────────→  │Worker││
│  │ (观察者) │ ←──────  │ rator + Foreman   │ ←───────────  │Agent ││
│  └──────────┘  batch   │   (决策 + 调度)    │  msg/status   │ Pool ││
│                suggest  └─────────┬─────────┘               └──────┘│
│                                   │                                  │
│               ┌───────────────────┼───────────────────┐              │
│               │ ProgressReporter  │ Control Plane     │              │
│               │ (飞书卡片)        │ (cccc_task/coord) │              │
│               └───────────────────┴───────────────────┘              │
└─────────────────────────────────────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────────┐
│                      Web Frontend                                   │
│   WorkflowTab · WorkflowActivityBar · useWorkflowStore (5s 轮询)    │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.1 Ralph — 观察层

- 外部 Python 守护进程，监控 Git 提交和任务依赖图
- 计算「哪些任务的前置依赖已满足，可以并行执行」
- 通过 **Daemon IPC**（Unix socket + JSON line）将 `ReadyBatchSuggestion` 发送给 CCCC Daemon
- **只读分析层**，没有执行权限

### 1.2 Foreman — 控制层

- CCCC Daemon 内部的工作流决策中心
- 接收 Ralph 的 batch 建议 → 评估 Agent Pool → 分配任务 → 启动 Agent
- 维护 Actor 生命周期的最终权威
- 对外通过 ProgressReporter 推送飞书进度卡片
- 对内通过 Control Plane（`cccc_task` / `cccc_coordination`）同步共享状态

### 1.3 Worker Agent — 执行层

- 由 Foreman 动态创建或复用的 AI Agent
- 每个 Agent 绑定一个具体模型（Claude / Gemini / Codex 等）
- 在独立的 UI tab 中运行，通过 MCP 工具与 Foreman 通信
- 执行完成后通过 `cccc_message_send(to="@foreman", ...)` 汇报结果

---

## 2. 核心数据模型

### 2.1 IPC 消息协议 (`contracts/v1/ralph_ipc.py`)

| 消息类型 | 方向 | 用途 |
|----------|------|------|
| `ReadyBatchSuggestion` | Ralph → Foreman | 建议一批可并行的任务 |
| `BatchDecision` | Foreman → Ralph | 对 batch 的决策（approved/modified/rejected/deferred） |
| `VerificationResult` | Ralph → Foreman | 验证结果（build/test/lint） |
| `RestartSuggestion` | Ralph → Foreman | 建议重启失败/卡住的任务 |
| `ActorStatus` | 任意 Actor → Daemon | Actor 状态上报 |

**TaskRef** — 任务引用：

```python
class TaskRef(BaseModel):
    id: str
    title: str = ""
    type: Literal["frontend", "backend", "general"] = "general"
```

**BatchDecisionType** — 批次决策类型：

```python
BatchDecisionType = Literal["approved", "modified", "rejected", "deferred"]
```

**Actor 状态机**：

```
idle → analyzing → executing → completed
                  ↘ waiting → blocked
```

### 2.2 Agent 合约 (`contracts/v1/agent.py`)

**Agent** — 动态创建的 AI Agent：

```python
class Agent(BaseModel):
    id: str                          # "claude-backend-worker-1"
    name: str                        # "Claude Backend Worker"
    model_runtime: str               # "claude" / "gemini" / "codex"
    model_id: str                    # "claude-sonnet-4"
    role_type: AgentRoleType         # "worker" / "reviewer" / "specialist"
    capabilities: List[str]          # ["task_execution", "code_modification", ...]
    task_affinity: List[str]         # ["backend", "database"]
    prompt: str                      # 自定义 system prompt
    created_by: str                  # "foreman"
```

**ModelCapability** — 模型能力描述（存于 `registry.yaml`）：

```python
class ModelCapability(BaseModel):
    runtime: str                     # "claude" / "gemini"
    model_id: str                    # "claude-sonnet-4"
    strengths: List[str]             # ["complex_logic", "code_refactoring"]
    weaknesses: List[str]            # ["realtime_info"]
    context_window: str              # "200k"
    foreman_rating: Optional[float]  # Foreman 评分 (1-5)
    foreman_sample_count: int        # 评分样本数
```

**ModelRegistry** — 可用模型注册表：

```python
class ModelRegistry(BaseModel):
    models: Dict[str, ModelCapability]
    # 查询方法: get_model(), find_by_strength(), find_by_runtime()
```

---

## 3. 工作流生命周期

### 3.1 完整执行序列

```
Ralph                   Daemon IPC              WorkflowOrchestrator        AgentPool           Web UI
  │                        │                           │                       │                  │
  │──ReadyBatchSuggestion─→│                           │                       │                  │
  │                        │──handle_ralph_batch_suggest│                       │                  │
  │                        │   ↓ auto_process=true     │                       │                  │
  │                        │──process_batch_suggestion─→│                       │                  │
  │                        │                           │──evaluate_for_task───→│                  │
  │                        │                           │←─AgentEvaluation[]────│                  │
  │                        │                           │──create_or_reuse_agent→│                  │
  │                        │                           │←─TaskAssignment────────│                  │
  │                        │                           │                       │                  │
  │                        │                           │──sync_batch_to_control_plane              │
  │                        │                           │  (cccc_task.create + coordination.note)   │
  │                        │                           │                       │                  │
  │                        │                           │──reporter.on_batch_started (飞书卡片)     │
  │                        │                           │                       │                  │
  │                        │                           │──_start_assigned_agents│                  │
  │                        │                           │  ├─ _add_actor_via_daemon (actor_add)──→ │ 新 tab
  │                        │                           │  └─ _send_message_fn (task prompt)──→    │
  │                        │                           │                       │                  │
  │                        │                           │            Worker 执行任务...             │
  │                        │                           │                       │       poll 5s ──→│
  │                        │                           │←─────────on_task_completed                │
  │                        │                           │  ├─ reporter.on_task_completed (飞书)     │
  │                        │                           │  ├─ record_model_usage                    │
  │                        │                           │  ├─ release_agent                         │
  │                        │                           │  └─ _check_batch_completion               │
  │                        │                           │                       │                  │
  │←─VerificationResult───│                           │                       │                  │
  │                        │──on_verification_result──→│                       │                  │
  │                        │                           │  (passed → batch_complete)                │
  │                        │                           │  (failed → task_failed)                   │
  │                        │                           │                       │                  │
  │  (下一个 batch)         │                           │                       │                  │
  │──ReadyBatchSuggestion─→│                           │  ... 循环 ...          │                  │
  │                        │                           │                       │                  │
  │                        │         complete_workflow  │ reporter.on_workflow_completed (飞书)     │
```

### 3.2 阶段详解

#### Phase 1: 接收 Batch 建议

Ralph 通过 IPC 发送 `ReadyBatchSuggestion`，包含：
- `suggestion_id` — 建议唯一 ID
- `workflow_id` — 工作流 ID
- `tasks[]` — 准备执行的任务列表（TaskRef）
- `rationale` — 为什么这些任务可以一起执行
- `estimated_parallelism` — 预期并行度

Daemon 的 `ralph_ipc_handler.py` 接收后：
1. 存入 `_RALPH_STATE["pending_suggestions"]`
2. 若 `auto_process=true`，直接调用 `_try_process_batch()` 进入下一阶段

#### Phase 2: 评估 Agent Pool

`AgentPoolManager.evaluate_for_task()` 对每个任务评估所有可用 Agent，评分维度：

| 维度 | 分值 | 说明 |
|------|------|------|
| 任务亲和力 | 0-40 | task_type 匹配 agent 的 task_affinity |
| 角色匹配 | 0-30 | worker=30, specialist=25 |
| 能力匹配 | 0-20 | 所需 capabilities 是否满足 |
| 模型适配 | 0-10 | 模型 strengths 包含该任务类型 |

各任务类型所需能力：

| 任务类型 | 所需能力 |
|----------|----------|
| frontend | task_execution, code_modification |
| backend  | task_execution, code_modification, memory_access |
| general  | task_execution |

#### Phase 3: 分配任务

`AgentPoolManager.create_or_reuse_agent()` 对每个任务：

1. **优先复用**：寻找评分 ≥ 50 的空闲 Agent
2. **创建新 Agent**：若无合适 Agent，根据任务类型和模型注册表创建
   - 自动选择最佳模型（`select_model_for_task`）
   - 生成唯一 agent_id（如 `claude-backend-worker-1`）
   - 设置 Worker Contract prompt

生成的 `TaskAssignment` 包含：
```python
TaskAssignment(
    task=TaskRef,
    agent_id="claude-backend-worker-1",
    agent_name="Claude Backend Worker",
    is_new_agent=True,
    assignment_reason="Created new agent for backend task",
    model_runtime="claude",
    model_id="claude-sonnet-4",
)
```

#### Phase 4: 批次决策

`ForemanWorkflow.process_batch_suggestion()` 汇总结果，决定：

| 决策 | 条件 |
|------|------|
| `approved` | 所有任务都成功分配 |
| `modified` | 部分任务分配成功，部分被拒 |
| `rejected` | 没有任何任务能分配 |
| `deferred` | 延后处理 |

#### Phase 5: 启动 Agent

`WorkflowOrchestrator._start_assigned_agents()` 对每个已分配的任务：

1. **注册为 Group Actor**：通过 `daemon_request_fn(actor_add)` 创建真正的 Actor
   - runtime（claude/gemini）、capability_autoload（pack:group-runtime）
   - UI 前端自动创建新 tab

2. **发送任务 Prompt**：通过 `_send_message_fn` 发送结构化任务指令：
   ```
   [Foreman Assignment]
   Task ID: xxx
   Title: 实现用户登录
   Type: backend

   Execute this task only.
   Report back to Foreman with:
   - progress delta or blockers
   - changed files or evidence
   - anything still unverified
   - Report via cccc_message_send(to="@foreman", text=...).
   ```

3. **同步到 Control Plane**：创建 `cccc_task` 记录 + `coordination.note`

#### Phase 6: 任务执行与完成

Worker Agent 独立执行，完成后触发 `on_task_completed()`：

1. 更新 assignment 状态为 `completed`
2. 记录模型用量（`record_model_usage` → `registry.yaml`）
3. 释放 Agent（`pool_manager.release_agent`）
4. 推送飞书完成卡片
5. 检查 batch 是否全部完成

任务失败时触发 `on_task_failed()`，状态更新为 `failed`。

#### Phase 7: 验证与批次完成

Ralph 运行验证（build/test/lint），发送 `VerificationResult`：

- `passed` → 标记 batch 完成，可以进入下一个 batch
- `failed` → 标记相关任务失败，推送飞书告警
- `timeout` / `skipped` → 记录并通知

Batch 完成条件：当前 batch 内所有任务都不在 `pending`/`running` 状态。

#### Phase 8: 工作流完成

所有 batch 处理完毕后调用 `complete_workflow()`：
- 清理 `_active_workflows` 状态
- 推送飞书「工作流完成」卡片
- 清空 ProgressReporter 状态

---

## 4. Daemon IPC 操作接口

`ralph_ipc_handler.py` 注册的 Daemon 操作：

| 操作名 | 功能 | 关键参数 |
|--------|------|----------|
| `ralph_batch_suggest` | Ralph 提交 batch 建议 | workflow_id, tasks[], auto_process |
| `ralph_verification_result` | Ralph 报告验证结果 | workflow_id, overall_outcome, checks[] |
| `ralph_restart_suggest` | Ralph 建议重启任务 | workflow_id, task_id, reason |
| `ralph_batch_decision` | Foreman 决策 batch | suggestion_id, decision, approved/rejected |
| `ralph_actor_status` | Actor 状态上报 | actor_id, status, progress_pct |
| `ralph_get_pending` | 查询待处理建议 | workflow_id |
| `ralph_get_actors` | 查询 Actor 状态 | workflow_id, actor_type |
| `ralph_process_pending` | 手动处理待定 batch | suggestion_id, group_id, project_root |
| `ralph_workflow_progress` | 查询工作流进度 | group_id, workflow_id |
| `ralph_clear_workflow` | 清理已完成工作流 | workflow_id |

内存状态存储（`_RALPH_STATE`）：

```python
{
    "pending_suggestions": {},   # suggestion_id -> ReadyBatchSuggestion
    "pending_restarts": {},      # suggestion_id -> RestartSuggestion
    "decisions": {},             # decision_id -> BatchDecision
    "verifications": {},         # verification_id -> VerificationResult
    "actor_statuses": {},        # actor_id -> ActorStatus
}
```

---

## 5. 进度报告系统

### 5.1 ProgressReporter

`daemon/foreman/progress_report.py` 管理进度状态和飞书通知。

**进度状态（ProgressState）**：

```python
ProgressState:
    workflow_id: str
    current_batch_id: str
    batch_start_time: float
    workflow_start_time: float
    total_batches / completed_batches: int
    tasks: Dict[task_id, TaskInfo]      # 全量任务状态
    current_batch_task_ids: List[str]   # 当前批次的任务
```

**任务状态流转**：

```
PENDING → RUNNING → COMPLETED
                  ↘ FAILED
                  ↘ BLOCKED (需人工介入)
                  ↘ SKIPPED
```

### 5.2 飞书卡片通知

| 事件 | 触发时机 | 卡片内容 |
|------|----------|----------|
| `batch_started` | batch 开始执行 | 任务列表、Agent 分配、并行度 |
| `task_completed` | 单个任务完成 | Agent 名、耗时、变更文件、批次进度 |
| `task_failed` | 任务失败 | 错误信息、建议操作 |
| `intervention_needed` | 需要人工介入 | 原因、操作选项 |
| `batch_completed` | 批次全部完成 | 完成/失败/跳过统计、耗时 |
| `workflow_completed` | 工作流完成 | 批次数、任务数、总耗时 |

卡片通过 `ProgressCardBuilder`（`ports/im/templates/progress_card.py`）构建，经 `FeishuAdapterWrapper` 发送。

---

## 6. Kernel 层

### 6.1 角色系统

角色由 `kernel/system_prompt.py` 中的 `get_effective_role()` 确定，分为：

**Foreman（管理者）**：
- 负责用户对齐、计划制定、Agent 路由、模型选择、进度评判、对外更新
- 不直接执行实现任务（除非用户明确指定 foreman-only）
- 可用工具：`cccc_actor`, `cccc_runtime_list`, `cccc_model`
- 将 `done`、`idle`、沉默视为需要评估的信号，而非终结

**Peer（执行者 / Worker）**：
- 只执行 Foreman 分配的范围
- 提交具体证据、变更文件、阻塞项
- 不擅自重新规划工作流或创建新 Worker
- 通过 `cccc_message_send(to="@foreman", ...)` 回报

### 6.2 System Prompt 生成

`render_system_prompt(group, actor)` 组装如下结构：

```
[CCCC] You are {actor_id} ({role}) in group '{title}'
group_id: {group_id}
runtime: {runtime} ({runner})
topic: {topic}
team: {actor_count} actors (...)
foreman: {foreman_ids}
project: PROJECT.md found (...)

scopes (* = active):
  main: /path/to/repo *

---
Working Style:
- Work like a sharp teammate, not a customer-service script.
- Prefer silence over low-signal chatter...

Platform Invariants:
- No fabrication. Verify before claiming done.
- Visible replies must go through MCP...

Role Focus:
- (Foreman 或 Peer 的角色规则)

Memory:
- (内存策略)

Group Space:
- (NotebookLM 绑定状态)

(CCCC_PREAMBLE.md 或 DEFAULT_PREAMBLE_BODY)
```

### 6.3 Preamble — 默认执行指南

`prompt_files.py` 中的 `DEFAULT_PREAMBLE_BODY`：

1. **Quick start** — 先调 `cccc_bootstrap`，获取 session/recovery/inbox/memory_recall_gate
2. **Ralph workflow** — Foreman 职责清单（对齐、规划、路由、进度、更新）
3. **Execution checklist** — MCP 可见通信、共享状态同步、agent_state 维护
4. **Gap routing** — 信息缺口 → bootstrap/context/project_info/web; 能力缺口 → capability_use
5. **Memory boundary** — agent_state = 短期执行内存; memory files = 长期记忆

### 6.4 能力系统 (`kernel/capabilities.py`)

**始终可见的核心工具**：
- `cccc_help`, `cccc_bootstrap`, `cccc_project_info`
- `cccc_capability_search`, `cccc_capability_state`
- `cccc_inbox_*`, `cccc_message_*`, `cccc_file`, `cccc_presentation`
- `cccc_context_get`, `cccc_coordination`, `cccc_task`
- `cccc_agent_state`, `cccc_memory`

**按需启用的能力包**：

| 能力包 | 用途 |
|--------|------|
| `pack:group-runtime` | Group 状态、Actor/Runtime 生命周期、模型管理 |
| `pack:file-im` | 文件附件、IM 绑定 |
| `pack:space` | NotebookLM Group Space 操作 |
| `pack:automation` | 自动化提醒检查与修改 |
| `pack:context-advanced` | Context 同步、内存管理 |
| `pack:headless-notify` | Headless 运行器、通知 |
| `pack:diagnostics` | 终端日志、调试诊断 |

### 6.5 任务管理能力 (`resources/capabilities/task_management.yaml`)

为不同角色注入 Prompt Fragment：

- **Common**：任务工具列表（cccc_task, cccc_coordination, cccc_actor, cccc_runtime_list, cccc_model）
- **Foreman**：编排职责、Worker 复用、模型选择策略
- **Peer**：任务执行、证据提交、不擅自扩大范围

---

## 7. Web 前端

### 7.1 状态管理 — useWorkflowStore (Zustand)

```typescript
interface WorkflowState {
  pendingSuggestions: BatchSuggestion[]     // 待处理的 batch 建议
  decisions: BatchDecision[]               // 已做出的决策
  progress: WorkflowProgress | null        // 当前工作流进度
  assignments: WorkflowAgentAssignment[]   // Agent 分配详情

  // 异步操作
  refreshPending(workflowId?)              // 刷新待处理列表
  refreshProgress(groupId, workflowId?)    // 刷新进度（5s 轮询）
  submitBatch(groupId, workflowId, tasks)  // 提交 batch 建议
  processBatch(groupId, suggestionId)      // 处理待定 batch
  clearWorkflow(workflowId)               // 清理已完成工作流
}
```

**WorkflowAgentAssignment**：

```typescript
interface WorkflowAgentAssignment {
  task_id: string
  task_title: string
  task_type: "frontend" | "backend" | "general"
  agent_id: string
  agent_name: string
  model_runtime: string       // "claude" / "gemini"
  model_id: string
  is_new_agent: boolean
  status: "pending" | "running" | "completed" | "failed"
  duration_seconds?: number
  changed_files?: string[]
}
```

### 7.2 WorkflowTab — 详细工作流视图

展示完整工作流状态：
- Agent 分配卡片（任务标题、类型图标、Agent 名称/runtime、状态）
- 任务类型标识（F/B/G = frontend/backend/general）
- 状态颜色：completed=绿 / failed=红 / running=蓝 / pending=黄
- 耗时格式化、点击导航到 Agent tab
- 批次决策展示

### 7.3 WorkflowActivityBar — 内嵌进度条

Chat tab 内的紧凑工作流状态条：
- 实时 Agent 状态芯片（状态圆点 + 名称 + 任务标题）
- 计数器：running / pending / done / failed
- 渐变进度条（cyan → emerald）
- 可折叠/展开；「详情」按钮跳转到 WorkflowTab
- **每 5 秒自动轮询** `refreshProgress(groupId)`

### 7.4 API 层 (`services/api.ts`)

| API 函数 | 对应 Daemon 操作 |
|----------|-----------------|
| `fetchWorkflowPending()` | `ralph_get_pending` |
| `fetchWorkflowProgress()` | `ralph_workflow_progress` |
| `submitBatchSuggestion()` | `ralph_batch_suggest` |
| `processPendingBatch()` | `ralph_process_pending` |
| `clearWorkflow()` | `ralph_clear_workflow` |

---

## 8. 文件结构索引

```
src/cccc/
├── contracts/v1/
│   ├── ralph_ipc.py          # IPC 消息协议（TaskRef, BatchSuggestion, BatchDecision 等）
│   └── agent.py              # Agent/ModelCapability/ModelRegistry 数据模型
├── daemon/
│   ├── ralph_ipc_handler.py  # Daemon 操作路由（10 个 ralph_* 操作）
│   ├── foreman/
│   │   ├── workflow.py            # ForemanWorkflow — 批次处理管线
│   │   ├── workflow_orchestrator.py # WorkflowOrchestrator — 集成层（IPC + Foreman + Reporter）
│   │   ├── agent_pool.py          # AgentPoolManager — Agent 评估/创建/分配
│   │   └── progress_report.py     # ProgressReporter — 飞书进度通知
│   └── ops/
│       ├── agent_ops.py           # Agent CRUD 操作
│       └── model_ops.py           # 模型用量记录
├── kernel/
│   ├── system_prompt.py      # System Prompt 渲染（角色策略 + 内存策略 + Space 策略）
│   ├── prompt_files.py       # Preamble/Help 文件管理 + DEFAULT_PREAMBLE_BODY
│   ├── capabilities.py       # 能力系统（核心工具 + 能力包）
│   ├── group.py              # Group 数据模型（group.yaml）
│   └── actors.py             # Actor 列表、角色推断
├── ports/
│   ├── mcp/handlers/
│   │   └── cccc_core.py      # MCP 核心工具（help, bootstrap, project_info, memory）
│   ├── web/routes/
│   │   └── groups.py         # HTTP API 路由
│   └── im/templates/
│       └── progress_card.py  # 飞书卡片模板构建
└── resources/
    ├── cccc-help.md           # 内置帮助文档
    └── capabilities/
        └── task_management.yaml  # 任务管理能力定义

web/src/
├── stores/
│   └── useWorkflowStore.ts   # Zustand 工作流状态
├── pages/
│   └── WorkflowTab.tsx       # 详细工作流视图
├── components/
│   └── WorkflowActivityBar.tsx # 内嵌进度条
└── services/
    └── api.ts                # API 调用层
```

---

## 9. 设计要点

### 9.1 关注分离

- **Ralph 只观察不执行**：分析 Git、计算依赖、建议 batch，但不碰 Actor 生命周期
- **Foreman 只调度不实现**：评估 Agent、分配任务、追踪进度，但不写业务代码
- **Worker 只执行不决策**：完成分配的任务范围，不擅自扩大或重新规划

### 9.2 Agent 复用策略

优先复用已有 Agent（评分 ≥ 50），减少 Actor 创建开销。评分系统综合考虑任务亲和力、角色类型、能力匹配和模型特长。

### 9.3 模型感知调度

Foreman 通过 `ModelRegistry` 了解各模型的 strengths/weaknesses，为不同类型任务选择最合适的模型。模型使用记录会存入 registry.yaml，支持后续的 Foreman 评分。

### 9.4 飞书实时反馈

关键事件（batch 开始、任务完成/失败、需要介入、工作流完成）都通过飞书卡片实时推送，确保用户在 IM 端即可掌握工作流进展。

### 9.5 Control Plane 同步

每个 batch 决策都会同步到 CCCC 的共享状态（`cccc_task` + `cccc_coordination`），确保所有 Actor 可以看到相同的任务全景。
