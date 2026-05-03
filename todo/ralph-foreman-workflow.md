# Ralph-Foreman 工作流系统

> 最后更新：2026-04-03（v4 E2E 实战后 + 设计意图正式确立）
> 前置阅读：todo/findings.md（11 条实践教训）、todo/设计偏移发现记录.md

---

## 0. 当前状态概要

| 层 | 设计目标 | 实际状态 |
|----|---------|---------|
| **Ralph（独立工具）** | 计划校验 + 任务调度 + 执行时验收 | ✅ CLI 可用，validate/suggest/verify/explain 四命令 |
| **Ralph（daemon 内）** | 观察层，verify gate | ✅ v4 实战验证：task complete → verifying → completed 链路生效 |
| **Foreman prompt** | 引导使用 workflow submit | ✅ v4 实战验证：零手工 cccc send，自动下发 [Foreman Assignment] |
| **Worker prompt** | 引导使用 task complete | ✅ v4 实战验证：4/4 任务通过 cccc task complete 完成 |
| **MCP → CLI 迁移** | MCP 工具从 AI 上下文中移除 | ✅ 已完成，CLI 为唯一主路径 |
| **Verify gate** | task complete → verifying → completed/failed | ✅ v4 验证：checks 非空，outcome=passed |
| **Foreman 主导 worker 决策** | Foreman 判断并创建 worker，引擎不自动兜底 | ❌ 代码仍有自动分配和静默 fallback，待修正（见 ARCH 系列问题）|
| **Engine 为状态唯一权威** | assignment + 状态全进 engine，无影子状态 | ❌ _active_workflows 影子状态仍存在（见 ARCH-4）|

**当前阶段：主路径闭环已在 v4 验证（评分 3.3/5）。下一步是修正架构偏移（ARCH 系列），让 Foreman 真正主导 worker 决策，并消除影子状态。**

> **注**：2026-04-03 本次更新正式确立了从未被写入文档的原始设计意图。此前的版本（03-30）写于 WF-NEW-4 fallback 加入之后，描述的是已实现的状态，不是最初的意图。详见 `todo/设计偏移发现记录.md`。

---

## 1. 整体架构

### 1.1 目标架构

```
用户
 │  (1) 选择模型、配置 agent pool 能力信息
 ▼
Foreman AI
 │  (2) ralph validate plan.yaml        → 结构校验
 │  (3) ralph suggest plan.yaml         → 计算可并行批次
 │  (4) 查看 group 已有 actor
 │       有合适的 → 直接在 submit 中指定 assignment
 │       没有    → 查 agent pool 了解模型能力
 │                → cccc actor add --runtime MODEL --worker-prompt "..." 创建持久化 actor
 │  (5) cccc workflow submit --plan plan.yaml（含明确 assignment）
 ▼
CCCC Daemon
 │
 ├── WorkflowOrchestrator
 │   ├── 接收 Foreman 提交的 batch（已含 assignment）
 │   ├── _start_assigned_agents() → 启动指定 actor，发任务 prompt
 │   ├── 无合适 actor 时 → 向 Foreman 发消息请求指示，不自行解决
 │   └── [不创建 worker，不做静默 fallback]
 │
 ├── Ralph (daemon 内)
 │   ├── suggest_ready_batch()  → 计算可并行批次
 │   ├── verify_completion()    → 执行时验收
 │   └── sweep_stalled_tasks()  → 检测卡住的任务
 │
 └── WorkflowEngine（状态 + assignment 双权威）
     └── task: pending → assigned → running → verifying → completed/failed
         assignment: task_id → actor_id（存在 engine，不在影子状态）

Worker AI ──cccc task complete──→ Daemon → verify gate → 状态推进
```

### 1.2 Agent Pool 设计定位

**Agent Pool 是模型能力信息库，不是自动分配引擎。**

| 职责 | 归属 |
|------|------|
| 存储模型能力描述（擅长/不擅长/context window）| Agent Pool |
| 存储用户主观评估和 Foreman 实践简评 | Agent Pool |
| 决定用哪个模型创建 worker | **Foreman** |
| 创建持久化 actor（cccc actor add）| **Foreman** |
| 查看已有 actor 并复用 | **Foreman** |
| 自动创建泛型 worker | ❌ 不应发生 |
| 无合适 agent 时自动 fallback | ❌ 不应发生 |

### 1.3 v4 实战后的实际行为（已生效）

```
Foreman AI ──cccc workflow submit --plan plan.yaml──→ Daemon
                                                       │
                                          [Foreman Assignment] 自动发至 Worker inbox
                                                       │
Worker AI ──cccc task complete TASK_ID──→ Daemon → verify gate → completed
```

**v4 验证生效**：零手工 cccc send，DAG 门控生效，verify gate 执行，4/4 任务自动闭环。

**尚未修正的偏移**（ARCH 系列，见 `问题清单.md`）：
- orchestrator 仍有自动 worker 创建和静默 fallback
- engine 不存 assignment，影子状态仍在
- submit 接口无 assignment 字段

---

## 2. Ralph 独立工具（已完成，可用）

Ralph 已从 daemon 中抽取为独立 CLI 工具，可脱离 CCCC 使用。

### 2.1 核心定位

**Foreman 的质检搭档**：Foreman 自由规划 → Ralph 立即校验并反馈不足 → Foreman 据此修正。循环越紧密，对 Foreman 精确度的依赖越低。

Ralph 当前有三种形态：
- **CLI 静态验证**（`ralph validate`）— 计划结构校验
- **daemon 内 verify gate** — 任务完成时运行 verification checks
- **Agent 审查** — 基于 Agent 的对抗式语义审查

### 2.2 CLI 命令

```bash
ralph validate plan.yaml          # 结构性检查（27 条规则），exit 1 = 有 error
ralph validate plan.yaml --format json  # JSON 输出给 AI 消费
ralph suggest plan.yaml           # 输出 ready batch + blocked reasons（含 waiting/deferred 分类）
ralph explain plan.yaml --task T1 # 解释为什么某任务被阻塞
ralph verify plan.yaml --task T1  # 执行验证命令
```

### 2.3 Plan 文件格式

Plan YAML 是唯一真相源，Ralph 只读不改。

```yaml
required_issues: ["R-1", "R-2"]  # 必须被 addresses 的问题

tasks:
  - id: T1
    title: "..."
    role: leaf | integration | verification
    depends_on: ["T0"]
    claimed_paths: ["src/module_a/"]
    addresses: ["R-1"]
    goal_behavior: "..."
    acceptance_criteria: "..."
    verification:
      level: compile | unit | integration | e2e
      command: "pytest tests/test_a.py -q"
      covers:
        tasks: ["T0", "T1"]
        flows: ["flow_id"]
    provides:
      - name: module_a_ready
        kind: runtime_capability
    consumes:
      - name: config_loaded
        from: T0

critical_entrypoints:
  - src/main.py

critical_flows:
  - id: startup_loads_module_a
    description: "..."
    entrypoints: ["src/main.py"]
    required_verification_level: integration

forbidden_flows:
  - id: progress_update_cannot_complete
    description: "旧路径不能改变状态"
    required_verification_level: e2e

state:
  completed_task_ids: []
  running_tasks: []
  failed_task_ids: []
```

### 2.4 校验规则（27 条）

| 分类 | 规则 | 严重度 |
|------|------|--------|
| **图结构** | E_DUPLICATE_TASK_ID, E_DEP_UNKNOWN, E_DEP_SELF, E_DEP_CYCLE | error |
| | W_DISCONNECTED_COMPONENTS, W_ISOLATED_TASK | warning |
| **字段完整性** | E_MISSING_CLAIMED_PATHS, E_MISSING_VERIFICATION | error |
| | W_EMPTY_ACCEPTANCE, W_GLOBAL_WRITE_CLAIM | warning |
| **验收强度** | E_NO_CROSS_TASK_VERIFICATION, E_MISSING_INTEGRATION_SPINE | error |
| | W_WEAK_VERIFICATION_ONLY, W_VERIFICATION_BEHAVIOR_MISMATCH | warning |
| **契约匹配** | E_CONSUMER_WITHOUT_PROVIDER, E_CONSUMER_FROM_UNKNOWN | error |
| | W_PROVIDER_UNUSED, W_CONSUME_WITHOUT_DEP, W_DEP_WITHOUT_CONSUME | warning/hint |
| **关键覆盖** | E_CRITICAL_ENTRYPOINT_UNOWNED, E_CRITICAL_FLOW_UNCOVERED | error |
| | E_CRITICAL_FLOW_ENTRYPOINT_UNOWNED, E_CRITICAL_FLOW_LEVEL_TOO_WEAK | error |
| **禁止流** | E_FORBIDDEN_FLOW_UNCOVERED, E_FORBIDDEN_FLOW_LEVEL_TOO_WEAK | error |
| **问题覆盖** | E_UNCOVERED_REQUIRED_ISSUE | error |
| **集成缝隙** | W_CROSS_BOUNDARY_WITHOUT_GLUE, W_IMPLICIT_SERIALIZATION | warning/hint |

### 2.5 suggest 输出

区分硬阻塞（waiting）和本批次延迟（deferred）：

```json
{
  "ready": ["T1", "T2"],
  "blocked": [
    {"task_id": "T3", "kind": "waiting", "reasons": ["depends_on:T1"]},
    {"task_id": "T4", "kind": "deferred", "reasons": ["claimed_paths_conflict:batch"]}
  ]
}
```

- `waiting`：硬依赖未满足，必须等前置任务完成
- `deferred`：依赖已满足但与本批次其他任务 write-set 冲突，下一批即可 ready

### 2.6 已知限制

1. 无法验证 verification_command 是否可执行（只做结构检查）
2. suggest 算法是顺序贪心（可能非最优批次）
3. 契约只做名字匹配（不做 schema 校验）
4. role 字段存在但 validator 尚未据此强化检查

---

## 3. 工作流状态机

### 3.1 任务状态

```
pending → assigned → running → verifying → completed
                                         → failed → (retry) → pending
```

`verifying` 是关键状态——任务完成后不直接到 completed，必须经过 Ralph verify gate。

### 3.2 谁拥有状态迁移权

| 迁移 | 当前实际触发者 | 应该由谁触发 |
|------|--------------|-------------|
| pending → assigned | Orchestrator (batch process) | 不变 |
| assigned → running | Worker 开始执行 | 不变 |
| running → verifying | **未发生**（Worker 不走 task complete） | Worker 调 `cccc task complete` |
| verifying → completed | **未发生** | Ralph verify_completion() 通过 |
| verifying → failed | **未发生** | Ralph verify_completion() 失败 |
| running → done | **Foreman 通过旧状态变更接口直接改状态** | 不应存在（绕过 verify gate） |

---

## 4. Daemon IPC 操作

| 操作 | 功能 | 关键参数 |
|------|------|----------|
| `ralph_batch_suggest` | 提交 batch 建议 | tasks[], auto_process (**默认 True**) |
| `ralph_task_event` | 任务状态事件 | task_id, event_type, changed_files |
| `ralph_task_verify` | 手动触发验证 | task_id, changed_files |
| `ralph_workflow_progress` | 查询进度 | group_id |
| `ralph_process_pending` | 手动处理待定 batch | suggestion_id |
| `ralph_clear_workflow` | 清理已完成工作流 | workflow_id |

### 关键路径

```
cccc workflow submit → ralph_batch_suggest (auto_process=True)
  → _try_process_batch()
    → get_orchestrator(group_id, project_root=...)
      → WorkflowOrchestrator.process_batch_suggestion()
        → ForemanWorkflow: evaluate_agent_pool → assign_tasks → batch_decision
          → _start_assigned_agents() → actor_add + 发送任务 prompt

cccc task complete → ralph_task_event
  → orchestrator.apply_task_event()
    → 状态 → verifying
      → ralph.verify_completion(task_id, changed_files)
        → 通过 → completed / 失败 → failed
```

---

## 5. Foreman Prompt 架构

### 5.1 Prompt 组装顺序

```
render_system_prompt(group, actor)
  ├── [CCCC] actor identity block
  ├── Working Style
  ├── Platform Invariants
  ├── Role Focus (Foreman/Peer)
  │   └── 包含 workflow submit/status 引导（已加入）
  ├── Memory / Group Space
  └── CCCC_PREAMBLE.md 或 DEFAULT_PREAMBLE_BODY
       └── 包含 workflow 引导（已加入）

+ task_management.yaml (capability 注入)
  └── 包含 workflow-first 指导（已加入）

+ cccc-help.md (帮助文档)
  └── 包含 workflow commands 参考（已加入）
```

### 5.2 Worker 任务分配 Prompt

由 `workflow_orchestrator.py` 动态生成：

```
[Foreman Assignment]
Task ID: {task_id}
Title: {title}

Execute this task only.
Report completion via: cccc task complete {task_id} --changed-file <path> --evidence "..."
Use cccc send --to @foreman --text "..." for progress updates or blockers only.
```

### 5.3 Prompt 稳定性问题（E2E 验证发现）

| 条件 | Foreman 行为 | Worker 行为 |
|------|-------------|-------------|
| 新 session，无历史 | ✅ 使用 workflow submit | 未测到 |
| 有历史上下文 | ❌ 回退到旧 MCP 状态工具 + 进度消息接口 | ❌ 使用 `cccc send` 后再走绕过 verify gate 的旧状态路径 |

**结论：AI 使用旧路径是因为 MCP 工具仍然暴露在上下文中，不是 prompt 引导失败。完成 MCP → CLI 迁移后需重新验证。**

---

## 6. 并行执行模型

### 6.1 Ralph 的并行计算

Ralph `suggest()` 基于两个维度决定并行性：

1. **依赖图**：`depends_on` 中所有前置必须 completed
2. **Write-set 冲突**：`claimed_paths` 不能重叠（含路径包含关系）

```python
# 两个任务可以并行 IFF:
# 1. 都没有未满足的 depends_on
# 2. claimed_paths 之间无路径重叠
# 3. 都不声明 "/" (全局写)
```

### 6.2 执行协议：动态 DAG

不僵化按 Wave 推进。每完成一个任务就更新 `state.completed_task_ids` 并重新 `ralph suggest`。

```
初始: P1 P2 P3 P4 ready
  → P2 先完成 → re-suggest → W1 W2 解锁
  → P1 P3 P4 完成 → re-suggest → W3 解锁
  → 不等 P1 P3 P4 全完成才开始 W1
```

### 6.3 并行的正确理解

> 并行的价值不是"同时做更多事"，而是"通过拆模块降低子任务复杂度 + 分开验收"。

理想流程：
```
拆分（降低子任务复杂度）
  → 并行执行（各自独立完成）
    → 逐个验收（每完成一个就检查，不合格就驳回重试）
      → 组合集成（已验收的模块拼接）
        → E2E 确认（最终确认组合后工作正常）
```

E2E 应该是"确认已验收的模块能组合"，而不是"第一次发现问题"。

---

## 7. 待解决问题（按优先级）

### P0 — 完成 MCP → CLI 迁移

> 当前 AI 使用旧路径不是安全漏洞，是迁移未完成。不需要给旧路径打补丁，需要完成迁移。

| 步骤 | 描述 | 对应问题清单 v3 |
|------|------|----------------|
| MCP 工具移除 | 从 AI 可见上下文中移除旧状态变更 MCP 工具 | M-1 |
| CLI 唯一化 | CLI 成为 AI 唯一可用的操作接口 | M-1 |
| Prompt 收敛 | Prompt 只引导 CLI 用法，不再提及 MCP 备选 | R-1 |
| Ralph 校验 | Ralph 检查 AI 是否正确使用了 CLI | 新 |

### P1 — Ralph v2

| 方向 | 描述 | 来源 |
|------|------|------|
| **注册不变量检查** | 通用的 producer → registry → consumer 三角检查，见下方详述 | v3 架构优化 E2E (2026-04-01) |
| 验证命令预检 | 检查 command 中的文件/函数是否存在 | 已知限制 #1 |
| Flow segment ownership | 关键流每段是否有人负责 | 审查建议 |
| Schema 契约匹配 | 超越名字匹配，检查类型兼容性 | 审查建议 + v3 已实现基础版 |
| Role-based rules | 按 role 字段强化 integration/verification 任务的检查 | 审查建议 |
| Ready 排序 | 按解锁下游数量排优先级 | 审查建议 |
| **test→source 依赖检测** | 改源文件时自动检查哪些测试 claim 了该文件行为，提醒补入 claimed_paths | MCP→CLI 迁移实践 (2026-03-31) |
| **语义依赖推断** | 当 task A provides 某格式、task B 在 goal 中提到消费该格式时，提醒缺 depends_on | MCP→CLI 迁移实践 (2026-03-31) |
| **运行时 agent 行为监控** | 见下方详述 | MCP→CLI 迁移实践 (2026-03-31) |
| **验证命令静态预检** | 检查 command 中引用的 import/文件/pytest 路径是否存在 | Phase 2 计划生成实践 (2026-03-31) |
| **W_UNCLAIMED_TEST_FOR_SOURCE** | 改源文件时检测哪些测试 import 了该文件，提醒 claim | Phase 2 计划生成实践 (2026-03-31) |
| **W_COVERS_CLAIM_UNVERIFIABLE** | 声称 covers 某 task 但 verification 不引用该 task 的文件 | Phase 2 计划生成实践 (2026-03-31) |
| **W_VERIFICATION_BEHAVIOR_MISMATCH 降级** | 被下游 integration/e2e 的 covers.tasks 包含时降为 hint | Phase 2 计划生成实践 (2026-03-31) |

#### 注册不变量检查（Registration Invariant Checking）

> 来源：v3 架构优化 E2E 验证 (2026-04-01)，heartbeat IPC handler 未注册到 dispatch table

**问题的通用抽象**

任何基于查表分发的架构（IPC dispatch、HTTP router、event handler、plugin registry、DI container）中，新增端点必须同时注册到分发表。这是一个 **producer → registry → consumer** 的三角关系：

```
Producer (新端点)          Registry (分发表)          Consumer (处理逻辑)
CLI sends op="X"    →    _OPS["X"] = handler    →    handler(args)
route("/api/X")     →    router.add("X", view)  →    view(request)
event("X.created")  →    handlers["X"] = fn     →    fn(event)
```

当某个 Task 创建了 Producer 和 Consumer 但没有更新 Registry，就会产生"精致的死代码"——每个组件内部正确，但不可达。

**Ralph 不应硬编码项目特定规则（如"检查 IPC handler 文件"），而应提供通用机制：**

```yaml
# 项目级配置（.ralph.yaml 或 plan 顶层），不是 Ralph 内置规则
registration_invariants:
  - name: "IPC op dispatch"
    description: "每个新 daemon op 必须注册到 ralph_ipc_handler"
    registry_file: "src/cccc/daemon/ralph_ipc_handler.py"
    registry_symbol: "_RALPH_OPS"
    # 当 task 的 claimed_paths 中新增了发送某 op 的代码，
    # 检查该 op 是否在 registry 中有对应 entry

  - name: "CLI subcommand parser"
    description: "每个新 CLI 子命令必须在 main.py 中注册 parser"
    registry_file: "src/cccc/cli/main.py"
    registry_symbol: "subparsers.add_parser"

  - name: "HTTP route registration"
    description: "每个新 route handler 必须注册到 router"
    registry_file: "src/cccc/ports/web/app.py"
    registry_symbol: "app.router.add_route"
```

**检查逻辑（通用，不依赖具体项目）**：

1. **扫描 Task 的 claimed_paths**，检测新增的字符串字面量 / 函数调用
2. **匹配 registration_invariant 的 producer pattern**（如新增 `op="X"` 字符串）
3. **检查该 Task 或其依赖 Task 是否 claim 了 registry_file**
4. 没有 → `W_REGISTRATION_INVARIANT_UNCOVERED`

**核心设计原则**：
- **机制通用**：producer → registry → consumer 三角检查适用于所有查表分发架构
- **配置项目特定**：哪些文件是 registry、什么 pattern 是 producer，由项目声明
- **不依赖计划作者声明**：不需要作者手写 provides/consumes 来覆盖注册层——自动从 claimed_paths 检测
- **不依赖代码语义理解**：只需文件级 diff + 字符串匹配，不需要 AST 分析

**与现有 provides/consumes 的区别**：
- provides/consumes 是**声明式**的——依赖计划作者完整声明，容易遗漏"实现细节"级的依赖
- registration_invariants 是**检测式**的——从代码变更中自动发现新端点并验证注册完整性
- 两者互补：provides/consumes 覆盖功能级合约，registration_invariants 覆盖架构级接线

**实际案例**：

v3 架构优化中 T16（heartbeat 功能）创建了：
- Producer: `cmd_task_heartbeat()` 发送 `op="ralph_task_heartbeat"` (在 workflow_cmds.py)
- Consumer: `orchestrator.on_heartbeat()` (在 workflow_orchestrator.py)
- 缺失：`_RALPH_OPS["ralph_task_heartbeat"] = handle_ralph_task_heartbeat` (在 ralph_ipc_handler.py)

如果配置了 registration_invariant，Ralph 会：
1. 发现 T16 的 claimed_paths 中新增了 `"ralph_task_heartbeat"` 字符串
2. 匹配到 "IPC op dispatch" invariant
3. 检查 T16 或其依赖是否 claim 了 `ralph_ipc_handler.py`
4. 没有 → 报 `W_REGISTRATION_INVARIANT_UNCOVERED: task T16 introduces op "ralph_task_heartbeat" but registry file "ralph_ipc_handler.py" is not claimed by T16 or its dependencies`

---

#### Phase 2 计划生成实践发现（2026-03-31 fix-workflow-phase2.yaml）

> 来源：生成 10 任务计划 → Ralph validate → Codex 代码审查 的完整循环

**Ralph 做对了什么**：
- `W_DISCONNECTED_COMPONENTS` 精确定位孤立子图（T3 无边、MCP 链断连），引导修复 T9 依赖
- `W_CONSUME_WITHOUT_DEP` 抓到 T9 消费 T1/T2 但没 depends_on
- `W_PROVIDER_UNUSED` 抓到 T3 的 http_project_root_fixed 没被消费
- 禁止流、关键流覆盖检查全部正确，0 个误报 error

**Ralph 漏了什么（均被 Codex 审查发现）**：

| 漏洞 | 实例 | 建议的规则 | 实现复杂度 |
|------|------|-----------|----------|
| **假验收命令** | T2 写了 `from cccc.daemon.ralph_ipc_handler import RalphIPCHandler`，该类不存在。Ralph 报 valid。 | 验证命令静态预检：对 `python -c "from X import Y"` 检查 Y 是否存在于 X 的 AST 顶层；对 `pytest tests/foo.py` 检查文件是否存在 | 中 |
| **改源漏 claim 测试** | T2 改 `ralph_ipc_handler.py`，但 `tests/test_ralph_ipc.py` 对该文件有硬断言（`get_orchestrator.assert_called_once_with("group-1")` 不带 project_root）。改了源文件必然打碎测试，Ralph 没提醒 claim。 | `W_UNCLAIMED_TEST_FOR_SOURCE`：对 claimed_paths 中每个 `src/X.py`，扫描 `tests/` 下 import 了它的文件，未被任何 task claim 则报 warning | 低 |
| **虚假覆盖声明** | T8 声称 `covers.tasks` 包含 T5（改 `task_management.yaml`），但 T8 指向的 `test_prompt_defaults.py` 只调用 `load_builtin_help_markdown()`，完全不读 YAML。 | `W_COVERS_CLAIM_UNVERIFIABLE`：如果 A covers B 但 A 的 verification.command 和 claimed_paths 均不引用 B 的 claimed_paths，报 warning | 低 |
| **W_VERIFICATION_BEHAVIOR_MISMATCH 过度噪音** | 3 个 leaf 任务全报 warning，但它们都被下游 integration/e2e 任务的 `covers.tasks` 包含——这是完全合理的 leaf+integration 计划模式。10 task 计划里这类 warning 会出现 5-7 次，淹没真正有价值的信息。 | 降级逻辑：当 task T 被某个 `verification.level >= integration` 的 task U 的 `covers.tasks` 包含时，降级为 hint | 低 |
| **语义依赖** | CLI `auto_process` 默认 False（`main.py:517 store_true`）直接影响 T1 的效果，但 `main.py` 不在 T1 的 claimed_paths 里。 | 已列（语义依赖推断），此实例确认优先级应提升 | 高 |

**建议优先级**：`W_UNCLAIMED_TEST_FOR_SOURCE` > 验证命令静态预检 > `W_COVERS_CLAIM_UNVERIFIABLE` > `W_VERIFICATION_BEHAVIOR_MISMATCH` 降级 > 语义依赖推断

前三个可用文件级检查实现，不需要运行命令或分析测试逻辑，投入产出比最高。

#### v3 架构优化计划审查发现（2026-04-01 v3-architecture-optimization.yaml）

> 来源：20 任务计划 → Ralph validate (0 error) → Codex 代码审查 的完整循环

**Ralph 做对了什么**：
- 结构校验准确：0 error 通过
- 隐式串行检测（W_IMPLICIT_SERIALIZATION）抓到多对共享 claimed_paths 的任务
- 禁止流/关键流覆盖检查正确
- 测试覆盖差距（W_TEST_COVERAGE_GAP）准确指出了 12 个相关测试缺口

**Ralph 漏了什么（均被 Codex 审查发现）**：

| 漏洞 | 实例 | 建议的规则 | 实现复杂度 |
|------|------|-----------|----------|
| **注册层缺失（E2E 暴露）** | T16 实现了 heartbeat 的 6 个组件（CLI/engine/orchestrator/state_types），但 IPC dispatch table 中没有 handler entry，导致 CLI 发送的 op 在 daemon 中不可达。所有组件内部正确但不可达 | 通用注册不变量检查 `W_REGISTRATION_INVARIANT_UNCOVERED`（详见 问题清单-v5-ralph.md RO-5） | 高 |
| **claimed_paths 不足以实现 goal** | T16 声称实现 heartbeat CLI，但没 claim main.py（parser 注册）、state_types.py（事件类型）、IPC handler（dispatch 注册）。Codex 审查发现了前两者，E2E 暴露了第三个 | 通用注册不变量 + goal→claimed_paths 一致性检查 | 高 |
| **标题范围 vs claimed_paths 不匹配** | M-1b 标题写"MCP/CLI/HTTP 适配层统一"，但 T12 的 claimed_paths 只有 CLI 和 HTTP，没有 MCP handler | `W_SCOPE_CLAIM_MISMATCH`：title/goal 范围与 claimed_paths 覆盖不一致 | 中 |
| **canonical API 表面不完整** | T1 定义 5 个 canonical 函数，但 T2 提到 cmd_workflow_verify，verify_task 不在 T1 的 API 中 | `W_CONSUMER_USES_UNPROVIDED_API`：consumer 的 goal 提到 provider 未声明的函数 | 中 |
| **管道操作吞 exit code** | T19 的 `pytest tests/ | tail -5` 在无 pipefail 时丢失退出码 | `W_VERIFICATION_PIPE_SWALLOWS_EXIT` | 低 |
| **接受标准允许不安全实现** | T17 要求"ledger 中有 message event"，但直接 append_event（违反单写者原则）也能通过验收 | `W_ACCEPTANCE_PERMITS_ANTIPATTERN` | 高 |

**通用化方向**：上述发现中，"注册层缺失"和"claimed_paths 不完整"的根因是同一个——**基于查表分发的架构中，新端点必须注册到分发表**。已将通用解法（Registration Invariant Checking）写入 `问题清单-v5-ralph.md` RO-5，作为 Ralph 的通用机制而非项目特定规则。

#### 运行时 agent 行为监控（Ralph 当前最大盲区）

**当前状态**：Ralph 在执行前校验计划、执行后验证结果，但执行中不观察 agent 做了什么。

**为什么需要**（实际案例）：

MCP→CLI 迁移中，8 个任务完成、46 个 pytest 通过、prompt 全部改为 CLI-only。关闭 MCP 后实际测试发现两类问题：

1. **Foreman 沉默**（初次误诊为 PTY 传输层问题，实为 preamble 冷启动流程仍引导 agent 先调 MCP 工具，卡在不存在的 `cccc_bootstrap` 上。详见 findings #15 更正记录）
2. **Workflow 状态机断裂**：foreman 用 `cccc workflow submit` 注册了 task（到 ready 状态），但之后直接用 `cccc send` 给 worker 分配任务，绕过了 approve → assign → running 流程。Worker 调 `cccc task complete` 时 task 还在 ready，被状态机拒绝。

如果 Ralph 有运行时监控，它可以：
1. **检测沉默 agent**：task 分配后 N 秒无 ledger 事件 → 报警
2. **检测路径偏航**：agent 用 `cccc send` 直接分配任务而非等待 workflow 自动 assign → 警告"workflow task 未走 approve 流程"
3. **检测状态不一致**：worker 报 `cccc task complete` 但 task 不在 running 状态 → 提示 foreman 检查 workflow 流程

**最小可行方案**：
- daemon 已有 ledger 事件流，Ralph 可以订阅
- 对 workflow-managed task：分配后启动计时器，超时无 `ralph_task_event` 则报警
- 不需要解析 agent 输出——只需观察"是否产生了预期的 ledger 事件"

### P2 — 架构优化

| 问题 | 描述 |
|------|------|
| project_root 手传 | 应提升为 group 元数据 |
| Prompt 4 处分散 | 应收敛为单一 canonical fragment |

### P3 — Worker 协作

| 问题 | 描述 |
|------|------|
| W-1 | Worker 间无共享类型合约 |
| W-2 | Worker 无主动进度推送（Foreman 靠 poll） |

---

## 8. 文件索引

```
src/cccc/ralph/                    # ← 独立 Ralph CLI 工具（新）
├── __init__.py
├── models.py                      # Plan, TaskSpec, Verification, Contract, ForbiddenFlow...
├── core.py                        # suggest(), verify(), path overlap 算法
├── validator.py                   # validate() — 27 条结构性检查
├── plan_io.py                     # YAML/JSON plan 加载
└── cli.py                         # CLI 入口：validate, suggest, verify, explain

src/cccc/daemon/foreman/
├── ralph_service.py               # daemon 内 Ralph（suggest_ready_batch, verify_completion）
├── workflow_orchestrator.py        # 集成层（batch → assign → start agents）
├── workflow.py                     # ForemanWorkflow（batch 决策管线）
├── agent_pool.py                   # Agent 评估/创建/分配
└── progress_report.py             # 飞书进度通知

src/cccc/daemon/
└── ralph_ipc_handler.py           # IPC 路由（ralph_batch_suggest, ralph_task_event...）

src/cccc/kernel/
├── system_prompt.py               # Foreman/Worker prompt（已含 workflow 引导）
├── prompt_files.py                # Preamble（已含 workflow 引导）
├── workflow_state_engine.py       # 状态机
└── workflow_state_types.py        # 状态枚举

src/cccc/cli/
├── main.py                        # CLI 命令注册
└── workflow_cmds.py               # workflow submit/status/verify/retry/fail + task complete

src/cccc/ports/web/routes/
└── workflow.py                    # HTTP 端点

src/cccc/resources/
├── cccc-help.md                   # 帮助文档（已含 workflow commands）
└── capabilities/
    └── task_management.yaml       # 能力注入（已含 workflow-first 指导）

plans/
└── fix-cccc-workflow.yaml         # 修复计划（9 任务，已执行完成）

tests/ralph/
├── test_ralph_standalone.py       # Ralph 单元测试（34 项）
├── sample_bad_plan.yaml           # 模拟旧失败模式
└── sample_good_plan.yaml          # 正确示范

tests/
├── test_prompt_assembly.py        # Prompt 集成测试（3 项）
└── e2e/
    ├── test_smoke_workflow.py     # 基础 smoke 测试
    ├── test_workflow_e2e.py       # 正向 E2E（verify pass + fail）
    └── test_workflow_anti_bypass.py  # 反向 E2E（进度消息不能完成任务）
```
