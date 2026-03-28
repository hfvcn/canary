# CCCC Workflow 全量并行执行计划

> 涵盖 Wave 1 ~ Wave 4+ 的所有改动，按 Ralph 依赖分析拆分为并行 Batch。
> 已完成的 Batch 标注 ✅，未来的 Batch 标注文件依赖和并行策略。

---

## 已完成进度

### Wave 1 + 1.5 ✅ 全部完成

| Phase | Batch | Task | Worker | 状态 | 验证 |
|-------|-------|------|--------|------|------|
| 1 | batch-0 | 契约 (TaskEvent) + RalphService 骨架 + handler adapter | Codex-A | ✅ | py_compile 通过 |
| 1 | batch-1C | Tab registry + BoardTabContainer + Workspace/Panorama 占位 | Codex-C | ✅ | tsc + build 通过 |
| 2 | batch-1A | kind+snapshot 后端响应 + orchestrator 接入 RalphService + apply_task_event | Codex-1A | ✅ | py_compile 通过 |
| 2 | batch-1B | resolve_group_runtime_context + route 改造 (ralph_task_event 薄转发) | Codex-1B | ✅ | py_compile 通过 |
| 3 | batch-2 | WorkflowProgressResponse 前端类型 + store refreshProgress 改造 | Codex-2 | ✅ | tsc 通过 |

**产出文件** (新建 4 个 + 修改 8 个):
- 新建: `ralph_service.py`, `BoardTabContainer.tsx`, `WorkspaceTabContainer.tsx`, `PanoramaTabContainer.tsx`
- 修改: `ralph_ipc.py`, `ralph_ipc_handler.py`, `workflow_orchestrator.py`, `progress_report.py`, `workflow.py`, `AppShell.tsx`, `api.ts`, `useWorkflowStore.ts`

---

## Wave 2 — 止血

### Batch W2-0 — 契约层 (串行基座)

#### Task W2-0A: Actor model 扩展 (admin_hold + run_id)

**write_set**: `contracts/v1/actor.py`, `kernel/actors.py`
**depends_on**: `[]`

改动:
- `actor.py`: 新增 `admin_hold: Literal["none", "manual", "policy"] = "none"` 和 `run_id: int = 0`
- `actors.py`: `add_actor()` 初始化 admin_hold/run_id；`update_actor()` 支持这两个字段

---

### Batch W2-1 — 并行组 (W2-0 完成后，4 个 Task 同时执行)

#### Task W2-1A: actor stop/start hold 逻辑

**write_set**: `daemon/actors/actor_lifecycle_ops.py`
**depends_on**: `[W2-0A]`

改动:
- `handle_actor_stop()`: 同时设 `enabled=false` + `admin_hold="manual"`
- `handle_actor_start/restart()`: 清除 `admin_hold="none"`，递增 `run_id`

---

#### Task W2-1B: auto_wake + group_start hold 检查

**write_set**: `daemon/messaging/chat_support_ops.py`, `daemon/group/group_lifecycle_ops.py`
**depends_on**: `[W2-0A]`

改动:
- `auto_wake_recipients()`: 检查 `admin_hold != "none"` → 跳过并记日志
- `handle_group_start()`: 跳过 held actor，结果带 `skipped_held` 列表

---

#### Task W2-1C: single_writer 安全模式

**write_set**: `daemon/foreman/workflow_orchestrator.py`
**depends_on**: `[W2-0A]`

改动:
- `process_batch_suggestion()` 增加 single_writer gate：同一时间只批准一个可写 worker
- 未批准的标为 `deferred`（理由 `single_writer_active`）
- 所有 task 默认视为"可写"

---

#### Task W2-1D: 前端 hold badge + stalled UI

**write_set**: `web/src/types.ts`, `web/src/components/AgentTab.tsx`, `web/src/components/WorkflowActivityBar.tsx`
**depends_on**: `[W2-0A]` (实际只需要知道字段名，前端独立)

改动:
- `types.ts`: Actor 类型加 `admin_hold`, `run_id`
- `AgentTab.tsx`: hold 状态 badge + tooltip
- `WorkflowActivityBar.tsx`: stalled/offline 状态颜色和图标

---

### Batch W2-2 — 双时钟 Heartbeat (W2-1C 完成后)

#### Task W2-2A: heartbeat sweep 后台任务

**write_set**: `daemon/automation/engine.py`, `daemon/foreman/ralph_service.py`
**depends_on**: `[W2-1C]`

改动:
- `ralph_service.py`: 新增 `sweep_stalled_tasks()` — 检查 last_seen_at/last_progress_at 超时
- `engine.py`: 注册周期任务调用 sweep

---

#### Task W2-2B: heartbeat 前端状态类型

**write_set**: `web/src/services/api.ts`, `web/src/stores/useWorkflowStore.ts`
**depends_on**: `[W2-1D]`

改动:
- `api.ts`: WorkflowAgentAssignment.status 扩展 `"stalled" | "offline" | "blocked"`
- `useWorkflowStore.ts`: 状态类型同步

---

### Batch W2-3 — 飞书卡片 (可与 W2-2 并行)

#### Task W2-3A: stalled/offline 飞书卡片

**write_set**: `ports/im/templates/progress_card.py`, `daemon/foreman/progress_report.py`
**depends_on**: `[W2-0A]`

改动:
- `progress_card.py`: ProgressStatus 枚举加 STALLED/OFFLINE
- `progress_report.py`: on_task_stalled() / on_task_offline() 事件处理

---

### Wave 2 依赖图

```
         W2-0A (actor model)
              │
   ┌──────┬──┴───┬──────┐
   │      │      │      │
 W2-1A  W2-1B  W2-1C  W2-1D     W2-3A
 (stop)  (wake) (single (UI)     (飞书)
                writer)
              │      │
           W2-2A  W2-2B
           (sweep) (types)
```

### Wave 2 执行策略

| Phase | Tasks | 并行数 | 说明 |
|-------|-------|--------|------|
| W2-P0 | W2-0A | 1 | 契约必须先做 |
| W2-P1 | W2-1A + W2-1B + W2-1C + W2-1D + W2-3A | 5 | write_set 无交集 |
| W2-P2 | W2-2A + W2-2B | 2 | heartbeat 依赖 single_writer 和 UI |

---

## Wave 3 — 治理

### Batch W3-0 — 契约层 (串行基座)

#### Task W3-0A: TaskRef 扩展 + 服务主体定义

**write_set**: `contracts/v1/ralph_ipc.py`, `kernel/permissions.py`
**depends_on**: `[]`

改动:
- `ralph_ipc.py`: TaskRef 加 `depends_on: List[str]`, `claimed_paths: List[str]`
- `permissions.py`: 新增 `service:*` 前缀处理 + `allowed_actions` 白名单

---

### Batch W3-1 — 并行组 A (W3-0 完成后，3 路并行)

> Codex 冲突检查发现原方案 5 路并行不安全，调整为 3 阶段。

#### Task W3-1B: 服务主体权限放行 (必须先于 W3-1A)

**write_set**: `daemon/actors/actor_membership_ops.py`, `daemon/actors/actor_lifecycle_ops.py`, `daemon/context/context_ops.py`
**depends_on**: `[W3-0A]`

改动:
- `context_ops.py`: `service:*` 前缀放行 reassign/remove + 审计 `requested_by`
- actor ops: `require_actor_permission()` 对 `service:*` 身份按 allowed_actions 放行
- 注意：`permissions.py` 的 `service:*` 处理已在 W3-0A 落地

---

#### Task W3-1C: 依赖门控 + claimed_paths (可与 W3-1B 并行)

**write_set**: `daemon/foreman/ralph_service.py`
**depends_on**: `[W3-0A]`

改动:
- `suggest_ready_batch()`: 实现 depends_on DAG 检查 + claimed_paths 冲突检测
- `check_dependencies()`: 真正查询已完成任务列表
- single_writer gate 升级为 claimed_paths admission control

---

#### Task W3-1E: 前端权限/状态 UI (可与 W3-1B 并行)

**write_set**: `web/src/types.ts`, `web/src/services/api.ts`, `web/src/stores/useWorkflowStore.ts`
**depends_on**: `[W3-0A]`

改动:
- 前端类型同步 depends_on/claimed_paths
- deferred 任务在 UI 中显示原因

---

### Batch W3-2 — 串行依赖 (W3-1B 完成后)

#### Task W3-2A: 受限服务主体接入 orchestrator

**write_set**: `daemon/foreman/workflow_orchestrator.py`
**depends_on**: `[W3-1B]` (权限放行必须先到位，否则 service:* 调用会被拒绝)

改动:
- orchestrator 调度时 `by="service:workflow_orchestrator"`
- actor_add/remove/reassign 统一走 service 身份

---

### Batch W3-3 — 三层状态重构 (W3-2A 完成后，独立大任务)

> Codex 指出此任务改动面远超 4 个文件，enabled 字段被 10+ 处依赖。
> 不能与其他改 actor 相关文件的任务并行。

#### Task W3-3D: Actor 三层状态重构

**write_set**: `contracts/v1/actor.py`, `kernel/actors.py`, `kernel/messaging.py`, `daemon/actors/actor_lifecycle_ops.py`, `daemon/actors/actor_update_ops.py`, `daemon/group/group_lifecycle_ops.py`, `daemon/messaging/chat_support_ops.py`
**depends_on**: `[W3-2A]` (权限模型稳定后再重构状态)

改动:
- `desired_state: running | stopped`
- `runtime_state: starting | running | stopping | stopped | crashed`
- `admin_hold` 保留，reconciliation loop：`desired_state==running && admin_hold==none → start`
- 全面替换 `enabled` 的 10+ 处依赖

---

### Wave 3 依赖图 (修正后)

```
         W3-0A (contracts + permissions.py)
              │
   ┌──────────┼──────────┐
   │          │          │
 W3-1B      W3-1C      W3-1E
 (权限放行)  (ralph     (前端
              门控)      types)
   │
 W3-2A
 (orchestrator
  service 身份)
   │
 W3-3D
 (三层状态
  重构, 10+文件)
```

### Wave 3 执行策略

| Phase | Tasks | 并行数 | 说明 |
|-------|-------|--------|------|
| W3-P0 | W3-0A | 1 | 契约 + permissions 基座 |
| W3-P1 | W3-1B + W3-1C + W3-1E | 3 | 权限放行/Ralph门控/前端 (无交集) |
| W3-P2 | W3-2A | 1 | orchestrator 接入 service 身份 (依赖 W3-1B) |
| W3-P3 | W3-3D | 1 | 三层状态重构 (改动面大，独立串行) |

> 冲突修正说明 (Codex 验证):
> - W3-1B 必须先于 W3-2A：service:* 权限放行必须先落地，否则 orchestrator 用 service 身份调用会被拒绝
> - W3-3D 必须最后做：enabled 字段被 10+ 处依赖，三层状态重构会波及 actor_lifecycle_ops/actor_update_ops/messaging.py 等，不能与其他改 actor 的任务并行
> - W3-1B 的 write_set 修正：需要改 context_ops.py (原方案漏写)

---

## Wave 4+ — 长期演进

### Batch W4-独立 (各 Task 间无依赖，可按需并行)

#### Task W4-A: Git Worktree 隔离

**write_set**: `daemon/foreman/ralph_service.py`, `daemon/foreman/workflow_orchestrator.py`
**depends_on**: `[W3-1C]` (需要 claimed_paths 基座)

改动:
- RalphService: `create_worktree()`, `merge_worktree()`, `cleanup_worktree()`
- Orchestrator: 高风险任务自动分配到 worktree

---

#### Task W4-B: 断路器

**write_set**: `daemon/foreman/ralph_service.py`
**depends_on**: `[W2-2A]` (需要 heartbeat 基座)

改动:
- `detect_stuck_loop()`: 连续 N 次相同 tool 调用 + 相同报错 → 中断

---

#### Task W4-C: Model Registry 强约束 + 能力匹配

**write_set**: `daemon/foreman/agent_pool.py`, `daemon/ops/agent_ops.py`, `contracts/v1/agent.py`
**depends_on**: `[]`

改动:
- Agent.task_affinity/capabilities 映射到 Actor
- AgentPoolManager: registry key 修正 (按 model_id 查而非 runtime)
- 调度器 score 替代 prompt 纪律

---

#### Task W4-D: Runtime-specific worker contract

**write_set**: `daemon/foreman/workflow_orchestrator.py` (prompt 模板), `kernel/prompt_files.py`
**depends_on**: `[]`

改动:
- 统一 worker contract (输入/输出/reporting format)
- 按 runtime (claude/codex/gemini) 包 adapter prompt

---

#### Task W4-E: Ralph 观察层深化

**write_set**: `daemon/foreman/ralph_service.py`
**depends_on**: `[W3-1C]`

改动:
- Import graph analysis (静态分析推断 write_set)
- Test impact detection
- Verification hook (轻量 build/lint 检查)
- Push results to inbox (不等 AI 查询)

---

#### Task W4-F: Board 拖拽

**write_set**: `web/src/components/app/BoardTabContainer.tsx`
**depends_on**: `[]`

改动:
- dnd-kit 集成 (@dnd-kit/sortable + rectSortingStrategy)
- 拖拽后调用 cccc_task move API

---

#### Task W4-G: 前后端 Schema 共享 + CI 契约漂移检测

**write_set**: 新建 `scripts/generate_ts_types.py`, CI 配置
**depends_on**: `[]`

改动:
- Pydantic schema → TypeScript types 自动生成
- CI 检测后端字段变了但前端没更新

---

#### Task W4-H: retire/decommission 替代 hard remove

**write_set**: `kernel/actors.py`, `daemon/actors/actor_membership_ops.py`
**depends_on**: `[W3-1B]` (需要服务主体)

改动:
- `retire_actor()` 替代 `remove_actor()`
- 默认 UI 隐藏 retired actor，审计和历史 assignment 保留

---

### Wave 4 依赖图

```
独立任务（可按需并行，最多 8 路）:

W4-A (worktree)  ← W3-1C
W4-B (断路器)    ← W2-2A
W4-C (model)     ← 无
W4-D (contract)  ← 无
W4-E (ralph++)   ← W3-1C
W4-F (dnd)       ← 无
W4-G (schema CI) ← 无
W4-H (retire)    ← W3-1B
```

---

## 全局依赖总览

```
Wave 1 + 1.5 ✅ (已完成)
  batch-0 → batch-1A,1B (并行) → batch-2
  batch-1C (与 batch-0 并行)

Wave 2 (止血)
  W2-0A → W2-1A,1B,1C,1D,W2-3A (5并行) → W2-2A,2B (2并行)

Wave 3 (治理)
  W3-0A → W3-1A,1B,1C,1D,1E (5并行)

Wave 4+ (演进)
  W4-A~H (8个独立任务，按需并行)
```

## 执行统计

| Wave | 总 Task 数 | Phase 数 | 最大并行度 | 状态 |
|------|-----------|---------|-----------|------|
| Wave 1+1.5 | 5 | 3 | 2 | ✅ 完成 |
| Wave 2 | 8 | 3 | 5 | ✅ 完成 |
| Wave 3 | 6 | 4 | 3 | ✅ 完成 |
| Wave 4+ | 8 | 1 | 8 | ✅ 完成 |
| **总计** | **27** | **11** | — | — |

### 冲突检查记录
- **Wave 2**: Codex 验证 write_set 无交集 ✅ 安全
- **Wave 3**: Codex 发现 3 处冲突 ❌ → 已修正为 4 phase (从 2 phase 5 并行 → 4 phase 最大 3 并行)
  - W3-1A→W3-2A: 依赖 W3-1B 权限放行先到位
  - W3-1D→W3-3D: enabled 被 10+ 处依赖，改动面远超原 write_set
  - W3-1B write_set 补充: 需改 context_ops.py
- **Wave 4**: 各 Task 独立，无交集 ✅ 安全
