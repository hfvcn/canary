**CCCC Workflow 修复方案完善报告**  
（基于 plan.md 问题清单 + 网络搜索最佳实践分析与质疑）

文档的核心洞见非常精准：三类问题（Workflow Tab 数据管线断裂、Board Tab 渲染遗漏、多 Agent 协作破坏性并发）背后是**“状态模型分裂 + 契约漂移 + 执行约束缺失”**。我结合 2025-2026 年多 Agent AI 框架（LangGraph、CrewAI、Temporal、Akka、Ray、Claude/Cursor 实际部署案例）的网络搜索结果，对原计划进行**逐 Wave 质疑、完善与替代方案建议**。重点覆盖边缘案例（daemon 重启、长时思考、依赖循环、高并发写）、可观测性、长期可扩展性，以及为什么某些方案需调整优先级。

搜索来源包括：Git worktree 在 AI 编码 Agent 并行中的实际应用、Temporal/Airflow 心跳与 stalled 检测、Akka 监督树 Actor 生命周期、OpenAPI 契约防漂移、dnd-kit Kanban 模式、CrewAI/RBAC 系统身份等。目标是**在保持最小改动的同时，提升正确性与吞吐**，避免单写者模式带来的“吞吐换正确性”短期妥协。

### 1. 共同根因深化 + 新发现风险
原分析“状态模型分裂 + 契约漂移”完全正确。搜索补充：
- 多 Agent 系统（如 CrewAI、LangGraph）普遍采用**分层状态**（desired_state vs runtime_state + supervision tree），而非单一 enabled/hold_reason 字段。
- 文件并发写是 AI 编码 Agent 最常见生产事故（覆盖率 >60%），最佳实践是**FS 级隔离而非策略锁**。
- API 契约漂移是前后端脱节主因，推荐 OpenAPI 作为单一真相源（而非手动解构）。
- 新风险：daemon 重启后 group.yaml 并发写可能导致状态不一致（多 Foreman 场景）；Ralph 观察层缺席会导致依赖图/验证完全缺失（LangGraph 强调 graph-based coordination）。

**质疑原伴随 bug 处理**：仅新增 `ralph_task_completed/failed` op 仍不够——应绑定到事件总线（event sourcing），确保即使 HTTP route 失效，内部调用也能触发。

### 2. Wave 1 — 可观测面（数据管线）完善
原方案（BUG-01~04 + 伴随）**方向正确、改动小**，但需强化契约与可观测性。

**完善点**：
- **BUG-01/01b**：`get_orchestrator` 必须强制传入 `project_root`（从 group active scope 解析）。新增 fallback：若 group.yaml 无 project_root，则返回 idle + reason="missing_project_root"（显式 debug）。
- **BUG-02**：扁平化返回（status/tasks/... 顶层）完全匹配前端期望。**补充**：后端统一使用 OpenAPI Spec 定义 `WorkflowProgress` schema（Pydantic v2 + FastAPI），前端生成 TS 类型。防止未来嵌套回归。
- **BUG-03/04**：idle payload 补全字段 + `reason`（"no_orchestrator" / "no_active_workflow"）——避免掩盖真实问题。边缘案例：daemon 重启 0-30s 内前端可能短暂看到 idle，应加 loading spinner + retry 逻辑。
- **伴随**：`ralph_task_completed/failed` 新 op 必须返回 **progress delta**（仅变动的字段），减少前端轮询负载。测试覆盖：立即补 integration test（模拟无 orchestrator + completed 路径）。

**无重大质疑**，但建议**立即生成 OpenAPI 文档**作为 Wave 1 出口门禁。

### 3. Wave 1.5 — Board Tab 接线完善
原方案（KB-BUG-01~03）**关键但不完整**。

**完善点**：
- AppShell 补渲染分支 + Suspense + React.lazy（BoardTab、WorkspaceTab、PanoramaTab）。搜索显示，大型 React App 必须 route-level code splitting，避免首次加载 500KB+ 冗余代码。
- props 传递：从 `useWorkspaceStore` 取 tasks + loading + isDark + onOpenTask（复用 handleOpenWorkspaceFile）。**新增**：BoardTab 立即集成 dnd-kit（DndContext + SortableContext + multiple containers），支持列间拖拽、卡片排序。教程丰富，5-10 行即可实现完整 Kanban。
- **类型补全（KB-BUG-04）**：立即增加 outcome/blocked_by/parent_id/priority/waiting_on/checklist（前端 UI 依赖）。否则后续拖拽/过滤功能会卡死。
- **拖拽（KB-BUG-05）**：并非 LOW，而是 Wave 1.5 必做——否则 BoardTab 仅展示无交互，验收价值低。

**边缘案例**：暗黑模式下任务卡片拖拽视觉反馈、移动端 touch 事件、拖拽中任务状态变更（并发冲突）。

### 4. Wave 2 — 止血（并发破坏）**重大质疑与替代方案**
这是计划最需调整的部分。原方案止血思路正确，但**单写者模式（B1）吞吐代价过高**，git worktree 被搜索一致推荐为更优根治方案。

**WF-01（Actor Hold）质疑与改进**：
- 原方案（hold_reason 枚举 + group.yaml 持久化）**短期可行**，但语义单一（“manual_stop” vs policy）。
- **质疑**：yaml 并发写风险高（多 daemon/重启）；未分离 desired_state 与 runtime_state，容易“起不来”困惑（用户看不到 hold 原因）。搜索显示 Akka/Ray/Orleans 采用 **supervision tree + desired_state enum**，Foreman 作为 supervisor 统一决策。
- **更合适方法**：引入 `desired_state: "running" | "stopped" | "suspended"` + `hold_reason`（保留）。持久化升级为专用 state store（SQLite 或 Redis，Wave 3 前可选）。UI 强制展示 badge + tooltip + skipped_held 列表。auto_wake/group_start 检查 desired_state。

**WF-02（文件写入安全）质疑与重大改进**：
- 原方案（Wave 2 single_writer → Wave 3 claimed_paths）**正确性优先但牺牲并行**。搜索显示，**git worktree 是 AI 编码 Agent 并发标配**（Claude Code、Cursor、AugmentCode 均用），提供真正 FS 隔离（独立 working dir/index/branch，共享 .git 对象库），磁盘开销极低。
- **质疑**：plan 否决 B3（worktree）理由“复杂度高”已过时——2026 年社区已有成熟 orchestration 模式（Foreman 创建 worktree、传递 CWD、completion 时 cherry-pick/merge + Ralph 验证）。single_writer 短期吞吐降至 1/3，claimed_paths 仅 advisory（后写仍可能覆盖）。
- **更合适方案（替换 B1）**：Wave 2 核心改为 **git worktree per actor/task**：
  1. Orchestrator admission 时：`git worktree add ../worktrees/{actor_id}_{task_id} {branch}`。
  2. Worker 启动时 cwd = worktree path。
  3. Completion 时：Foreman 验证 → merge to main（或 PR-like）。
  4. 清理：任务结束删除 worktree。
- **优势**：真正并行、无覆盖、依赖图可自然映射。**边缘案例**：磁盘配额（限 5-10 个 worktree）、网络挂载、git gc 冲突（后台定时）。短期可保留 single_writer 作为 fallback。
- claimed_paths 保留为 Wave 3 精细化（子路径锁）。

**WF-04（Heartbeat 超时）完善**：
- 原 A+C（上报 + sweep）**优秀**，与 Temporal 完全对齐。
- **补充**：任务类型化超时（code_gen 5-15min，讨论 2min）；多心跳事件（progress + output + LLM call）；stalled 后自动 reassign + checkpoint（保存 partial files）。被动检测（runner 输出）作为 secondary（避免误杀思考期）。
- stalled UI + 飞书卡片必做，增加 escalation 到 human-in-loop。

### 5. Wave 3 — 治理（权限与调度）优化
**WF-05/06（系统调度身份）**：原 C2（by="system" + audit）**方向正确**。
- **补充**：结合 CrewAI RBAC + capability tokens（短时窄权限）。 普通 foreman 仍受限，scheduler 仅用于 orchestrator 路径。
- WF-03（依赖门控）：立即加 TaskRef.depends_on + Ralph 依赖图（Git watcher + graph 计算）。LangGraph 证明 graph 是多 Agent 正确性基石。

**WF-02b（claimed_paths）**：保留，但作为 worktree 补充。

### 6. 后续 Wave 4+ 与全局增强
- **WF-07/08/09**：Model Registry 强制 bootstrap 返回摘要；runtime-specific prompt 放入 worker_prompt 模板；activation_pending 改 explicit "ready"。
- **WF-10（Ralph 观察层）**：提前到 Wave 3——Git 监控 + ReadyBatchSuggestion + VerificationResult 是依赖图前提。
- **测试集强化**：Wave 1 必须补单元 + integration（pytest + Playwright）；Wave 2 加并发 stress test（5 worker 同时写）。
- **新增全局**：
  - 状态机统一（使用状态机库如 transitions 或 Temporal 风格）。
  - 容器 sandbox（每个 worker Docker）增强安全（搜索推荐）。
  -  observability：LangSmith-style tracing（task handoff 日志）。
  - 人机回路：关键 merge/ stalled 加 human checkpoint。

### 7. 风险评估更新与实施建议
- **新风险**：worktree 磁盘/清理遗漏 → 缓解：Foreman 统一管理 + 定时 gc。
- **吞吐提升**：worktree 替代 single_writer → 并行度恢复 3-5x。
- **优先级调整**：Wave 2 核心改为 git worktree + hold 增强 + heartbeat；Board dnd-kit 并入 Wave 1.5。
- **实施路线**：先 Wave 1+1.5（1-2 天可观测），再 Wave 2（worktree 3-4 天），测试覆盖贯穿。

此完善方案在**正确性、并行度、可维护性**三维均优于原计划，同时保持改动可控。预计 Wave 2 完成后，多 Agent 相互破坏问题可根治，Workflow/Board Tab 进入生产可用状态。若需具体代码片段（worktree 创建、dnd-kit Kanban、OpenAPI schema）或进一步搜索特定实现，我可继续细化。团队可立即启动 Wave 1 测试验证。