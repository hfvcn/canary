# Ralph-Foreman 工作流系统

> 最后更新：2026-03-30（Day 5 E2E 验证后）
> 前置阅读：todo/findings.md（11 条实践教训）

---

## 0. 当前状态概要

| 层 | 设计目标 | 实际状态 |
|----|---------|---------|
| **Ralph（独立工具）** | 计划校验 + 任务调度 + 执行时验收 | ✅ CLI 可用，validate/suggest/verify/explain 四命令 |
| **Ralph（daemon 内）** | 观察层，verify gate | ⚠️ 代码存在但运行时未被触发（Worker 不走 task complete） |
| **Foreman prompt** | 引导使用 workflow submit | ⚠️ 新 session 有效，有历史上下文时回退到旧路径 |
| **Worker prompt** | 引导使用 task complete | ❌ Worker 始终使用 message_send + context.sync |
| **Verify gate** | task complete → verifying → done/failed | ❌ 链路代码可达但从未在真实场景触发 |
| **系统约束层** | 旧路径不能改变工作流状态 | ❌ 不存在，旧路径和新路径并存 |

**核心教训：Prompt 是引导层不是权威层。必须有系统级约束让错误路径无法改变状态。**

---

## 1. 整体架构

### 1.1 目标架构（尚未完全实现）

```
用户
 │
 ▼
Foreman AI ──cccc workflow submit──→ CCCC Daemon
 │                                    │
 │                                    ├── Ralph (daemon 内)
 │                                    │   ├── suggest_ready_batch() → 计算可并行批次
 │                                    │   ├── verify_completion()   → 执行时验收
 │                                    │   └── sweep_stalled_tasks() → 检测卡住的任务
 │                                    │
 │                                    ├── WorkflowOrchestrator
 │                                    │   ├── process_batch_suggestion() → 评估 agent pool → 分配
 │                                    │   ├── _start_assigned_agents()   → 启动 Worker
 │                                    │   └── apply_task_event()         → 状态迁移权威
 │                                    │
 │                                    └── WorkflowEngine (状态机)
 │                                        └── task: pending → assigned → running → verifying → completed/failed
 │
 ▼
Worker AI ──cccc task complete──→ Daemon → verify gate → 状态推进
```

### 1.2 当前实际行为

```
Foreman AI ──cccc_task.create / cccc_message_send──→ Worker AI
                                                      │
Worker AI ──cccc_message_send("I'm done")──→ Foreman AI
                                              │
                                              └── Foreman 自行判断完成，context.sync task.move done
                                                  （跳过 Ralph verify gate）
```

**差距：Foreman 和 Worker 绕过了整个工作流引擎，直接通过消息+共享状态完成协调。**

---

## 2. Ralph 独立工具（已完成，可用）

Ralph 已从 daemon 中抽取为独立 CLI 工具，可脱离 CCCC 使用。

### 2.1 核心定位

**Foreman 的质检搭档**：Foreman 自由规划 → Ralph 立即校验并反馈不足 → Foreman 据此修正。循环越紧密，对 Foreman 精确度的依赖越低。

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
  - id: message_send_cannot_complete
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
| running → done | **Foreman 通过 context.sync task.move** | 不应存在（绕过 verify gate） |

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
Use cccc_message_send for progress updates or blockers only.
```

### 5.3 Prompt 稳定性问题（E2E 验证发现）

| 条件 | Foreman 行为 | Worker 行为 |
|------|-------------|-------------|
| 新 session，无历史 | ✅ 使用 workflow submit | 未测到 |
| 有历史上下文 | ❌ 回退到 cccc_task + message_send | ❌ 使用 message_send + task.move |

**结论：Prompt 改动是必要层但不是充分层。**

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

### P0 — 系统约束层（A-1, A-2）

| 问题 | 描述 | 方向 |
|------|------|------|
| A-1 | Prompt 引导不足以保证 AI 走新路径 | Completion guardrail + canonical backend entry |
| A-2 | 旧路径仍能改变工作流状态 | MCP cccc_task 降级为只读/委托 |

### P1 — 架构优化

| 问题 | 描述 |
|------|------|
| project_root 手传 | 应提升为 group 元数据 |
| Prompt 4 处分散 | 应收敛为单一 canonical fragment |
| M-1b 适配层 | MCP/CLI/HTTP 统一到同一 backend service |

### P2 — Ralph v2

| 方向 | 描述 |
|------|------|
| 验证命令预检 | 检查 command 中的文件/函数是否存在 |
| Flow segment ownership | 关键流每段是否有人负责 |
| Schema 契约匹配 | 超越名字匹配，检查类型兼容性 |
| Role-based rules | 按 role 字段强化 integration/verification 任务的检查 |
| Ready 排序 | 按解锁下游数量排优先级 |

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
    └── test_workflow_anti_bypass.py  # 反向 E2E（message_send 不能完成任务）
```
