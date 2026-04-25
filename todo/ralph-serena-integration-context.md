# Ralph + Serena 集成方案讨论上下文

> 本文档为自包含上下文，供外部 AI 讨论 Ralph 与 Serena 的集成方案。
> 外部 AI 无法浏览项目代码，因此本文档是唯一的信息来源。
> 日期：2026-04-07

---

## 第一部分：系统背景

### 项目简介

CCCC 是一个多 AI 协作工作流系统。核心角色：
- **Foreman**（规划 AI）：接收用户需求，生成 plan.yaml（任务计划），协调 Worker 执行
- **Worker**（执行 AI）：接收单个任务，修改代码，提交结果
- **Ralph**：计划校验器 + 任务调度器，确保计划结构正确、调度安全
- **Daemon**：后台服务，管理工作流状态、事件、IPC

### 当前工作流

```
用户需求
  → Foreman 生成 plan.yaml
    → Ralph validate（结构校验）
      → Codex/外部AI 审查（语义审查）
        → Ralph suggest（输出 ready 批次）
          → Worker 并行执行
            → Ralph verify（验收检查）
              → 标记完成，re-suggest 下一批
```

### 核心教训（来自实践）

经过 6 天完整实践（27 Task + 3 轮 E2E 测试），总结出以下关键教训：

1. **结构校验和语义审查互补，不能互相替代**：Ralph 抓住结构问题（孤岛、断连、漏 claim），Codex 抓住语义问题（假验收命令、不存在的 import）
2. **编译通过不等于功能可用**：27 个 Task 全部通过 py_compile，但全部功能是死代码
3. **按文件拆任务会产生精致的死代码**：端到端功能需要多文件协作，按文件拆分导致没人负责"接线"
4. **不可运行的代码是假进展**：一个能跑的最小闭环 > 十个不相连的完整模块
5. **先跑通一条路径再扩展**：先让最简单路径端到端跑通，再逐步替换为真实实现

---

## 第 1.5 部分：Ralph 的使用场景和完整工作流

> 这是理解 Ralph 存在意义的关键章节。离开这些场景讨论集成方案没有意义。

### 场景总览

Ralph 在 CCCC 工作流中承担 **四个角色**，贯穿计划的全生命周期：

```
① 计划校验者 — Foreman 生成 plan.yaml 后，Ralph 检查结构完整性
② 任务调度者 — 根据依赖图和写冲突，决定哪些任务可以并行执行
③ 验收把关者 — Worker 完成任务后，Ralph 执行验证检查决定 pass/fail
④ 改进引擎  — 每轮实践暴露的 Ralph 自身不足被记录并持续改进
```

### 场景 1：计划生成与校验循环（Foreman ↔ Ralph）

**触发者**：Foreman AI（规划 AI）
**频率**：每次生成或修改计划
**核心价值**：在执行前发现结构性缺陷，避免执行阶段才发现断裂

```
Foreman 生成 plan.yaml 草稿
  │
  ▼
ralph validate plan.yaml --project-root .
  │
  ├─ 0 error → 进入 Codex 审查（语义层）
  │
  └─ 有 error → Foreman 读取错误信息，修改 plan → 重新 validate
       │
       └─ 典型循环 2-3 次才通过
```

**Ralph 在这里检查什么**（50+ 规则，举关键的）：
- 依赖图有没有环？（E_DEP_CYCLE）
- 有没有孤岛任务？（W_DISCONNECTED_COMPONENTS）
- 关键入口有没有人 claim？（E_CRITICAL_ENTRYPOINT_UNOWNED）
- 关键流程有没有端到端测试覆盖？（E_CRITICAL_FLOW_UNCOVERED）
- 验证命令和验收标准是否匹配？（W_VERIFICATION_BEHAVIOR_MISMATCH）
- 消费的契约有没有提供者？（E_CONSUMER_WITHOUT_PROVIDER）
- 禁止流程有没有反面测试？（E_FORBIDDEN_FLOW_UNCOVERED）

**真实例子**：Batch C 计划初版有 5 个任务各自独立修改 orchestrator.py 的不同函数。Ralph 报 `W_IMPLICIT_SERIALIZATION`（共享 claimed_paths 但无显式依赖），Codex 审查进一步发现 T3/T4/T5 应该合并为一个任务（同文件写冲突不可并行）。最终重构为 3 个任务。

**Ralph 在这里做不到什么**（已知局限）：
- 不知道 goal_behavior 中引用的函数名是否真的存在（RV-18）
- 不知道验证命令能不能真的发现 bug（RO-10n）
- 不知道计划声称的修复是否覆盖了所有相关路径（RO-18n-d）
- → 这些目前靠 Codex 审查补充，**这正是 Serena 集成的切入点**

### 场景 2：任务调度（Ralph suggest → Foreman → Worker）

**触发者**：Daemon 中的 Orchestrator
**频率**：每完成一批任务后自动 re-suggest
**核心价值**：安全的并行调度——保证并行任务不会互相踩踏

```
所有任务注册到 Engine
  │
  ▼
ralph suggest → BatchResult
  │
  ├─ ready: ["T1", "T2"]     ← 这些可以同时执行
  ├─ blocked:
  │    T3: waiting [depends_on:T1, depends_on:T2]  ← 等依赖完成
  │    T4: deferred [claimed_paths_conflict:batch]  ← 写冲突，下批再做
  │
  ▼
Foreman 评估 batch → approve → assign Worker
  │
  ▼
Worker A 执行 T1 ┐
Worker B 执行 T2 ┘── 并行
  │
  ▼（T1、T2 完成后）
ralph suggest → ready: ["T3"]  ← T3 的依赖满足了
  ...循环直到所有任务完成
```

**调度算法的三个关键决策**：
1. **依赖检查**：T3 声明 `depends_on: [T1, T2]`，T1/T2 未完成时 T3 被阻塞
2. **写冲突检测**：T1 claim `src/auth/`，T4 也 claim `src/auth/` → 不能并行（`_write_sets_conflict`）
3. **优先级排序**：T1 完成能解锁 3 个任务，T2 完成只解锁 1 个 → T1 优先（`_unlock_score`）

**冲突检测的局限**：
- 纯文件路径级别。T1 改 `interface.py` 的接口定义，T2 改 `impl.py` 的实现 → 文件不同，不检测为冲突
- 但符号层面存在冲突（改了接口定义后，实现需要同步更新）
- → **这是 Serena 符号级冲突检测的核心价值场景**

**真实例子**：两阶段拆分模型

```
第一阶段（Ralph 负责）：
  plan.yaml:
    T1 (claimed_paths: [src/auth/])
    T2 (claimed_paths: [src/db/])
    T3 (depends_on: [T1, T2], claimed_paths: [src/api/])

  Ralph suggest → Batch 1: [T1, T2]（无依赖、无写冲突）
                  Batch 2: [T3]（等 T1+T2 完成）

第二阶段（Foreman 负责）：
  T1 → Foreman 拆为 Module A, Module B（模块化并行）
  Worker 各自执行模块 → 拼接 → Task verify gate
```

### 场景 3：验收把关（Worker 完成 → Ralph verify → pass/fail）

**触发者**：Worker 调用 `cccc task complete`
**频率**：每个任务完成时
**核心价值**：在标记完成前确认任务确实做到了它声称的事情

```
Worker 完成 T1，调用：
  cccc task complete --task T1 --changed-files src/auth/handler.py

Daemon 收到 → 触发 verify gate
  │
  ▼
ralph verify plan.yaml --task T1 --changed-files src/auth/handler.py
  │
  ├─ 运行 verification.checks 中的每个命令
  │    ✓ check "compile": python -m py_compile src/auth/handler.py  → exit 0
  │    ✓ check "test":    pytest tests/test_auth.py -v              → exit 0
  │
  ├─ 全部 required check 通过 → outcome: "passed"
  │    → Engine 标记 T1 为 COMPLETED
  │    → 触发 re-suggest 看下一批
  │
  └─ 任何 required check 失败 → outcome: "failed"
       → 任务停留在 RUNNING
       → 反馈给 Worker 重试
```

**蓝图规划的验证分流**（verification_mode）：

```
verification_mode: ralph   → 标准路径，Ralph 运行预设的 check 命令（exit code 判定）
verification_mode: agent   → Agent 路径，Ralph Agent 执行 Foreman 预设的模拟测试用例
                             （贴近真实使用的模拟输入 → 对比预期模拟输出）
                             Worker 全程不知道测试输入和预期输出
```

**监控钩子**（verify gate 之外的防线）：
- `check_file_overstepping`：Worker 修改了 claimed_paths 之外的文件 → error
- `check_completer_mismatch`：任务被非指定 Worker 完成 → error
- `check_silent_agent`：Worker 分配后 300 秒无响应 → warning
- `check_path_deviation`：Worker 用旧路径（MCP）而非新路径（CLI）→ warning

### 场景 4：Ralph 自我改进闭环

**触发者**：每轮完整实践后
**频率**：每个 plan 执行完毕后
**核心价值**：Ralph 的规则集不断进化，减少下一轮的漏洞

```
完整实践后：
  Foreman 评估 Ralph 本轮使用问题
    │
    ├─ 假阳性（Ralph 报了 error 但不合理）→ 新增豁免/降级规则
    ├─ 假阴性（Codex 发现了 Ralph 漏查的）→ 新增检查规则
    ├─ 真实 bug（执行/实测阶段暴露的）     → 强化验证命令校验
    │
    ▼
  追加到 问题清单-v5-ralph.md
    │
    ▼
  改进实施（遵循同一工作流：计划→验证→审查→执行→实测）
```

**设计哲学**：
- Ralph 预期成为强大的审查监督系统，承认不完美
- Agent 作为辅助和过渡工具补强 Ralph
- 不因 Agent 强大而懈怠 Ralph 自身改进
- **优先改 Ralph 静态规则 → 尝试把 Agent 处理的语义问题转为规则 → 持续减少 Agent 干预**

### 场景 5：完整端到端示例

以一个真实的 Batch C 计划为例，展示 Ralph 在全流程中的参与：

```yaml
# plans/batch-c-assignment-protocol.yaml
# 目标：实现"所有任务分配都经过 Foreman，无例外"

tasks:
  - id: T1
    title: "submit 协议支持 Foreman 显式 assignment"
    role: leaf
    claimed_paths: ["src/cccc/contracts/v1/ralph_ipc.py", "src/cccc/cli/workflow_cmds.py"]
    depends_on: []
    goal_behavior: "在 ReadyBatchSuggestion 中新增 assignments 字段..."
    verification:
      level: unit
      command: "pytest tests/e2e/test_smoke_workflow.py tests/test_ralph_ipc.py -q"
    provides:
      - name: assignment_submit_protocol
        kind: module
    addresses: ["ARCH-1"]

  - id: T2
    title: "handler 管道全入口透传 assignment_id + 校验"
    role: leaf
    claimed_paths: ["src/cccc/daemon/ralph_ipc_handler.py", "src/cccc/daemon/ops/workflow_task_ops.py"]
    depends_on: ["T1"]  # T2 需要 T1 的协议变更
    consumes:
      - name: assignment_submit_protocol
        from: T1
    ...

  - id: T3
    title: "orchestrator 主路径 assignment 校验"
    role: integration
    claimed_paths: ["src/cccc/daemon/foreman/workflow_orchestrator.py"]
    depends_on: ["T1", "T2"]
    verification:
      level: integration
      covers:
        tasks: ["T1", "T2", "T3"]  # 跨任务集成验证
        flows: ["assignment-flow"]
    ...
```

**Ralph 参与的时间线**：

| 阶段 | Ralph 做了什么 | 结果 |
|------|--------------|------|
| 计划生成后 | `ralph validate` 检查 50+ 规则 | 初版有 2 error（写冲突 + 缺集成测试），Foreman 修改后通过 |
| Codex 审查后 | 发现 T3/T4/T5 应合并（Ralph 无法发现的语义问题） | 重构为 3 任务 |
| 开始执行 | `ralph suggest` → Batch 1: [T1]（无依赖） | T1 分配给 Worker |
| T1 完成后 | `ralph verify` 运行 pytest → passed | T1 标记 COMPLETED |
| re-suggest | `ralph suggest` → Batch 2: [T2]（T1 完成，依赖满足） | T2 分配 |
| T2 完成后 | `ralph verify` → passed; re-suggest → [T3] | T3 分配 |
| T3 完成后 | `ralph verify`（integration 级）→ 运行跨任务测试 | 全部完成 |

### 场景 6：升级链和异常处理

```
Worker 执行 T2 失败（verify gate 未通过）
  │
  ▼
Ralph 反馈：check "test_handler" failed, exit code 1
  │
  ▼
Worker 重试（自动，最多 2 次）
  │
  ├─ 重试成功 → verify gate → passed → 继续
  │
  └─ 重试 2 次仍失败
       │
       ▼
     升级给 Foreman
       │
       ├─ Foreman 自行分析 → 发现是接口不匹配 → 修改 plan 或指导 Worker
       │
       └─ Foreman 无法解决 → 委派 Codex 帮 Worker 写代码
            │
            ├─ Codex 解决 → Worker 重新提交
            │
            └─ Codex 也失败 → 标记人工处理 → 通知用户
```

### 各角色在工作流中的分工总结

| 角色 | 做什么 | 不做什么 | 决策权 |
|------|--------|---------|--------|
| **Foreman** | 需求分析、生成 plan、模块拆分、集成拼接、E2E 验证、错误分析 | 不执行具体代码修改 | 工作流内唯一决策者 |
| **Ralph** | 结构校验（50+ 规则）、任务调度（依赖+冲突）、验收把关（运行 check 命令） | 不读代码逻辑、不做语义判断、不修改计划 | 无（校验者 + 调度者） |
| **Ralph Agent**（蓝图规划） | 语义审查超出范围项、执行模拟测试验证 | 不读代码、不做最终决策 | 无（建议者，"仅供参考"） |
| **Worker** | 接收任务→执行代码修改→提交结果 | 不知道其他 Worker 在做什么、不知道测试用例内容 | 无（执行者） |
| **Codex** | 外部对抗审查、帮 Worker 写代码 | 不在工作流内自动触发 | 无（辅助者） |
| **Engine** | 状态管理、7 条不变量守卫、ledger 记录 | 不做业务决策 | 无（守卫者） |

### Serena 在这些场景中的切入点

| 场景 | 当前痛点 | Serena 能做什么 |
|------|---------|----------------|
| 场景 1 计划校验 | Ralph 不知道 goal_behavior 引用的函数是否存在 | `find_symbol` 验证符号存在性 |
| 场景 1 计划校验 | Ralph 不知道计划声称的修复是否覆盖了所有相关路径 | `find_referencing_symbols` 查找所有引用点 |
| 场景 2 任务调度 | 写冲突检测只看文件路径，跨文件符号冲突漏检 | 符号级冲突检测 |
| 场景 2 任务调度 | 无法评估任务的影响范围大小 | 引用计数作为 risk-weight |
| 场景 3 验收把关 | 无法智能选择相关测试（全量或手动指定） | 调用链分析推荐测试范围 |
| 场景 4 改进闭环 | Codex 审查才能发现的代码事实问题 → 如果能变成 Ralph 规则就不需要 Codex | Serena 提供代码事实查询，使更多检查变为确定性规则 |

---

## 第二部分：Ralph 当前能力（完整）

### 2.1 定位

Ralph 是一个**无状态的计划校验器和任务调度器**。它操作 plan.yaml 文件（YAML/JSON），不读取代码逻辑，不执行代码，不维护 daemon 状态。所有函数都是纯计算。

### 2.2 数据模型

#### TaskSpec（单个任务）

```yaml
id: "T1"                              # 唯一标识
title: "实现用户认证"                    # 人类可读标题
role: "leaf"                           # leaf | integration | verification
type: "backend"                        # frontend | backend | general
depends_on: ["T0"]                     # 依赖的任务 ID 列表
claimed_paths:                         # 该任务声明修改的文件路径
  - "src/auth/handler.py"
  - "src/auth/middleware.py"
awareness_paths:                       # 该任务需要读取但不修改的路径
  - "src/config.py"
goal_behavior: "实现 JWT token 生成和验证" # 任务目标描述（自由文本）
acceptance_criteria: "登录接口返回有效 JWT" # 验收标准（自由文本）
failure_path: "回退到 session-based auth" # 失败时的处理方案
verification:                          # 验证规格
  level: "integration"                 # compile | unit | integration | e2e
  command: ""                          # 旧版单一命令（向后兼容）
  checks:                              # 结构化检查列表（推荐）
    - name: "compile"
      command: "python -m py_compile src/auth/handler.py"
      required: true
      expected_exit_code: 0
    - name: "test_auth"
      command: "pytest tests/test_auth.py -v"
      required: true
      expected_exit_code: 0
  covers:                              # 此验证覆盖的范围
    tasks: ["T0", "T1"]               # 覆盖的任务 ID
    paths: ["src/auth/"]              # 覆盖的路径
    flows: ["login-flow"]             # 覆盖的 critical flow
provides:                              # 该任务提供的契约
  - name: "jwt_token_api"
    kind: "api_endpoint"
    schema_hint: "POST /api/login → {token: str}"
consumes:                              # 该任务依赖的契约
  - name: "user_db_schema"
    kind: "artifact"
    from_task: "T0"                    # 从哪个任务获取（YAML 中写 from:）
addresses: ["AUTH-001", "SEC-003"]     # 该任务解决的问题编号
```

#### Plan（顶层文档）

```yaml
tasks: [TaskSpec, ...]                 # 所有任务
state:                                 # 运行时状态
  completed_task_ids: ["T0"]
  running_tasks:
    - task_id: "T1"
      claimed_paths: ["src/auth/"]
  failed_task_ids: []
critical_entrypoints:                  # 必须被某个任务 claim 的关键入口
  - "src/daemon/main.py"
  - "src/api/router.py"
critical_flows:                        # 必须被端到端测试覆盖的关键流程
  - id: "login-flow"
    description: "用户登录 → JWT 生成 → 资源访问"
    entrypoints: ["src/api/router.py", "src/auth/handler.py"]
    required_verification_level: "integration"
forbidden_flows:                       # 必须有反面测试证明不可能发生的流程
  - id: "bypass-auth"
    description: "未认证用户不得直接访问受保护资源"
    required_verification_level: "e2e"
registration_invariants:               # 必须维护的注册表
  - name: "tool_registry"
    description: "所有 CLI 命令必须注册"
    registry_file: "src/cli/commands.py"
    registry_symbol: "COMMANDS"
required_issues: ["AUTH-001"]          # 本次计划必须解决的问题编号
suppress_codes: ["W_ISOLATED_TASK"]    # 全局抑制的校验规则
suppress:                              # 精确抑制（比全局更安全）
  - code: "W_FLOW_OWNER_NO_VERIFICATION"
    task: "T-int-1"
    reason: "integration task verifies all flows collectively"
plan_scope: ["src/auth/", "src/api/"]  # 限制 critical entrypoint 检查范围
finding_refs:                          # 已知问题的缓解记录
  - id: "findings-13"
    mitigation: "Codex 审查补充语义检查"
    enforced_by: ["codex_review_gate"]
```

#### 输出模型

```python
# BatchResult — suggest() 的输出
{
    "ready": ["T1", "T2"],           # 可并行执行的任务
    "blocked": [
        {
            "task_id": "T3",
            "kind": "waiting",       # waiting（依赖未完成）或 deferred（写冲突）
            "reasons": ["depends_on:T1", "depends_on:T2"]
        },
        {
            "task_id": "T4",
            "kind": "deferred",
            "reasons": ["claimed_paths_conflict:running"]
        }
    ],
    "rationale": "2 tasks ready, 2 blocked"
}

# ValidationReport — validate() 的输出
{
    "valid": true/false,             # 有 error 则 false
    "errors": [ValidationIssue, ...],
    "warnings": [ValidationIssue, ...],
    "hints": [ValidationIssue, ...]
}

# ValidationIssue
{
    "code": "E_DEPENDENCY_CYCLE",    # 规则代码
    "severity": "error",             # error | warning | hint
    "message": "dependency cycle detected involving: T1, T2, T3",
    "task_ids": ["T1", "T2", "T3"],
    "evidence": {}                   # 额外诊断数据
}
```

### 2.3 核心算法

#### suggest(plan) → BatchResult

调度算法，决定哪些任务可以并行执行：

1. 跳过已完成、运行中、失败的任务
2. 检查依赖：所有 `depends_on` 必须在 `completed_task_ids` 中
3. 计算解锁分数：完成此任务能解锁多少后续任务（贪心优先）
4. 按解锁分数降序排列候选任务
5. 贪心选择：逐个检查候选任务的 `claimed_paths` 是否与已选任务/运行中任务冲突
6. 无冲突则加入 ready 批次，有冲突则标记为 deferred

**冲突检测**：纯文件路径级别。路径 A 和路径 B 冲突当且仅当：
- 两者相同
- 其中一个是另一个的前缀（父子目录关系）
- 其中一个是 `/`（全局写声明）

**关键局限**：只看文件路径，不看代码符号。修改同一接口的定义和实现（在不同文件中）不会被检测为冲突。

#### verify(task, changed_files) → outcome

验收算法：
1. 读取 `task.verification.checks`（优先）或 `task.verification.command`（向后兼容）
2. 逐个运行 check 命令（subprocess，120s 超时）
3. 全部 required check 通过才返回 `passed`
4. 第一个 required check 失败就短路返回 `failed`

#### _unlock_score(task_id) → int

贪心排序评分：假设当前任务完成后，有多少处于 waiting 状态的后续任务会变为 eligible（所有依赖都满足）。分数越高越优先。

### 2.4 校验规则完整目录

Ralph validate 包含 **50+ 条校验规则**，按严重度分为 error（致命）、warning（关注）、hint（信息）。

#### 图结构规则

| 规则代码 | 严重度 | 检查内容 |
|---------|--------|---------|
| E_DUPLICATE_TASK_ID | error | 任务 ID 重复 |
| E_DEP_UNKNOWN | error | 依赖的任务 ID 不存在于计划中 |
| E_DEP_SELF | error | 任务依赖自身 |
| E_DEP_CYCLE | error | 依赖图存在环（Kahn 拓扑排序检测） |
| W_DISCONNECTED_COMPONENTS | warning | 计划包含多个断开的任务组 |
| W_ISOLATED_TASK | warning | 某任务没有任何依赖边（入/出） |

#### Covers 图规则

| 规则代码 | 严重度 | 检查内容 |
|---------|--------|---------|
| E_COVERS_UNKNOWN_TASK | error | verification.covers 引用了不存在的任务 |
| E_COVERS_WITHOUT_DEP_ORDER | error | verification.covers 的任务不在传递依赖闭包中 |

#### 字段完整性规则

| 规则代码 | 严重度 | 检查内容 |
|---------|--------|---------|
| E_MISSING_CLAIMED_PATHS | error | 任务没有声明 claimed_paths |
| E_MISSING_VERIFICATION | error | 任务没有定义 verification |
| W_EMPTY_ACCEPTANCE | warning | 任务没有 acceptance_criteria |
| W_GLOBAL_WRITE_CLAIM | warning | 任务声明全局写（"/"），阻塞所有并行 |

#### 验证强度规则

| 规则代码 | 严重度 | 检查内容 |
|---------|--------|---------|
| E_NO_CROSS_TASK_VERIFICATION | error | 多任务计划没有跨任务的 integration/e2e 验证 |
| W_WEAK_VERIFICATION_ONLY | warning | 所有验证都是 compile 级别 |
| W_VERIFICATION_DUPLICATE_COMMAND | hint | 多个任务共享相同验证命令 |
| W_VERIFICATION_NO_CHECKS | warning | 有 verification.command 但 checks 列表为空 |

#### 契约规则

| 规则代码 | 严重度 | 检查内容 |
|---------|--------|---------|
| E_CONSUMER_WITHOUT_PROVIDER | error | 消费的契约没有提供者 |
| E_CONSUMER_FROM_UNKNOWN | error | 契约的 from_task 不存在 |
| W_CONTRACT_SCHEMA_MISMATCH | warning | 消费者和提供者的 schema_hint 不兼容 |
| W_PROVIDER_UNUSED | hint | 提供的契约无人消费 |
| W_CONSUME_WITHOUT_DEP | warning | 消费了某任务的契约但没有声明依赖 |
| W_DEP_WITHOUT_CONSUME | hint | 依赖了某任务但没有消费其契约 |
| W_INTEGRATION_INTERFACE_MISMATCH | hint | 消费者的验证命令未引用提供者的路径 |

#### 关键入口和流程规则

| 规则代码 | 严重度 | 检查内容 |
|---------|--------|---------|
| E_CRITICAL_ENTRYPOINT_UNOWNED | error/hint | 关键入口没有被任何任务 claim |
| E_CRITICAL_FLOW_UNCOVERED | error | 关键流程没有被任何验证覆盖 |
| E_CRITICAL_FLOW_ENTRYPOINT_UNOWNED | error/hint | 关键流程的入口没有被 claim |
| W_FLOW_SEGMENT_UNOWNED | warning | 任务覆盖了某流程但没 claim 其任何入口 |
| W_FLOW_OWNER_NO_VERIFICATION | warning/hint | 任务 claim 了流程入口但没验证该流程 |
| E_CRITICAL_FLOW_LEVEL_TOO_WEAK | error | 流程要求 integration 但最佳覆盖只是 compile |
| E_FORBIDDEN_FLOW_UNCOVERED | error | 禁止流程没有反面测试 |
| E_FORBIDDEN_FLOW_LEVEL_TOO_WEAK | error | 禁止流程的验证级别不足 |

#### 问题覆盖规则

| 规则代码 | 严重度 | 检查内容 |
|---------|--------|---------|
| E_UNCOVERED_REQUIRED_ISSUE | error | required_issues 中的问题没有被任何任务 addresses |

#### 验收匹配规则

| 规则代码 | 严重度 | 检查内容 |
|---------|--------|---------|
| W_ACCEPTANCE_UNCOVERED_BY_CHECKS | warning | acceptance_criteria 暗示实质功能但验证只有 compile/import |
| W_VERIFICATION_BEHAVIOR_MISMATCH | warning/hint | goal_behavior 暗示运行时行为但验证只是 compile/unit |
| W_COVERS_CLAIM_UNVERIFIABLE | warning | 声称覆盖某任务但验证命令未引用其路径 |

#### 角色约束规则

| 规则代码 | 严重度 | 检查内容 |
|---------|--------|---------|
| W_INTEGRATION_ROLE_WEAK_VERIFICATION | warning | integration 角色但缺少跨任务验证 |
| W_VERIFICATION_ROLE_NO_COVERS | warning | verification 角色但不覆盖任何任务 |
| W_VERIFICATION_ROLE_CLAIMS_SOURCE | warning | verification 角色却 claim 了源码（非测试文件） |
| W_LEAF_ROLE_IS_INTEGRATOR | warning | leaf 角色却提供了跨任务集成验证 |

#### 失败处理规则

| 规则代码 | 严重度 | 检查内容 |
|---------|--------|---------|
| W_NO_FAILURE_PATH | warning/hint | 涉及 actor/assignment 但没有 failure_path |

#### 隐式串行规则

| 规则代码 | 严重度 | 检查内容 |
|---------|--------|---------|
| W_IMPLICIT_SERIALIZATION | hint | 两个任务共享 claimed_paths 但没有显式依赖 |
| W_SHARED_FILE_PARTIAL_VERIFICATION | hint | 共享路径的依赖任务都没验证共享文件 |

#### 集成骨架规则

| 规则代码 | 严重度 | 检查内容 |
|---------|--------|---------|
| W_CROSS_BOUNDARY_WITHOUT_GLUE | warning | 跨路径边界依赖但缺少集成验证 |
| E_MISSING_INTEGRATION_SPINE | error | >3 任务但没有跨任务集成验证 |
| W_NO_EARLY_INTEGRATION_CHECKPOINT | warning | 所有集成验证都在图的末端 |

#### Finding 引用规则

| 规则代码 | 严重度 | 检查内容 |
|---------|--------|---------|
| W_FINDING_REF_DUPLICATE | warning | 重复的 finding 引用 |
| W_FINDING_REF_NO_MITIGATION | warning | finding 引用缺少缓解描述 |
| W_FINDING_REF_NO_ENFORCEMENT | warning | 有缓解但没有绑定执行机制 |

#### 文件系统校验规则（需 --project-root）

| 规则代码 | 严重度 | 检查内容 |
|---------|--------|---------|
| W_TEST_COVERAGE_GAP | warning | 源文件有对应测试但验证未覆盖 |
| W_INDIRECT_TEST_IMPORT | hint | 源文件被测试间接 import 但未覆盖 |
| W_CONFTEST_COVERAGE_GAP | warning | conftest 引用了源但未覆盖 |
| W_DYNAMIC_TEST_IMPORT_OPAQUE | hint | 源文件被动态 import（无法静态分析） |
| W_UNCLAIMED_TEST_FOR_SOURCE | warning/hint | 相关测试文件没有被任何任务 claim |
| W_REGISTRATION_INVARIANT_UNCOVERED | warning | 注册表文件未被 claim 但附近文件被 claim |
| W_VERIFICATION_COMPLEX_SHELL_SKIPPED | hint | 验证命令包含 shell 管道等复杂操作 |
| W_VERIFICATION_SHAPE_UNKNOWN | hint | 验证命令无法解析 |
| W_VERIFICATION_TRIVIAL_COMMAND | warning | 验证命令是无操作（true, echo 等） |
| W_VERIFICATION_PYTHON_SNIPPET_INVALID | warning | python -c 代码段语法错误 |
| W_VERIFICATION_PYTHON_IMPORT_OPAQUE | hint | python -c 使用通配符或相对 import |
| W_VERIFICATION_IMPORT_MODULE_MISSING | warning/hint | import 的模块不存在 |
| W_VERIFICATION_IMPORT_SYMBOL_MISSING | warning | import 的符号在模块中不存在 |
| W_VERIFICATION_REDUNDANT_PYCOMPILE | warning | 使用了冗余的 py_compile |
| W_VERIFICATION_TARGET_MISSING | warning/hint | 验证引用了不存在的文件路径 |
| W_VERIFICATION_PYTEST_NODE_MISSING | warning | pytest 目标节点不存在 |
| W_VERIFICATION_PYTEST_K_NO_MATCH | warning/hint | pytest -k 模式匹配不到任何测试 |
| W_SEMANTIC_DEP_HINT | hint | goal_behavior 引用了存在的 .py 文件但未 claim |

### 2.5 CLI 命令

```bash
ralph validate <plan.yaml> [--project-root PATH] [--format json|text] [--suppress CODE...]
ralph suggest <plan.yaml> [--format json|text]
ralph verify <plan.yaml> --task T1 [--changed-files FILE...] [--project-root PATH]
ralph complete <plan.yaml> --task T1 [--verify] [--project-root PATH]
ralph explain <plan.yaml> --task T1
ralph sync-state <plan.yaml> [--ledger PATH | --group ID]
ralph stats [--stats-file PATH] [--init]
```

### 2.6 Ralph 的已知局限

以下是 Ralph 无法通过增加静态规则解决的问题（来自实践验证）：

| 编号 | 问题 | 原因 |
|------|------|------|
| RV-18 | goal_behavior 中引用的函数名可能不存在 | Ralph 不解析代码符号 |
| RV-20 | monitor wiring 调用位置可行性无法验证 | 超出文件路径级别检测 |
| RO-10n | verification 命令无法检测连接级/运行时语义 bug | py_compile 通过不代表功能可用 |
| RO-11n | 删除函数的副作用链无法静态检测 | Ralph 无法建模函数内控制流 |
| RO-12n | 同一文件多入口只覆盖部分时不报警 | claimed_paths 是文件级不是函数级 |
| RO-16n-d | engine 方法缺少状态边界保护无法检测 | 无法校验方法是否有前置条件守卫 |
| RO-17n-d | plan 声称的 CAS 校验在真实入口链路中不触发 | 无法验证 goal_behavior 声称的行为是否在运行时入口能生效 |
| RO-18n-d | plan 局部修复声称全局解决无法检测 | 无法检测 acceptance 是否过度声明 |
| RO-19n-d | dataclass replace 遗漏字段清理无法检测 | 无法检测代码层字段清理遗漏 |
| RO-13n-g2 | 跨 workflow 数据污染风险 | 无法检测查询是否按 workflow_id 过滤 |
| RO-14n-g2 | goal_behavior 中 API 选择正确性 | 无法校验描述的代码逻辑是否匹配实际 API |
| RO-15n-g2 | 变量业务语义被误用 | 无法检测变量语义是否正确 |

**共同根因**：Ralph 只看 plan.yaml 的结构，不看项目代码。它知道"任务 T1 声称修改 src/auth.py"，但不知道 src/auth.py 里有什么函数、谁调用了它们、调用链是什么。

---

## 第三部分：Serena 完整能力

### 3.1 定位

Serena 是一个**基于 Language Server Protocol (LSP) 的语义代码理解和操作工具包**。它通过 LSP 服务器（如 pyright、gopls、rust-analyzer）获得编译器级别的代码理解能力，而非文本搜索。

### 3.2 核心能力分类

#### A. 符号查询能力

**find_symbol** — 按名称查找符号
- 输入：名称模式（`"MyClass"`、`"MyClass/method"`、子字符串匹配）、可选的文件/目录限制
- 输出：匹配的符号列表，每个包含：
  - `name_path`：符号在文件中的层级路径（如 `MyClass/method`）
  - `kind`：Class / Function / Method / Variable / Property / Enum 等
  - `relative_path`：文件路径
  - `location`：行号、列号
  - `body`（可选）：完整源代码
  - `info`（可选）：文档字符串和签名
  - `children`（可选）：子符号列表（如类的方法）
- 能力：跨整个项目搜索，支持精确匹配和子字符串匹配

**get_symbols_overview** — 获取文件符号概览
- 输入：文件路径、层级深度
- 输出：按类型分组的符号列表（类、函数、变量等）
- 能力：无需读取整个文件即可了解其结构

**find_referencing_symbols** — 查找所有引用
- 输入：目标符号的 name_path 和文件路径
- 输出：所有引用该符号的位置，每个包含：
  - 引用所在的符号（哪个函数/类/模块引用了它）
  - 引用的行号和列号
  - 周围的代码上下文
- 能力：**这是最关键的能力** — 可以回答"谁调用了这个函数"、"谁使用了这个变量"

**search_for_pattern** — 正则表达式搜索
- 输入：正则模式、上下文行数、glob 过滤
- 输出：匹配位置和上下文
- 能力：当 LSP 符号搜索不够时的回退方案

#### B. 符号编辑能力

**replace_symbol_body** — 替换符号定义
- 输入：符号 name_path、文件路径、新代码
- 能力：按名称定位并替换，不需要行号

**insert_after_symbol / insert_before_symbol** — 在符号前后插入代码
- 输入：目标符号、文件路径、新代码
- 能力：精确的相对定位

**rename_symbol** — 重命名符号（全项目重构）
- 输入：符号 name_path、新名称
- 能力：LSP 驱动的全项目重命名，自动更新所有引用

**safe_delete_symbol** — 安全删除
- 输入：符号 name_path
- 行为：如果有引用则拒绝删除并返回引用列表；无引用则删除
- 能力：确保删除不会破坏任何引用

#### C. 文件操作能力

- `read_file` — 读取文件（指定行范围）
- `create_text_file` — 创建文件
- `list_dir` — 列出目录（支持递归、gitignore 过滤）
- `find_file` — glob 模式查找文件
- `replace_content` — 文本替换（字面量或正则）
- `execute_shell_command` — 执行 shell 命令（构建、测试、lint）

#### D. 高级 LSP 查询能力（通过底层 SolidLanguageServer）

这些是 LSP 服务器提供的原始能力，Serena 的工具在其上构建：

| 方法 | 能力 | 返回数据 |
|------|------|---------|
| `request_document_symbols` | 获取文件所有符号（带层级） | 符号树 |
| `request_full_symbol_tree` | 获取目录/项目所有符号 | 扁平符号列表 |
| `request_workspace_symbol` | 全局符号搜索 | 匹配的符号列表 |
| `request_referencing_symbols` | 查找所有引用 | 引用位置列表（带上下文） |
| `request_hover` | 获取悬浮信息 | 文档字符串、类型信息 |
| `request_signature_help` | 获取函数签名 | 参数列表、返回类型 |
| `request_defining_symbol` | 跳转到定义 | 定义符号的位置 |
| `request_containing_symbol` | 获取包含符号 | 所在的类/模块 |
| `request_rename_symbol_edit` | 计算重命名编辑 | 所有需要修改的位置 |

#### E. 记忆系统

- `write_memory` — 持久化项目知识（Markdown 文件）
- `read_memory` — 读取记忆
- `list_memories` — 列出记忆（按主题过滤）
- 存储在 `.serena/memories/` 目录，跨会话持久

#### F. 跨项目查询

- `query_project` — 在其他项目上执行只读工具
- 能力：在不切换项目的情况下查询另一个代码库的符号

### 3.3 语言支持

通过 LSP 支持 **40+ 编程语言**，核心包括：
Python (pyright)、TypeScript、JavaScript、Go (gopls)、Rust (rust-analyzer)、Java、C/C++、C#、Ruby、PHP、Kotlin、Dart、Swift、Scala、Elixir、Haskell 等。

当前项目配置为 **Python only**（通过 pyright）。

### 3.4 编程接口

Serena 可以脱离 MCP 直接作为 Python 库使用：

```python
from serena.agent import SerenaAgent
from serena.tools.symbol_tools import FindSymbolTool, FindReferencingSymbolsTool

# 初始化
agent = SerenaAgent()
agent.activate_project_from_path_or_name("/path/to/project")

# 获取工具实例
find_tool = agent.get_tool(FindSymbolTool)
ref_tool = agent.get_tool(FindReferencingSymbolsTool)

# 查找符号
result = find_tool.apply(
    name_path_pattern="suggest",
    relative_path="src/cccc/ralph/core.py",
    include_body=True
)

# 查找引用
refs = ref_tool.apply(
    name_path="suggest",
    relative_path="src/cccc/ralph/core.py"
)
```

### 3.5 Serena 的局限

1. **动态语言不完备**：Python 的 duck typing、monkey patch、动态导入（`importlib.import_module`、`getattr`）超出 LSP 范围
2. **只能回答"代码中有什么"**：不能判断"这样做对不对"（业务语义需要 LLM）
3. **语言服务器启动开销**：首次使用需要启动 LSP 服务器并索引项目
4. **跨文件分析有限**：LSP 的引用查找在大型项目中可能不完整
5. **不理解运行时行为**：函数被引用不代表运行时会执行到（条件分支、异常路径等）

---

## 第四部分：集成机会分析

### 4.1 Serena 能确定性解决的 Ralph 局限

**高确定性**（LSP 可直接回答 yes/no）：

| Ralph 局限 | Serena 解法 | 原理 |
|-----------|------------|------|
| RV-18 函数名不存在 | `find_symbol(name)` → 存在/不存在 | LSP 精确匹配 |
| RO-12n 多入口只覆盖部分 | `get_symbols_overview(file)` → 所有函数级入口 | LSP 枚举文件所有公开符号 |
| RO-14n-g2 API 选择不正确 | `find_symbol(api_name)` → 签名/参数 | LSP 返回实际 API 定义 |

**中高确定性**（LSP 提供强证据，但 Python 动态性限制完备性）：

| Ralph 局限 | Serena 解法 | 原理 |
|-----------|------------|------|
| RV-20 调用位置可行性 | `find_referencing_symbols(target)` → 引用链 | 验证引用是否存在 |
| RO-11n 删除函数副作用链 | `find_referencing_symbols(deleted_func)` → 所有调用者 | 追踪谁还在调用 |
| RO-17n-d 参数不透传 | 沿调用链追踪参数传递 | 逐层检查参数是否被传递 |
| RO-18n-d 读路径未修改 | `find_referencing_symbols(target)` → 所有读写点 | 查找所有使用该数据的位置 |
| RO-13n-g2 查询未过滤 | `find_symbol("query_method", include_body=True)` → 检查方法体 | 读取方法实现 |

**低确定性**（Serena 提供数据，但判断需要 LLM）：

| Ralph 局限 | 原因 |
|-----------|------|
| RO-10n 验证命令强度 | "够不够"是语义判断 |
| RO-16n-d 守卫是否充分 | 需要理解业务状态机 |
| RO-15n-g2 变量语义误用 | 变量名的业务含义超出 LSP |
| RO-19n-d 字段清理遗漏 | 需要理解 dataclass replace 语义 |

### 4.2 Ralph 可以新增的能力（借助 Serena）

以下是超出当前 Ralph 能力范围的新功能，Serena 使其成为可能：

#### 能力 1：符号存在性验证
- **场景**：plan.yaml 中 goal_behavior 写"修改函数 `process_batch`"，Ralph 验证该函数是否真的存在
- **实现**：`find_symbol("process_batch")` → 存在/不存在
- **需要**：plan.yaml 新增字段让计划者显式声明涉及的符号名（避免从自由文本猜测）

#### 能力 2：符号级冲突检测
- **场景**：任务 A 修改 `interface.py` 的 `IAuth` 接口定义，任务 B 修改 `impl.py` 的 `AuthImpl` 实现。文件路径不重叠，但符号层面存在冲突
- **实现**：`find_referencing_symbols("IAuth")` → 发现 `AuthImpl` 在引用链上 → 标记为符号冲突
- **对 suggest 的影响**：在文件路径冲突检测之上叠加符号级冲突检测

#### 能力 3：跨文件原子性检查
- **场景**：任务改了 `foo()` 的签名，`foo()` 被 50 处调用。当前批次的任务只覆盖了其中 30 处 → 这个批次会导致编译失败
- **实现**：`find_referencing_symbols("foo")` → 50 个引用点 → 检查每个引用点的文件是否被某个任务的 claimed_paths 覆盖
- **这直接解决了 findings #2 教训**："按文件拆任务会产生精致的死代码"

#### 能力 4：自动依赖推断（作为 warning）
- **场景**：任务 B 修改函数 F1，任务 A 的范围内的 F2 调用了 F1，但 A 和 B 没有声明依赖
- **实现**：分析各任务 claimed_paths 中的符号引用关系 → 发现隐式依赖 → 报 warning
- **定位**：validate 阶段的诊断警告，不自动注入依赖

#### 能力 5：死代码验证
- **场景**：计划中的清理任务要删除某模块，Ralph 需要确认该模块确实无人调用
- **实现**：`find_referencing_symbols(module_symbol)` → 零引用 → 安全删除
- **比 grep 更可靠**：区分注释中的引用、字符串字面量中的引用、不同模块的同名符号

#### 能力 6：调用链权重评分
- **场景**：任务修改一个被 300 处调用的核心函数 vs 修改一个被 3 处调用的工具函数
- **实现**：`find_referencing_symbols(func)` → 引用数量 → 作为风险权重
- **对 suggest 的影响**：高 fanout 的修改任务标记为 high-risk，辅助排序

#### 能力 7：验证范围优化
- **场景**：任务完成后，只运行受影响的测试而非全量回归
- **实现**：从 changed symbols → find_referencing_symbols → 找到引用这些符号的测试文件
- **注意**：应作为"快速反馈"，不替代最终的全量验证

### 4.3 原有方案 vs Serena 集成方案

**原计划（RA-1/RA-2）**：

```
Ralph validate（结构校验）
  → 标记"超出结构校验范围"的问题
    → Gemini Flash Agent 做语义审查
      → 结果标注"仅供参考"
```

- 优点：灵活，可处理模糊语义
- 缺点：非确定性，结果不可信赖（"仅供参考"）
- 依赖外部 LLM 服务

**Serena 集成方案**：

```
Ralph validate（结构校验）
  → Ralph validate --semantic（Serena 代码事实校验）
    → 确定性问题直接报 error/warning
    → 不确定问题标记为"需要 Agent 审查"
      → LLM Agent 做最终语义判断
```

- 优点：确定性问题（符号存在性、引用链、调用图）直接变成可靠的校验结果
- 优点：减少 LLM 审查负担，只把真正需要语义判断的问题交给 Agent
- 缺点：LSP 在动态语言中不完备，需要标注"best-effort"
- 需要 plan.yaml 扩展字段（显式声明涉及的符号）

---

## 第五部分：架构约束

### 5.1 用户方向

- **移除 MCP，不是优化 MCP**：Serena 本身用 MCP 暴露工具，但集成时应直接调用 Python API，不走 MCP 协议
- **Ralph 保持无状态**：Serena 集成不应让 Ralph 变成有状态服务。LSP 服务器的生命周期应该隔离
- **先跑通一条路径**：MVP 应该是一条 CLI 命令（如 `ralph validate --semantic`），不涉及 daemon 集成

### 5.2 技术约束

- Serena 可以脱离 MCP 作为 Python 库直接调用（已验证）
- LSP 服务器启动有开销（pyright 需要几秒），需要考虑生命周期管理
- 推荐架构：sidecar 模式 — Ralph 核心保持纯函数，SemanticAnalyzer 作为独立层管理 LSP 生命周期

### 5.3 plan.yaml 扩展需求

为了让 Serena 有明确的查询入口（而非从 goal_behavior 自由文本猜测），plan.yaml 可能需要新字段：

```yaml
# 候选扩展字段（供讨论）
tasks:
  - id: "T1"
    # ... 现有字段 ...
    symbol_changes:                    # 显式声明涉及的符号变更
      - symbol: "src.auth.handler.AuthHandler.login"
        action: "modify_signature"     # modify_signature | modify_body | delete | create
      - symbol: "src.auth.middleware.verify_token"
        action: "modify_body"
    symbol_references:                 # 显式声明需要检查的引用
      - "src.auth.handler.AuthHandler"
```

---

## 第六部分：讨论要点

请基于以上完整上下文，讨论以下问题：

1. **集成架构**：Ralph + Serena 的最佳集成形态是什么？
   - 直接在 Ralph 内集成 Serena Python API？
   - Sidecar 模式（独立进程管理 LSP）？
   - 或者其他方案？

2. **能力优先级**：4.2 节列出的 7 个新能力，实施顺序应该如何？
   - 哪些是 MVP 必须的？
   - 哪些可以推迟？

3. **plan.yaml 扩展**：5.3 节的 symbol_changes 字段设计是否合理？
   - 是否需要？（vs 从 claimed_paths 自动推断符号）
   - 字段粒度是否合适？
   - 向后兼容性如何保证？

4. **确定性边界**：哪些检查可以作为 error 级别（必须通过），哪些只能作为 warning（最佳努力）？
   - Python 动态性如何影响这个边界？

5. **三层校验模型**：结构校验（Ralph） + 代码事实校验（Serena） + 语义审查（LLM Agent）+ 运行时验证（E2E），这个分层是否合理？
   - 各层的职责边界在哪里？
   - 如何避免层间重复？

6. **风险和陷阱**：
   - LSP 不完备性带来的假阴性风险如何管理？
   - 符号级检查是否可能产生大量假阳性（尤其在 Python 动态语言中）？
   - plan.yaml 变得更复杂是否会增加 Foreman 的负担？
