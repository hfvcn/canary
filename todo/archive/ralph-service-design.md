# Ralph Service 架构设计 — 从文档概念到真实服务

> 由 Claude (Opus) 与 Codex 协作讨论后达成的共识。
> 解决核心问题：Ralph 只有 transport 壳子没有领域逻辑，workflow 热路径不应绑定 MCP。

---

## 0. 现状诊断

**Ralph 不是"外部进程缺了一半"，而是"领域逻辑根本没实现"。**

| 组件 | 设计文档说 | 实际状态 |
|------|-----------|----------|
| Ralph 守护进程 | 外部 Python 进程，监控 Git，计算依赖图 | **不存在** |
| ralph_ipc_handler.py | 接收 Ralph 的 IPC 消息 | 壳子，等着不存在的 producer |
| ReadyBatchSuggestion | Ralph 分析后推送给 Daemon | 只能通过 HTTP/MCP 手动提交 |
| 依赖图分析 | Ralph 核心能力 | **不存在** |
| Git 变更监控 | Ralph 核心能力 | **不存在** |
| WorkflowOrchestrator | 接收 Ralph 建议，评估并执行 | 存在但从没收到过真正的 Ralph 建议 |
| Foreman AI | 调度控制层 | 被迫同时做观察+分析+调度，依赖 MCP 全量加载 |

**当前 workflow 运作方式**：人工/AI 通过 MCP → daemon op → orchestrator。AI 做了"本应 Ralph 做的事"，但必须先加载完整 MCP server。

---

## 1. 架构决策

### 1.1 Ralph 形态：Daemon 内部服务 (先 B，后 D)

**选定方案**：先做 `RalphService` 作为 daemon 内部模块，不造独立进程。

**理由**：
- 独立进程 (A) 引入第二套生命周期/IPC/状态一致性，复杂度远超收益
- 纯提示词驱动 (C) 没有持久状态/事件订阅/幂等保证，不适合做核心逻辑
- daemon 内部模块直接复用 group state、repo 路径、control-plane

**演进路线**：
```
Phase 1: RalphService in daemon (内部模块)
   ↓ 跑稳后
Phase 2: 如果 repo watcher / indexer 变重 → 拆成 sidecar
   ↓ 如需跨机器
Phase 3: 独立进程 + IPC
```

### 1.2 领域能力与调用协议解耦

**核心原则**：AI 能不能用 MCP，不应决定 workflow 能不能跑。

```
                    RalphService (领域核心)
                    ┌─────────────────────┐
                    │ analyze_repo()       │
                    │ suggest_ready_batch()│
                    │ apply_task_event()   │
                    │ get_snapshot()       │
                    │ check_dependencies() │
                    └──────┬──────────────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
          HTTP route   daemon op    CLI command
          (web/routes) (ralph_ipc   (cccc-cli)
                       _handler)
              │            │
              │       MCP adapter
              │       (薄封装,
              │        非必需)
```

### 1.3 MCP 职责收缩

| 场景 | 当前 | 目标 |
|------|------|------|
| 批次建议 | MCP → daemon | RalphService 自动分析 → 推送 inbox |
| 进度查询 | AI 主动 MCP 查询 | RalphService push snapshot → context/inbox |
| 任务事件 | MCP → daemon | HTTP/daemon op 直接调用 |
| 消息协作 | MCP | 保留 MCP (协作可见性) |
| 任务板 | MCP | 保留 MCP (人工可见) |
| 记忆 | MCP | 保留 MCP |

---

## 2. RalphService 核心接口

```python
# src/cccc/daemon/foreman/ralph_service.py (新建)

class RalphService:
    """
    Ralph — 观察层服务。
    分析仓库状态，计算任务依赖，建议并行批次。

    不是独立进程，而是 daemon 内部服务。
    """

    def __init__(self, project_root: Path, group_id: str):
        self.project_root = project_root
        self.group_id = group_id
        self._dep_graph: Optional[DependencyGraph] = None

    # === 核心分析能力 ===

    def analyze_repo(self) -> RepoAnalysis:
        """分析仓库状态：Git diff, 文件变更, 依赖关系。"""
        # Phase 1: git diff + changed files
        # Phase 2: import graph / dependency detection
        # Phase 3: test/build impact analysis

    def suggest_ready_batch(
        self,
        tasks: List[TaskRef],
        constraints: Optional[BatchConstraints] = None,
    ) -> ReadyBatchSuggestion:
        """
        给定一组任务，分析依赖关系，返回可并行的批次建议。

        核心逻辑：
        1. 解析每个任务的 write_set (从 claimed_paths 或推断)
        2. 检查 write_set 交集 → 有交集的不能并行
        3. 检查 depends_on → 依赖未完成的不能进入当前批次
        4. 输出: 一组 write_set 无交集且依赖已满足的并行任务
        """

    def check_dependencies(self, task_id: str) -> DependencyStatus:
        """检查某个任务的前置依赖是否满足。"""

    # === 事件处理 ===

    def apply_task_event(self, event: TaskEvent) -> EventResult:
        """
        统一处理任务事件 (completed/failed/stalled/blocked)。
        幂等去重 + assignment 有效性校验 + 状态推进。
        """

    # === 状态查询 ===

    def get_snapshot(self) -> WorkflowSnapshot:
        """返回 kind + reason_code + snapshot 结构。"""

    # === Git 观察 (Phase 1 最小实现) ===

    def get_changed_files(self, since_ref: str = "HEAD~1") -> List[str]:
        """获取自某个 ref 以来的变更文件列表。"""

    def detect_write_set_conflicts(
        self,
        assignments: List[TaskAssignment],
    ) -> List[WriteConflict]:
        """检测多个 assignment 之间的 write_set 冲突。"""
```

---

## 3. "MCP 转一般工具" 的具体含义

### 3.1 当前链路 (AI 必须走 MCP)

```
AI Agent (Foreman/Worker)
  → MCP server 启动 + 全量工具加载 (开销大)
    → cccc_coordination / cccc_task / cccc_message_send
      → daemon IPC
        → handler
          → orchestrator
```

### 3.2 目标链路 (workflow 热路径不依赖 MCP)

```
RalphService (daemon 内部)
  → 自动分析 repo 变更
  → 生成 ReadyBatchSuggestion
  → 推送到 Foreman inbox / context (无需 AI 主动查询)

Foreman AI
  → 读取 inbox 中的 batch 建议 (轻量读取, 不需全量 MCP)
  → 通过 HTTP API / CLI 确认/修改/拒绝 (不需 MCP)
  → 或者: auto_process=true 时 RalphService 直接交给 Orchestrator

Worker AI
  → 收到任务 prompt (由 Foreman 发送)
  → 执行完成后通过 HTTP API 报告 (不需 MCP)
  → 或者: daemon 自动检测 worker idle/done → RalphService 推进状态

MCP 只用于:
  → cccc_message_send (协作可见消息)
  → cccc_memory (长期记忆)
  → cccc_inbox_list (人工查看)
```

### 3.3 Prompt 改进

当前 worker prompt:
```
Report via cccc_message_send(to="@foreman", text=...).
```

目标 worker prompt:
```
Report completion:
  - Primary: daemon will auto-detect task completion via git/file changes
  - Fallback: POST /api/v1/groups/{gid}/workflow/task/completed
  - For human-visible updates: cccc_message_send(to="@foreman", text=...)
```

---

## 4. 实现路线

### Phase 0 (前置): 提取 RalphService 骨架

| 改动 | 文件 | 说明 |
|------|------|------|
| 新建 RalphService | `daemon/foreman/ralph_service.py` | 空骨架 + 接口定义 |
| Orchestrator 接入 | `daemon/foreman/workflow_orchestrator.py` | `self.ralph = RalphService(...)` |
| Handler 退化为 adapter | `daemon/ralph_ipc_handler.py` | 委托给 `RalphService` |

### Phase 1 (Wave 1 同步): 最小可用 Ralph

| 能力 | 实现 |
|------|------|
| `get_changed_files()` | `git diff --name-only` 封装 |
| `get_snapshot()` | 委托 ProgressReporter + kind/reason_code 包装 |
| `apply_task_event()` | 幂等事件处理 + assignment 校验 |
| `suggest_ready_batch()` | 基于 write_set 交集检测的简单版 |

### Phase 2 (Wave 2 同步): Ralph 支撑止血能力

| 能力 | 实现 |
|------|------|
| `detect_write_set_conflicts()` | 支撑 single_writer → claimed_paths 过渡 |
| `check_dependencies()` | 基于 depends_on 字段的简单 DAG 检查 |
| heartbeat sweep | RalphService 的周期任务，检测 stalled/offline |
| auto-detect completion | 监测 worker actor 的 git commit / file changes |

### Phase 3 (Wave 3+): Ralph 智能化

| 能力 | 实现 |
|------|------|
| Import graph analysis | 静态分析推断 write_set |
| Test impact detection | 哪些测试受变更影响 |
| Verification hook | build/test/lint 自动验证 |
| Push to inbox | 分析结果主动推送而非等 AI 查询 |

---

## 5. 和 workflow-fix-plan.md 的关系

这份设计不替代 workflow-fix-plan.md (Rev.2)，而是为它补充**架构基座**：

- Wave 1 的 `ralph_task_event` → 改为 `RalphService.apply_task_event()` 的 handler adapter
- Wave 1 的 `kind+reason_code+snapshot` → 改为 `RalphService.get_snapshot()` 的返回结构
- Wave 1 的 `resolve_group_runtime_context()` → RalphService 初始化时的参数
- Wave 2 的 single_writer / heartbeat → RalphService 的 `detect_write_set_conflicts()` 和周期 sweep
- Wave 3 的 claimed_paths / 依赖门控 → RalphService 的 `suggest_ready_batch()` 和 `check_dependencies()`

**Ralph 不是 Wave 4+ 的事，而是 Wave 1 就应该开始落的基座。**
