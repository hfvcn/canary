# Wave 1 + 1.5 Parallel Task Decomposition (Rev.2)

> 整合了设计文档 gap 检查后的完整并行拆分。
> write_set 无交集的 Task 可安全并行执行。

---

## 设计 Gap 整合记录

经系统性检查 `docs/ralph-foreman-workflow.md` 与 fix plan，发现 7 个遗漏的设计理念：

| # | 遗漏 | 影响 | 整合到 |
|---|------|------|--------|
| G1 | Ralph 不存在，只有 transport 壳子 | Foreman 被迫做观察+调度 | Batch 0 (RalphService 骨架) |
| G2 | MCP 转一般工具未实现 | workflow 热路径强绑 MCP | Batch 1B (route 改为不依赖 MCP) |
| G3 | Agent↔Actor 契约有损转换 | role_type/task_affinity/capabilities 丢失 | 记录但不在 Wave 1 修 |
| G4 | Agent Pool 模型适配分经常失效 | registry key != runtime，0-10 分失效 | 记录但不在 Wave 1 修 |
| G5 | 验证循环完全缺失 | 无 build/test/lint 自动验证 | Batch 0 (RalphService 预留接口) |
| G6 | 两套状态模型未映射 | ralph_ipc 状态 vs admin_hold/stalled | Batch 1A (统一映射) |
| G7 | 三层分离被打破 | Orchestrator 同时承担观察+调度+执行 | Batch 0 (RalphService 剥离观察职责) |

---

## Batch 0 — 契约基座 + RalphService 骨架（串行）

### Task batch-0-contract-and-ralph: 契约补齐 + RalphService 骨架 + handler adapter

**write_set**:
- `src/cccc/contracts/v1/ralph_ipc.py`
- `src/cccc/daemon/ralph_ipc_handler.py`
- `src/cccc/daemon/foreman/ralph_service.py` (新建)

**depends_on**: `[]`

**改动要点**:

1. `ralph_ipc.py` — 新增 TaskEvent model + 状态映射注释:
   ```python
   class TaskEvent(BaseModel):
       event_type: Literal["completed", "failed"]
       task_id: str
       assignment_id: str
       actor_run_id: str = ""
       idempotency_key: str = ""
       occurred_at: str = Field(default_factory=utc_now_iso)
       payload: Dict[str, Any] = Field(default_factory=dict)
   ```

2. `ralph_service.py` (新建) — RalphService 骨架:
   ```python
   class RalphService:
       """观察层服务 — 分析仓库、计算依赖、建议并行批次。"""
       def __init__(self, project_root: Path, group_id: str): ...
       def get_changed_files(self, since_ref="HEAD~1") -> List[str]: ...
       def suggest_ready_batch(self, tasks, constraints=None) -> ReadyBatchSuggestion: ...
       def apply_task_event(self, event: TaskEvent) -> EventResult: ...
       def get_snapshot(self) -> Dict[str, Any]: ...
       def check_dependencies(self, task_id) -> DependencyStatus: ...
       def detect_write_set_conflicts(self, assignments) -> List[WriteConflict]: ...
       # Phase 2+: verify_completion(), run_lightweight_checks()
   ```

3. `ralph_ipc_handler.py` — 退化为 adapter:
   - `handle_ralph_task_event()` 委托给 `RalphService.apply_task_event()`
   - `handle_ralph_workflow_progress()` 委托给 `RalphService.get_snapshot()`
   - 无 orchestrator 时返回 `kind="unavailable"` 的完整结构

**解决的设计 gap**: G1 (Ralph 不存在), G5 (验证接口预留), G7 (观察职责剥离)

---

## Batch 1 — 并行组（Batch 0 完成后，三个 Task 同时执行）

> write_set 互不重叠 ✓

### Task batch-1A-backend-progress-shape: kind + snapshot 后端响应 + 状态映射

**write_set**:
- `src/cccc/daemon/foreman/workflow_orchestrator.py`
- `src/cccc/daemon/foreman/progress_report.py`

**depends_on**: `[batch-0-contract-and-ralph]`

**改动要点**:
1. `workflow_orchestrator.py`:
   - `get_workflow_state()` 返回 `kind + reason_code + snapshot` 结构
   - 接入 `RalphService`：`self.ralph = RalphService(project_root, group_id)`
   - 新增 `apply_task_event()` 委托给 `self.ralph.apply_task_event()`
   - **状态映射** (解决 G6): ralph_ipc 的 `idle/analyzing/executing/waiting/blocked/completed` 映射到 snapshot 里的 assignment 状态
2. `progress_report.py`:
   - idle 分支返回完整固定 shape snapshot
   - running 时 snapshot 包含真实数据

**解决的设计 gap**: G6 (状态映射)

---

### Task batch-1B-route-runtime-context: resolve_group_runtime_context + MCP 解耦

**write_set**:
- `src/cccc/ports/web/routes/workflow.py`

**depends_on**: `[batch-0-contract-and-ralph]`

**改动要点**:
1. 新增 `resolve_group_runtime_context(ctx, group_id)` helper
2. `get_workflow_progress()` 使用此 helper
3. `report_task_completed/failed` 改为调用 `ralph_task_event` op（薄转发）
4. **确保所有 workflow HTTP route 可独立于 MCP 使用** (解决 G2)：
   - 这些 route 是 RalphService 的 HTTP adapter
   - Worker 完成任务可直接 POST 到这些 route，不需要走 MCP

**解决的设计 gap**: G2 (workflow 热路径不依赖 MCP)

---

### Task batch-1C-tab-container: Tab registry + container 模式

**write_set**:
- `web/src/App.tsx`
- `web/src/components/app/AppShell.tsx`
- `web/src/components/app/BoardTabContainer.tsx` (新建)
- `web/src/components/app/WorkspaceTabContainer.tsx` (新建)
- `web/src/components/app/PanoramaTabContainer.tsx` (新建)

**depends_on**: `[]` (可与 Batch 0 并行)

**改动要点**:
1. 新建三个 container：各自从 store 直连取数据
2. `AppShell.tsx`: Tab registry + 纯壳层
3. `App.tsx`: 移除 Board/Workspace prop drilling

---

## Batch 2 — 前端契约对齐（Batch 1A 完成后）

### Task batch-2-frontend-progress-types: WorkflowProgress 类型同步

**write_set**:
- `web/src/services/api.ts`
- `web/src/stores/useWorkflowStore.ts`

**depends_on**: `[batch-1A-backend-progress-shape]`

**改动要点**:
1. `api.ts`: WorkflowProgress 改为 `kind + reason_code + snapshot`
2. `useWorkflowStore.ts`: `refreshProgress()` 按 kind 消费
3. 状态类型扩展

---

## 依赖图

```
    batch-0-contract-and-ralph       batch-1C-tab
    (ralph_ipc.py + handler          (AppShell + containers)
     + RalphService 骨架)            [可与 Batch 0 并行]
           │
    ┌──────┴──────┐
    │             │
  batch-1A     batch-1B
  (orchestrator  (workflow.py
   + reporter     route + MCP解耦)
   + 状态映射)
    │
  batch-2
  (api.ts + store)
```

## 执行策略

| 阶段 | Task | Worker 数 | 说明 |
|------|------|----------|------|
| Phase 1 | batch-0 + batch-1C | 2 Codex 并行 | 后端契约/骨架 + 前端 Tab |
| Phase 2 | batch-1A + batch-1B | 2 Codex 并行 | 后端响应+状态映射 + 路由 |
| Phase 3 | batch-2 | 1 Codex | 前端类型对齐 |

## 不在 Wave 1 修但已记录的设计 gap

| Gap | 计划修复时间 | 说明 |
|-----|-------------|------|
| G3: Agent↔Actor 契约有损转换 | Wave 3 | role_type/task_affinity 需要映射到 Actor |
| G4: Agent Pool 模型适配分失效 | Wave 3 | registry key 与 runtime 的映射问题 |
| G5: 验证循环完整实现 | Wave 2+ | RalphService 骨架已预留接口 |
