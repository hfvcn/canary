# CCCC Workflow Issues — 2026-03-26

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



---

## 修复优先级

| 优先级 | 编号 | 修复工作量 |
|--------|------|-----------|
| P0 立即修 | BUG-01, KB-BUG-01, KB-BUG-02, WF-01, WF-02 | 中 |
| P1 尽快修 | BUG-02, BUG-03, KB-BUG-03, WF-03, WF-04, WF-05, WF-06 | 中-大 |
| P2 改进 | BUG-04, BUG-05, KB-BUG-04, WF-07, WF-08, WF-09 | 小-中 |
| P3 后续 | KB-BUG-05, WF-10 | 大 |
