# CCCC 问题清单 v5 — Ralph 改进专项

> 日期：2026-03-31
> 来源：v4 Phase 2 计划生成实践 + ralph-foreman-workflow.md P1
> 状态：**实施规范已确定**（Claude + Codex 四轮讨论共识）
> 前置：v4 已归档（Ralph 基础架构跑通 + 端到端流程闭环 + 12 类结构规则运行中）

---

## 〇、项目上下文（供外部审查者）

### CCCC 是什么

CCCC 是一个多 AI 协作工作流系统。核心架构：

- **Foreman**（Claude Opus）：规划 AI，负责将用户目标拆分为 plan.yaml，包含任务、依赖、验收标准
- **Worker**（Codex/GPT-5.4）：执行 AI，按 Foreman 分发的任务修改代码
- **Ralph**：计划校验器 + 任务调度器，在**执行前**校验计划结构质量，**执行中**调度并行批次，**执行后**运行验证命令检查结果
- **Daemon**：常驻后台进程，管理 group（会话）、ledger（事件日志）、actor（AI 身份）

### 工作流程

```
用户设定目标
  → Foreman 生成 plan.yaml（任务、依赖、claimed_paths、验收标准、验证命令）
    → Ralph validate plan.yaml（结构性检查：依赖图、字段完整性、契约匹配、关键流覆盖）
      → Codex 审查 plan.yaml（语义检查：验证命令有效性、测试覆盖、接口兼容）
        → Ralph suggest（输出可并行执行的 ready batch）
          → Workers 并行执行
            → Worker 完成后 Ralph verify_completion()（运行验证命令）
              → 通过 → 标记完成；失败 → 驳回重试
```

### Ralph 的两个实现

Ralph 有两套实现，分别用于不同场景：

**1. 独立 validator（`src/cccc/ralph/`）— 计划执行前的静态分析**

纯函数式，输入 `Plan` 输出 `ValidationReport`，无副作用。用于 `ralph validate plan.yaml` CLI 命令。
当前有 12 类结构规则（详见下方"现有规则清单"）。

**2. daemon 内 RalphService（`src/cccc/daemon/foreman/ralph_service.py`）— 运行时服务**

运行在 daemon 进程内，负责：
- `suggest_ready_batch()`：分析依赖 + claimed_paths 冲突，输出可并行任务批次
- `verify_completion()`：任务完成后执行验证命令（py_compile + 自定义命令）
- `sweep_stalled_tasks()`：检测停滞/离线 worker
- `check_dependencies()`：检查任务前置是否满足

### Plan 数据模型（Pydantic）

```python
class Plan(BaseModel):
    tasks: List[TaskSpec]           # 任务列表
    state: PlanState                # 运行时状态（已完成/运行中/失败的任务）
    critical_entrypoints: List[str] # 必须被某个任务 claim 的关键入口文件
    critical_flows: List[CriticalFlow]   # 必须被验证覆盖的端到端流
    forbidden_flows: List[ForbiddenFlow] # 必须被负测试覆盖的禁止流
    required_issues: List[str]      # 必须被某个任务 address 的问题 ID

class TaskSpec(BaseModel):
    id: str
    title: str
    role: Literal["leaf", "integration", "verification"]
    depends_on: List[str]           # 前置任务 ID
    claimed_paths: List[str]        # 该任务声称要修改的文件路径
    goal_behavior: str              # 任务目标行为描述
    acceptance_criteria: str        # 验收标准
    verification: Optional[Verification]  # 验证规格
    provides: List[Contract]        # 该任务产出的契约
    consumes: List[Contract]        # 该任务消费的契约
    addresses: List[str]            # 该任务解决的问题 ID

class Verification(BaseModel):
    level: Literal["compile", "unit", "integration", "e2e"]
    command: str                    # 验证命令（shell 命令）
    covers: VerificationCovers      # 该验证覆盖的任务/路径/流
    expected_exit_code: int = 0

class VerificationCovers(BaseModel):
    tasks: List[str]    # 该验证覆盖的任务 ID
    paths: List[str]    # 该验证覆盖的文件路径
    flows: List[str]    # 该验证覆盖的命名流 ID

class Contract(BaseModel):
    name: str           # 契约名称
    kind: str           # artifact, runtime_capability, api_endpoint, ...
    from_task: Optional[str]  # 消费时指定来源任务
    schema_hint: str    # 类型提示
```

### Plan YAML 样例

**好的计划**（通过 validate）：
```yaml
tasks:
  - id: T1
    title: Implement RalphService core logic
    claimed_paths: ["src/cccc/daemon/foreman/ralph_service.py"]
    depends_on: []
    verification:
      level: unit
      command: "pytest tests/test_ralph_service.py -q"
      covers:
        tasks: ["T1"]
    provides:
      - name: ralph_service_class
        kind: module

  - id: T4
    title: Wire Ralph into daemon startup
    claimed_paths: ["src/cccc/daemon/server.py", "src/cccc/daemon/ralph_ipc_handler.py"]
    depends_on: ["T1", "T2", "T3"]
    verification:
      level: integration
      command: "pytest tests/e2e/test_smoke_workflow.py -q"
      covers:
        tasks: ["T1", "T2", "T3", "T4"]  # 跨任务集成验证
        flows: ["daemon_startup_loads_ralph"]
    consumes:
      - name: ralph_service_class
        from: T1

critical_entrypoints:
  - src/cccc/daemon/server.py

critical_flows:
  - id: daemon_startup_loads_ralph
    description: "Daemon startup creates RalphService and registers IPC handler"
    required_verification_level: integration
```

**坏的计划**（validate 报多个 error/warning）：
```yaml
tasks:
  - id: T1
    claimed_paths: ["src/cccc/daemon/foreman/ralph_service.py"]
    verification:
      level: compile      # ← 只做编译检查
      command: "python -m py_compile src/cccc/daemon/foreman/ralph_service.py"
      covers:
        tasks: ["T1"]     # ← 只覆盖自己
  # ... 6 个任务全是 compile-only，无跨任务验证
  # 无 critical_entrypoints、无 critical_flows
```

### 现有 Ralph Validator 规则清单（12 类，已实现）

| # | 类别 | 诊断码 | 严重度 | 检查内容 |
|---|------|--------|--------|---------|
| 1 | 图结构 | `E_DUPLICATE_TASK_ID` | error | 任务 ID 重复 |
| 1 | 图结构 | `E_DEP_UNKNOWN` | error | depends_on 引用不存在的任务 |
| 1 | 图结构 | `E_DEP_SELF` | error | 任务依赖自己 |
| 1 | 图结构 | `E_DEP_CYCLE` | error | 依赖图有环（Kahn 算法） |
| 1 | 图结构 | `W_DISCONNECTED_COMPONENTS` | warning | 计划有多个不连通的任务组 |
| 1 | 图结构 | `W_ISOLATED_TASK` | warning | 任务没有任何依赖边（既不依赖别人也不被别人依赖） |
| 2 | 字段完整性 | `E_MISSING_CLAIMED_PATHS` | error | 任务无 claimed_paths |
| 2 | 字段完整性 | `E_MISSING_VERIFICATION` | error | 任务无 verification |
| 2 | 字段完整性 | `W_EMPTY_ACCEPTANCE` | warning | 任务无 acceptance_criteria |
| 2 | 字段完整性 | `W_GLOBAL_WRITE_CLAIM` | warning | 任务 claim "/" 全局写，阻塞所有并行 |
| 3 | 验证强度 | `E_NO_CROSS_TASK_VERIFICATION` | error | 多任务计划但无跨任务 integration/e2e 验证 |
| 3 | 验证强度 | `W_WEAK_VERIFICATION_ONLY` | warning | 所有验证都是 compile-level |
| 4 | 契约匹配 | `E_CONSUMER_WITHOUT_PROVIDER` | error | 消费的契约无人提供 |
| 4 | 契约匹配 | `E_CONSUMER_FROM_UNKNOWN` | error | from_task 指向不存在的任务 |
| 4 | 契约匹配 | `W_PROVIDER_UNUSED` | hint | 提供的契约无人消费 |
| 5 | 关键覆盖 | `E_CRITICAL_ENTRYPOINT_UNOWNED` | error | 关键入口文件无人 claim |
| 5 | 关键覆盖 | `E_CRITICAL_FLOW_UNCOVERED` | error | 关键流无人验证覆盖 |
| 5 | 关键覆盖 | `E_CRITICAL_FLOW_ENTRYPOINT_UNOWNED` | error | 关键流的入口文件无人 claim |
| 6 | 契约↔依赖 | `W_CONSUME_WITHOUT_DEP` | warning | 消费某任务的契约但不依赖它 |
| 6 | 契约↔依赖 | `W_DEP_WITHOUT_CONSUME` | hint | 依赖某任务（该任务有 provides）但不消费其契约 |
| 7 | 关键流级别 | `E_CRITICAL_FLOW_LEVEL_TOO_WEAK` | error | 关键流要求 integration 但实际覆盖只有 compile |
| 8 | 问题覆盖 | `E_UNCOVERED_REQUIRED_ISSUE` | error | required_issues 中的问题无人 address |
| 9 | 行为匹配 | `W_VERIFICATION_BEHAVIOR_MISMATCH` | warning | goal 暗示运行时行为但验证只是 compile/unit |
| 10 | 禁止流 | `E_FORBIDDEN_FLOW_UNCOVERED` | error | 禁止流无负测试覆盖 |
| 10 | 禁止流 | `E_FORBIDDEN_FLOW_LEVEL_TOO_WEAK` | error | 禁止流验证级别不足 |
| 11 | 隐式串行 | `W_IMPLICIT_SERIALIZATION` | hint | 两任务共享 claimed_paths 但无显式依赖 |
| 12 | 集成脊柱 | `W_CROSS_BOUNDARY_WITHOUT_GLUE` | warning | 跨边界依赖无集成验证覆盖 |
| 12 | 集成脊柱 | `E_MISSING_INTEGRATION_SPINE` | error | >3 任务计划但无跨任务集成验证 |

### 运行时验证流程（RalphService.verify_completion）

当 Worker 报告任务完成后，RalphService 执行两阶段验证：

```
Phase 1 (内建): py_compile — 对 changed_files 中的 .py 文件编译检查（30s 超时）
Phase 2 (自定义): 执行 TaskRef.verification_command 作为 shell 命令（120s 超时）

结果: passed / failed / timeout / skipped
  → passed: 标记任务完成
  → failed: 标记任务失败，驳回重试
```

### 关键实践教训（v4 总结）

1. **编译通过 ≠ 功能可用**：27 个任务全通过 py_compile，但所有 Ralph 功能是死代码
2. **按文件拆任务会产生死代码**：没有任务负责"在 daemon 启动时创建 RalphService 实例"
3. **Ralph + Codex 审查互补**：Ralph 抓结构缺陷（孤岛、断连、漏 claim），Codex 抓语义缺陷（假验收命令、危险迁移）。单独用任何一个都不够
4. **结构性校验通过 ≠ 计划无缺陷**：Ralph validate 报 0 error，但 Codex 发现 3 类问题（漏 claim 测试、假验收命令、语义依赖缺失）

---

## 一、Ralph validate 盲区（5 类）

来源：Phase 2 计划生成 → Codex 审查暴露的 Ralph 结构性检查不足

| 编号 | 问题 | 建议规则 | 实现复杂度 | 优先级 |
|------|------|----------|----------|--------|
| RV-1 | 改源文件漏 claim 测试文件 | `W_UNCLAIMED_TEST_FOR_SOURCE`：对 claimed_paths 中的 `src/X.py`，扫描 tests/ 下 import 了它的文件 | 低 | **P0** |
| RV-2 | 假验收命令通过验证 | 验证命令静态预检：对 `python -c "from X import Y"` 检查 Y 是否存在于 X 的 AST 顶层；对 `pytest tests/foo.py` 检查文件是否存在 | 中 | **P0** |
| RV-3 | 虚假覆盖声明 | `W_COVERS_CLAIM_UNVERIFIABLE`：如果 A covers B 但 A 的 verification 不引用 B 的 claimed_paths | 低 | **P1** |
| RV-4 | W_VERIFICATION_BEHAVIOR_MISMATCH 过度噪音 | 被下游 integration/e2e 的 `covers.tasks` 包含时降为 hint | 低 | **P1** |
| RV-5 | 语义依赖推断缺失 | 当 goal_behavior 提到某关键词，且该关键词出现在 plan 之外的文件中，提示检查 | 高 | **P2** |

### 实例（Phase 2）

- **RV-1 实例**：T2 改 `ralph_ipc_handler.py`，`tests/test_ralph_ipc.py` 对该文件有硬断言（`get_orchestrator.assert_called_once_with("group-1")` 不带 project_root），Ralph 没提醒 claim
- **RV-2 实例**：T2 验证写了 `from cccc.daemon.ralph_ipc_handler import RalphIPCHandler`，该类不存在，Ralph 报 valid
- **RV-3 实例**：T8 声称 `covers.tasks` 包含 T5（改 `task_management.yaml`），但 `test_prompt_defaults.py` 只调用 `load_builtin_help_markdown()`，不读 YAML

---

## 二、运行时 agent 行为监控（WF-NEW-3）

来源：MCP→CLI 迁移实践，详见 ralph-foreman-workflow.md

**当前状态**：Ralph 在执行前校验计划、执行后验证结果，但执行中不观察 agent 做了什么。

**需要检测的三类问题**：
1. **沉默 agent**：task 分配后 N 秒无 ledger 事件 → 报警
2. **路径偏航**：agent 用 `cccc send` 直接分配任务而非等待 workflow 自动 assign → 警告
3. **状态不一致**：worker 报 `cccc task complete` 但 task 不在 running 状态 → 提示

**最小可行方案**：
- daemon 已有 ledger 事件流，Ralph 可以订阅
- 对 workflow-managed task：分配后启动计时器，超时无 `ralph_task_event` 则报警
- 不需要解析 agent 输出——只需观察"是否产生了预期的 ledger 事件"

**E2E 实战新增证据（2026-04-02）**：

- **FIX-4 沉默 agent 实例**：v2 实战中 Codex worker 在 T2（前端 scaffold）上卡死 5+ 分钟，无超时、无错误、无进度报告。`last_heartbeat: null` 始终为空。Foreman 只能人工判断并重新分配给 Claude worker。check_stalled_tasks() 已实现但 automation loop 未定期触发。
  - Foreman 反馈："Silent failures are worse than loud failures — there was no timeout, no error, no partial status."
- **runtime_state 矛盾实例**：v1/v2 实战中，活跃 worker 显示 `runtime_state: "stopped"` 同时 `running: true`。两个字段语义矛盾，Foreman 无法可靠判断 worker 是否存活。

### 新增监控需求：子 agent 行为约束（E2E 实战暴露）

当前 WF-NEW-3 只监控**已知 worker** 的健康状态。但 E2E 实战暴露了更深层的问题：Foreman 和 Worker 可以自行创建子 agent、重新分配任务、甚至自己执行任务，这些行为完全不在 Ralph 的观测范围内。

**需要检测的新场景**：

4. **Foreman 自建子 agent**：Foreman 在 workflow 执行中创建计划外的 worker（如 `claude-general-worker`），绕过原始分配 → 告警
5. **任务完成者与分配者不匹配**：task 分配给 worker-A，但 task_reported_completed 的 agent_id 是 worker-B → 告警
6. **Foreman 直接执行任务**：Foreman 用 `cccc task complete` 自己报告完成（Foreman 应该协调而非执行） → 告警
7. **Worker 越权修改文件**：Worker 修改了不在其 claimed_paths 范围内的文件 → 告警（依赖 FIX-1 plan→engine 元数据传递）

**E2E 实战实例**：
- v2 T2 分配给 `frontend-worker`（Codex），但最终由 `planner`（Foreman 自己）完成。日志证据：task_registered 分配给 frontend-worker，但 task_reported_completed 的 agent_id 是 planner
- v2 Foreman 创建了 `claude-general-worker` 和 `claude-general-worker-1` 两个计划外 worker，plan.yaml 中没有对应的 assign_to 声明
- v2 T5 引擎分配给 `claude-general-worker-1`，Foreman 手工发给 `backend-worker`，最终由 `backend-worker` 完成——三方不一致

**为什么不在 v3 而在 v5**：这些检测需要 Ralph 运行时观测层（ledger 事件订阅 + 分配记录比对），是 WF-NEW-3 的自然扩展，不是 workflow engine 的调度逻辑。

---

## 二b、verification 事件语义（E2E 实战新增）

> 来源：e2e-v1-vs-v2-对比报告.md (FIX-5)
> 归类原因：verification 事件契约属于 Ralph 运行时观测层

### VER-1 verification_passed 事件语义修正（P1）
- **现象**：当 verification outcome 为 `skipped`（无 command configured）时，engine 仍发 `verification_passed` 事件。事件名与内容矛盾
- **影响**：Foreman 把 skipped 误读为 passed，对用户声称"all tasks verified by ralph"——实际 verify gate 从未运行
- **实例**：v2 实战全部 6 个任务的 verification_passed 事件内容为 `overall_outcome: "skipped", checks: []`。交叉验证时 Foreman 汇报与日志不一致
- **改进方案**：outcome=skipped → 发 `verification_skipped` 事件；outcome=failed → 发 `verification_failed` 事件
- **验收标准**：下轮实战中，skipped verification 不产生 verification_passed 事件

### VER-2 Foreman 虚报（VER-1 的用户侧后果，P2）
- **现象**：Foreman 对用户声称"6/6 tasks completed and verified by ralph"，但无任何 ralph 验证真正执行
- **根因**：VER-1 的事件命名误导。Foreman 读到 verification_passed 事件名就认为验证通过了
- **改进方案**：修复 VER-1 后，Foreman 收到 verification_skipped 会正确报告"验证已跳过"

---

## 三、新增改进（讨论中发现的盲区）

来源：Claude + Codex 四轮讨论

| 编号 | 问题 | 建议规则 | 优先级 |
|------|------|----------|--------|
| NEW-1 | `covers.tasks` 引用不存在的任务 | `E_COVERS_UNKNOWN_TASK` | **P1** |
| NEW-2 | `covers.tasks` 目标不在当前任务的传递依赖闭包内（覆盖了还没跑完的任务） | `E_COVERS_WITHOUT_DEP_ORDER` | **P1** |
| NEW-3 | 集成验证来得太晚（所有跨任务验证都是终点叶子，无早期 checkpoint） | `W_NO_EARLY_INTEGRATION_CHECKPOINT` | **P1** |
| NEW-4 | verification_command 只是 py_compile（与 Ralph 内建重复，零增量覆盖） | `W_VERIFICATION_REDUNDANT_PYCOMPILE` | **P0** |
| NEW-5 | 任务未 claim 验证命令引用的测试文件 | 由 RV-2 `E_VERIFICATION_PYTEST_TARGET_MISSING` 覆盖 | **P0** |

### 实施中发现的实例（Wave 1-2 执行期间 Codex 审查暴露）

- **NEW-5 实例 1**（Wave 1）：T2 验证写 `pytest tests/ralph/test_ralph_standalone.py -k root`，但测试中无 root 相关用例，Ralph validate 报 0 error
- **NEW-5 实例 2**（Wave 2A）：T1/T2 验证引用 `tests/ralph/test_workspace_index.py` 和 `tests/ralph/test_filesystem_validator.py`，文件不存在，Ralph validate 报 0 error
- **RV-2 实例（新）**：Wave 1 T4 与 T3 验证命令完全相同 `pytest tests/ralph/test_ralph_standalone.py -q`，Ralph 无法检测"集成测试实际等于单元测试"的语义重复
- **fatal 定义不清实例**：Codex 指出 `E_MISSING_CLAIMED_PATHS` 不应触发 FS 校验短路（内容缺失 ≠ 图结构破损），但 v5 方案未精确定义 fatal 集合

### 实施后修复（自测暴露的规则质量问题）

- **RV-3 假阳性修复**：`W_COVERS_CLAIM_UNVERIFIABLE` 对 integration/e2e 级别的验证也要求命令字符串引用被 cover 任务的 claimed_paths，但集成测试本质上运行的是跨模块测试，不可能在 pytest 命令中列出每个源文件。**修复**：integration/e2e 级别跳过此检查。
- **RV-1 冗余警告修复**：`W_TEST_COVERAGE_GAP` 对每个（源文件 × 关联测试）组合都发一条 warning，导致被 6 个测试文件 import 的源文件产生 6 条 warning。**修复**：按源文件聚合，一条 warning 附 evidence 列出所有未覆盖测试。
- **已修复 — pytest -k 空匹配**：新增 `W_VERIFICATION_PYTEST_K_NO_MATCH`，AST 收集测试名称后与 -k 模式做子串匹配。
- **已修复 — 验证命令语义重复**：新增 `W_VERIFICATION_DUPLICATE_COMMAND`（hint），豁免 self-covering leaf 任务。
- **已修复 — expected_exit_code 未使用**：Codex 审查发现 `VerificationSpec.expected_exit_code` 未被 `verify_completion()` 消费。已贯通到 `_run_verification_check()`。
- **已修复 — git root 解析错仓库**：`_git_top_level()` 现在在 plan 文件所在目录执行 `git rev-parse`，而非当前 shell 目录。
- **已修复 — 非法 .cccc/ralph.yaml 静默吞掉**：改为 `warnings.warn()`。
- **已修复 — wrapper unwrap 误解析**：`env -u`/`timeout -s` 等带参数 flag 的 wrapper 不再误判。
- **已修复 — 路径逃逸**：`WorkspaceIndex` 新增 `_safe_path()` 边界检查，拒绝 `../` 逃出 project_root。

### 能力扩展计划审查暴露的不足（2026-04-01）

以下均为 Codex 审查发现但 Ralph 无法检测的语义问题（validates 经验证工作流的互补性）：

- **接线点语义错误**：T6 计划修改 `agent_pool._generate_worker_prompt()` 注入 context，但重试流程实际调用 `orchestrator._build_task_prompt()`。Ralph 只检查 claimed_paths 和 depends_on 图结构，无法分析"这个函数是否真的在执行路径上"。
  - **实例**：capability-expansion.yaml T6，Codex 通过追踪 `retry_task() → READY → _build_task_prompt()` 调用链发现
- **IPC op 名称错误**：T7 写了 `capability_use IPC op`，实际 daemon op 是 `capability_tool_call`。Ralph 不检查 goal_behavior 中的 op 名称是否与代码库一致。
  - **实例**：capability-expansion.yaml T7，Codex 通过 grep daemon handler dispatch table 发现
- **执行路径遗漏**：T1 给 model 加了 `checks[]` 字段，但只计划修改 daemon 路径的执行器，遗漏了 standalone `ralph/core.py` 的执行器。Ralph 有 `W_REGISTRATION_INVARIANT_UNCOVERED` 但它检查的是 dispatch table，不是"所有消费某 model 字段的代码路径"。
  - **实例**：capability-expansion.yaml T1/T2，Codex 通过读 `core.py:119-159` 发现 verify 逻辑只读 `v.command`

这三类问题均属于"计划和代码实际行为不匹配"（finding 十三），验证了 Ralph + Codex 互补的结论。暂不列为 Ralph 改进项——这些是语义分析范畴，超出结构性校验的设计边界。

---

## 四、其他 Ralph 改进

来源：ralph-foreman-workflow.md P1 + v3 架构优化 E2E (2026-04-01)

| 编号 | 方向 | 描述 | 优先级 |
|------|------|------|--------|
| **RO-5** | **注册不变量检查** | **通用 producer→registry→consumer 三角检查，见下方详述** | **P1** |
| RO-1 | Flow segment ownership | 关键流每段是否有人负责 | P2 |
| RO-2 | Schema 契约匹配 | 超越名字匹配，检查类型兼容性（v3 已实现基础版 W_CONTRACT_SCHEMA_MISMATCH） | P2 |
| RO-3 | Role-based rules | 按 role 字段强化 integration/verification 任务的检查 | P2 |
| RO-4 | Ready 排序 | 按解锁下游数量排优先级 | P3 |

### RO-5 注册不变量检查（Registration Invariant Checking）

> 来源：v3 架构优化 E2E 验证 (2026-04-01)
> 实例：T16 实现了 heartbeat 的 6 个组件，但 IPC dispatch table 中没有对应 handler entry

**问题**：基于查表分发的架构（IPC dispatch、HTTP router、event handler、plugin registry、DI container）中，新增端点必须同时注册到分发表。当某个 Task 创建了端点的生产者和消费者但没更新注册表，就产生"每个组件内部正确但不可达"的集成缝隙。

**为什么现有机制抓不到**：
- `claimed_paths` 检查文件冲突，不检查"功能是否需要注册"
- `provides/consumes` 是声明式的，计划作者不会为"实现细节"级的注册写合约
- `critical_flows` 检查路径是否被验证覆盖，不检查路径中的注册层是否完整

**通用机制：项目声明注册不变量，Ralph 自动检测**

```yaml
# 项目级配置（.ralph.yaml 或 plan 顶层）
registration_invariants:
  - name: "IPC op dispatch"
    description: "新 daemon op 必须注册到 dispatch table"
    registry_file: "src/example/dispatch.py"
    registry_symbol: "_OPS"
    
  - name: "HTTP route"
    description: "新 route handler 必须注册到 router"
    registry_file: "src/example/app.py"
    registry_symbol: "app.add_route"
```

**检查逻辑（通用）**：

1. 扫描 Task 的 claimed_paths，检测新增的字符串字面量（如 `op="X"`）
2. 匹配到某个 registration_invariant 的 producer pattern
3. 检查该 Task 或其传递依赖 Task 是否 claim 了 registry_file
4. 没有 → `W_REGISTRATION_INVARIANT_UNCOVERED`

**设计原则**：
- 机制通用（producer → registry → consumer 三角检查，适用于所有查表分发架构）
- 配置项目特定（哪些文件是 registry 由项目声明）
- 不依赖计划作者声明（从 claimed_paths 自动检测，不需要手写 provides/consumes）
- 不依赖代码语义理解（文件级 diff + 字符串匹配即可）

**与 provides/consumes 的互补关系**：
- provides/consumes：功能级合约（"task A 产出某 capability"）— 声明式，需作者填写
- registration_invariants：架构级接线（"新端点必须注册"）— 检测式，自动发现

---

## 五、实施规范（Claude + Codex 共识，经 5 源审查修订）

> 修订来源：`todo/ralph-v5-review-synthesis.md`（gedt-5, gedt-v5-adversrial, gp-5, gpp-5, Codex 审查）
> 采纳 8 项直接建议（A1-A8），4 项确认建议（B2-B4, B7），推迟 4 项（B1, B5-B6, B8）

### 5.1 架构决策

#### 验证器分层

当前 `validator.py` 是纯 `Plan -> ValidationReport`，无副作用。RV-1/RV-2 需要读项目文件系统，属于新类别。

```
src/cccc/ralph/
├── validator.py              # 纯结构校验（现有 12 类 + Wave 1 新增 covers 图规则）
├── filesystem_validator.py   # 文件系统校验（新增，Wave 2）
├── workspace_index.py        # 共享文件系统索引（新增，Wave 2，服务 RV-1/RV-2/projected state）
└── models.py                 # 数据模型
```

- `validator.py` 保留 `validate(plan)` 纯结构入口
- `validator.py` 新增 `validate_with_project(plan, *, project_root: Path)` 聚合入口
- `filesystem_validator.py` 暴露 `validate_filesystem(plan, *, project_root: Path, workspace: WorkspaceIndex) -> list[ValidationIssue]`
- **硬约束**：如果纯结构校验有 fatal error（`E_DEP_CYCLE`, `E_MISSING_CLAIMED_PATHS`, `E_MISSING_VERIFICATION`），filesystem 校验**短路跳过**，避免在破损 DAG 上继续下钻产生噪音

**AST 解析错误处理**：语法错误时跳过该文件检查，记录 hint。语法正确性是运行时 py_compile 的职责。

#### Verification 单一真相源（审查 A1）

**问题**：计划模型使用结构化 `Verification.command`（`models.py`），运行时使用扁平 `TaskRef.verification_command`（`ralph_ipc.py`）。RV-2 校验的是计划层字段，但实际执行的是运行时字段——两者可能分叉。

**决策**：作为 Wave 1 前置修复。
- 优先方案：运行时直接消费结构化 `verification.command`
- 次优方案：在 plan → TaskRef 投影时做显式转换 + round-trip 一致性测试
- 禁止两套字段继续独立演化

#### project_root 解析链（审查 A7）

**问题**：当前 `ralph/cli.py` 默认 `project_root = Path(".")`。plan 放在 `.cccc/plans/` 或 `tmp/` 时会导致 filesystem 规则假阴性/假阳性。

**决策**：解析优先级改为：
1. CLI 显式 `--project-root`
2. 配置文件
3. **git root**（`git rev-parse --show-toplevel`）
4. plan 文件所在目录
5. cwd（最后 fallback）

CLI 输出中打印实际使用的 `project_root` 和 filesystem 校验是否启用。

### 5.2 实施波次

#### Wave 1：Foundation（模型统一 + 纯结构规则补齐）

目标：先统一真相源、修 root 解析、补齐纯图结构规则，确保后续 Wave 2 站在正确地基上。

##### 1a. Verification 单一真相源（A1）

统一 `models.Verification.command` 与 `ralph_ipc.TaskRef.verification_command`，消除 plan/runtime 双字段分叉。这是 RV-2 的硬前置——否则 RV-2 校验的命令和实际执行的命令不是同一个。

##### 1b. project_root 解析链（A7）

实现 CLI > config > git root > plan dir > cwd 的完整优先级链。

##### 1c. `covers.tasks` 图结构规则（A8，前移自原 Wave 2）

纯图结构规则，不依赖文件系统，应在 `validator.py` 中实现（与现有 12 类规则并列）。

| 诊断码 | 规则 | 严重度 |
|--------|------|--------|
| `E_COVERS_UNKNOWN_TASK` | `covers.tasks` 中出现未知 task id | error |
| `E_COVERS_WITHOUT_DEP_ORDER` | `covers.tasks` 中的 task 必须在当前任务的**自反传递依赖闭包**内 | error |

##### 1d. 设计冻结（Wave 2 准备）

- **WorkspaceIndex 接口设计**：定义共享文件系统索引的接口和职责边界（path exists cache, module map, AST cache, projected state）
- **ValidationIssue 扩展设计**：冻结 `layer`/`confidence`/`suggested_fix` 字段定义（Wave 2 实现）
- **filesystem 短路规则**：明确哪些结构 error 触发 FS 校验短路

#### Wave 2：Filesystem Validation（RV-2 + RV-1 + 启发式规则）

目标：验证命令预检 + 测试覆盖检测，带"计划写入意图"感知。

内部分两个 gate：

##### Wave 2A：RV-2 验证命令静态预检 + WorkspaceIndex

**RV-2 核心变更（整合审查 A2, A3, B4）**：

**Wrapper unwrap（A3）**：在形状匹配前先剥除常见语义无关包装：
- `env` / `/usr/bin/env` + 环境变量
- `timeout` / `gtimeout`
- `uv run`
- `poetry run`
- 可选 `pipenv run`

剥除后再做 shlex.split + 形状匹配。`bash -lc`、含 `&&/||/;` 的 shell 复合命令**不算 wrapper**，仍归入 `W_VERIFICATION_COMPLEX_SHELL_SKIPPED`。

**Projected state（A2）**：文件/符号存在性检查必须合并"计划写入意图"：
- 目标当前**存在** → 正常检查（error if missing symbol etc.）
- 目标当前**不存在**，但被**当前任务或其依赖闭包**中的某个任务 claim → 降为 `hint`（"目标尚未创建，但上游任务声称将创建"）
- 目标当前**不存在**，且无人 claim → 维持 `error`
- 注意：不是"全计划任意 task claim 了就降级"，必须在依赖闭包内

**Stdlib/第三方包处理（B4）**：
- repo-local module → 继续 AST / re-export 检查
- 非 repo-local module → 尝试 `importlib.util.find_spec()`；失败则降为 `cannot_validate`，不报 error

**形状白名单表（10 个诊断码，含 wrapper unwrap 后的实际命令）**：

| # | 形状 | 检查内容 | 失败结果 | 诊断码 |
|---|------|---------|---------|--------|
| 1 | `python -m py_compile path.py` | 文件存在且是 `.py`（+ projected state） | error | `E_VERIFICATION_PYCOMPILE_TARGET_MISSING` |
| 2 | `python -c "from X import Y"` (AST 为单个 ImportFrom) | 模块可解析；符号存在或 `__init__` re-export（+ projected state + stdlib fallback） | error | `E_VERIFICATION_IMPORT_MODULE_MISSING` / `E_VERIFICATION_IMPORT_SYMBOL_MISSING` |
| 3 | `pytest tests/foo.py` | 文件存在（+ projected state） | error | `E_VERIFICATION_PYTEST_TARGET_MISSING` |
| 4 | `pytest tests/foo.py::test_fn` | 文件存在 + 顶层函数/类存在（+ projected state） | error | `E_VERIFICATION_PYTEST_NODE_MISSING` |
| 5 | `pytest tests/foo.py::Class::method` | 文件 + 类 + 方法存在（参数化 `[...]` 剥掉）（+ projected state） | error | `E_VERIFICATION_PYTEST_NODE_MISSING` |
| 6 | Shell 复合命令（`&&`, `\|\|`, `;`, `\|`, 重定向，unwrap 后仍含 operator） | 不做静态预检 | hint | `W_VERIFICATION_COMPLEX_SHELL_SKIPPED` |
| 7 | 平凡命令（`true`, `:`, `echo "ok"`, `printf ok`） | 判定为可疑弱验证 | warning | `W_VERIFICATION_TRIVIAL_COMMAND` |
| 8 | verification_command 与 Ralph 内建 py_compile 重复 | 增量覆盖为零 | warning | `W_VERIFICATION_REDUNDANT_PYCOMPILE` |
| 9 | `python -c` 含执行语义（method call、属性链） | 视为 opaque | warning | `W_VERIFICATION_PYTHON_C_OPAQUE` |
| 10 | 其他未知形状 | 声明无法静态验证 | hint | `W_VERIFICATION_SHAPE_UNKNOWN` |

**WorkspaceIndex 实现（B7）**：随 RV-2 同步实现共享索引：
- path existence cache
- module → file path map
- AST parse cache（带语法错误 graceful skip）
- projected state（plan claimed_paths → dependency closure → "将创建文件"集合）

##### Wave 2B：RV-1 + covers 启发式 + 早期 checkpoint

**RV-1 语义重设计（审查 A4）**：从"未 claim 测试"改为"验证覆盖缺口"。

**问题**：`claimed_paths` 是写集语义（参与并行冲突检测），不是责任语义。强迫任务 claim 不会修改的测试文件会污染 write-set 冲突检测。

**新语义**：
1. 发现关联测试文件（grep 召回 + AST 判定，方式不变）
2. 检查是否有任何任务的 `verification.command` **实际执行**了该测试
3. 只有当**无人的 verification 覆盖**该测试时，才报 warning

| 情况 | 严重度 | 诊断码 |
|------|--------|--------|
| 关联测试存在，但全计划无 verification 执行该测试 | warning | `W_TEST_COVERAGE_GAP` |
| `conftest.py` 关联源变更，但未被 verification 覆盖 | hint | `W_CONFTEST_COVERAGE_GAP` |
| 发现动态导入，无法可靠判定关联 | hint | `W_DYNAMIC_TEST_IMPORT_OPAQUE` |

RV-1 检测范围不变：直接 import + 一跳 `__init__.py` re-export，不做 transitive。

**RV-4：W_VERIFICATION_BEHAVIOR_MISMATCH 降级**

若任务 T 被下游 `integration/e2e` 任务合法地 `covers.tasks` 包含，从 warning 降为 hint。

**RV-3：W_COVERS_CLAIM_UNVERIFIABLE**

仅在 `covers.tasks` 完整性通过后评估。A 声称 covers B 但 A 的 verification 无法接触 B 的 claimed_paths → warning。

**早期集成检查点（审查 B2 修订）**：从固定阈值改为图感知。

| 诊断码 | 严重度 |
|--------|--------|
| `W_NO_EARLY_INTEGRATION_CHECKPOINT` | warning |

定义不变（checkpoint = integration/e2e + covers >= 2 + 非 sink）。

触发条件修订为图感知：
1. `len(plan.tasks) >= 5`
2. 至少存在一个 cross-task verifier
3. 所有 cross-task verifier 都是 sink
4. `min_verifier_depth / max_graph_depth >= 0.5`（最早 verifier 出现在图深度过半之后）

v1 用简单的深度比例指标，后续根据真实计划样本迭代。

**ValidationIssue 扩展实现（B5）**：

在 Wave 2 新增的诊断码上实现 `layer`/`confidence` 字段：
- `layer`: `"structural"` | `"filesystem"` | `"heuristic"`
- `confidence`: `"definite"` | `"high"` | `"medium"` | `"low"`
- 现有 12 类结构规则保持不变，不追溯添加

#### Wave 3：Repo-level Invariants（减轻 planner 负担）

##### Repo 元数据（审查 A6）

**问题**：只靠 planner 手填 `critical_entrypoints` 会复现 v4"结构上过关、实际没有 wiring"的问题。

**决策**：不做通用 policy 系统，做最小 repo-local 元数据。复用现有 `.cccc/ralph.yaml` 配置约定，新增 `plan_defaults` 命名空间：

```yaml
# .cccc/ralph.yaml
plan_defaults:
  critical_entrypoints:
    - src/cccc/daemon/server.py
    - src/cccc/cli/main.py
    - src/cccc/daemon/ralph_ipc_handler.py

  critical_flows:
    - id: daemon_startup
      entrypoints:
        - src/cccc/daemon/server.py
```

当 `ralph validate` 加载 plan 时，自动合并 repo 元数据的 `plan_defaults`（plan 显式声明优先）。

**硬约束**：只承载 `critical_entrypoints` / `critical_flows`，不膨胀成通用策略系统。

##### 早期 checkpoint 迭代

用真实计划样本校准深度比例阈值。

#### Wave 4：Workflow Observability（运行时监控）

##### 前置：Task Event Contract 扩展（审查 A5）

**问题**：当前 `TaskEvent.event_type` 只有 `completed` | `failed`。内部状态机有 `ASSIGNED → RUNNING → VERIFYING`，但外部 IPC 事件是瘸腿的。没有 `started`/`progress`/`heartbeat` 事件，silent/stalled 检测会高噪声。

**决策**：先补最小任务事件契约：
- `task_assigned`（已有 ledger 事件，需暴露到 IPC）
- `task_started`（worker 开始工作时上报）
- `task_heartbeat`（定期心跳，可选）
- `task_completed`（现有）
- `task_failed`（现有）

##### WF-NEW-3：静默/停滞 agent 检测

在事件契约补齐后实现：
- Actor push `ActorStatus.updated_at`（现有）+ 新增 task-level 事件
- Ralph 定时 pull 判定 offline/stalled
- **v5 scope：仅检测 + 告警，不自动重派**

#### Wave 5（后续）

| 项目 | 描述 | 来源 |
|------|------|------|
| `review_request` sidecar | Ralph 产出 `review_request.yaml`（`cannot_validate`, `risk_codes`, `focus_paths`, `focus_tasks`, `focus_questions`, `evidence`），供 Codex 审查聚焦。v5 是文件级输出，Ralph **不解析** Codex 结果。结构化闭环是 **v6**。 | 原 v5 规划 |
| ~~RO-1~~ | ~~Flow segment ownership~~ | ~~原 v5 规划~~ |
| | **已完成 (2026-04-02)**：`_check_flow_segment_ownership()` 新增至 validator.py，检查 critical flow 的每个 entrypoint 是否有 covering task claim。发出 `W_FLOW_SEGMENT_UNOWNED` 和 `W_FLOW_OWNER_NO_VERIFICATION` 两个 warning。4 个新测试。 | |
| ~~RO-2~~ | ~~Schema 契约匹配~~ | ~~原 v5 规划~~ |
| | **已完成 (2026-04-02)**：`_contract_schema_hints_compatible()` 增强为支持 properties 结构子类型、items 递归比较、required 字段检查、嵌套属性类型匹配。7 个新测试。[Codex F6 adopted] | |
| ~~RO-3~~ | ~~Role-based rules~~ | ~~原 v5 规划~~ |
| | **已完成 (2026-04-02)**：`_check_role_constraints()` 新增至 validator.py，强制 integration 任务需 cross-task 验证、verification 任务不应 claim 源码、leaf 任务不应有 integration 行为。4 个新 warning 码。7 个新测试。 | |
| ~~RO-4~~ | ~~Ready 排序~~ | ~~原 v5 规划~~ |
| | **已完成 (2026-04-02)**：`suggest()` 重构为两遍：先收集 eligible 并按 `_unlock_score()` 排序，再做 batch 冲突筛选。高解锁分的任务优先进入 batch。[Codex F1/F3 adopted] 6 个新测试。 | |
| RV-5 | 语义依赖推断 | 原 v5 规划 |
| ~~**RV-6**~~ | ~~**pytest -k AST 收集器识别 class 内测试方法**~~ | ~~**v5 RO-5 实践 (2026-04-01)**~~ |
| | **已完成 (2026-04-02)**：`_collect_pytest_k_names()` 递归扫描 `ClassDef.body` 中的 `FunctionDef`/`AsyncFunctionDef`。4 个新测试。 | |
| ~~**RV-7**~~ | ~~**聚焦计划的 critical_entrypoints 豁免机制**~~ | ~~**v5 RO-5 实践 (2026-04-01)**~~ |
| | **已完成 (2026-04-01)**：采用方案 (b) — parent-directory 启发式。`_check_critical_coverage()` 计算 entrypoint 的父目录，若计划无任务 claim 该子目录下的文件则降为 hint。同时覆盖 `E_CRITICAL_FLOW_ENTRYPOINT_UNOWNED`。3 个新测试。 | |
| ~~**RV-8**~~ | ~~**图算法工具函数提取为共享模块**~~ | ~~**v5 RO-5 实践 (2026-04-01)**~~ |
| | **已完成 (2026-04-01)**：`transitive_deps()`、`detect_cycle()`、`find_components()` 提取到 `ralph/graph_utils.py`。`validator.py` 和 `filesystem_validator.py` 共享同一实现，`_transitive_deps_local` 已删除。 | |
| ~~**CLI-1**~~ | ~~**`ralph complete` 子命令**~~ | ~~**v5 RO-5 实践 (2026-04-01)**~~ |
| | **已完成 (2026-04-01)**：`ralph complete plan.yaml --task T1 [--verify]`。`save_plan_state()` 读取原始 YAML 并只 patch `state` 区块，避免 repo defaults 污染。5 个新测试。 | |
| **CLI-2** | **`ralph complete` 的 `yaml.dump` 破坏文件格式**：`save_plan_state()` 用 `yaml.safe_load` + `yaml.dump` 做 roundtrip，注释丢失、缩进/引号风格被重写。语义正确但人类可读性严重下降。修复：改用 `ruamel.yaml`（保留注释和格式）或 surgical text patch（只改 `state:` 区块） | **v5 RV-7/8/CLI-1 实践 (2026-04-01)** |
| ~~**RV-9**~~ | ~~**`load_plan()` 合并后丢失来源标记**~~ | ~~**v5 RV-7/8/CLI-1 实践 (2026-04-01)**~~ |
| | **已完成 (2026-04-02)**：`Plan` 模型新增 `_provenance` PrivateAttr（不影响 model_validate 输入和 model_dump 输出）。`load_plan()` 标记 "plan"，`_merge_*` 标记 "repo_defaults"。[Codex F2/F5 adopted] 5 个新测试。 | |
| **RV-10** | **`W_TEST_COVERAGE_GAP` 召回过宽**：`validator.py` 被 `test_prompt_assembly.py`、`test_prompt_defaults.py`、`test_system_prompt_roles.py` 等文件 import（但这些测试测的是 prompt 组装，不是 validator 逻辑），导致修改 validator 的任务被报 3 条无关的 coverage gap warning。应区分"测试文件 import 了该模块"和"测试文件测试了该模块的功能" | **v5 RV-7/8/CLI-1 实践 (2026-04-01)** |
| **RALPH-1** | **自指计划的 bootstrap 循环**：当计划实现的功能恰好是该计划需要通过的校验规则时（如 RV-7 计划需要 RV-7 才能 validate 通过），Ralph 没有机制处理。方案：(a) `ralph validate --suppress E_CRITICAL_ENTRYPOINT_UNOWNED` 临时豁免；(b) plan 级 `suppress_codes` 字段（类似 linter `# noqa`） | **v5 RV-7/8/CLI-1 实践 (2026-04-01)** |

### 5.3 Composition Root 覆盖策略

**v5 不新增 CCCC-specific 的 core rule。**

**Wave 1-2**：通过现有 `E_CRITICAL_ENTRYPOINT_UNOWNED` 规则检查 plan 中声明的 critical_entrypoints。
**Wave 3**：通过 `.cccc/ralph.yaml` 的 `plan_defaults.critical_entrypoints` 将 repo 级别的关键入口自动注入 plan，减轻 planner 手工枚举负担。

### 5.4 诊断码总表

**Wave 1 — structural 类（2 个新码）**：

| 码 | 严重度 | 来源 | 位置 |
|----|--------|------|------|
| `E_COVERS_UNKNOWN_TASK` | error | A8 | validator.py |
| `E_COVERS_WITHOUT_DEP_ORDER` | error | A8 | validator.py |

**Wave 2A — filesystem 类（10 个新码）**：

| 码 | 严重度 | 来源 | 位置 |
|----|--------|------|------|
| `E_VERIFICATION_PYCOMPILE_TARGET_MISSING` | error | RV-2 | filesystem_validator.py |
| `E_VERIFICATION_IMPORT_MODULE_MISSING` | error | RV-2 | filesystem_validator.py |
| `E_VERIFICATION_IMPORT_SYMBOL_MISSING` | error | RV-2 | filesystem_validator.py |
| `E_VERIFICATION_PYTEST_TARGET_MISSING` | error | RV-2 | filesystem_validator.py |
| `E_VERIFICATION_PYTEST_NODE_MISSING` | error | RV-2 | filesystem_validator.py |
| `W_VERIFICATION_COMPLEX_SHELL_SKIPPED` | hint | RV-2 | filesystem_validator.py |
| `W_VERIFICATION_TRIVIAL_COMMAND` | warning | RV-2 | filesystem_validator.py |
| `W_VERIFICATION_REDUNDANT_PYCOMPILE` | warning | RV-2 | filesystem_validator.py |
| `W_VERIFICATION_PYTHON_C_OPAQUE` | warning | RV-2 | filesystem_validator.py |
| `W_VERIFICATION_SHAPE_UNKNOWN` | hint | RV-2 | filesystem_validator.py |

**Wave 2B — filesystem + heuristic 类（4 个新码 + 1 行为变更）**：

| 码 | 严重度 | 来源 | 位置 |
|----|--------|------|------|
| `W_TEST_COVERAGE_GAP` | warning | RV-1 改 | filesystem_validator.py |
| `W_CONFTEST_COVERAGE_GAP` | hint | RV-1 改 | filesystem_validator.py |
| `W_DYNAMIC_TEST_IMPORT_OPAQUE` | hint | RV-1 | filesystem_validator.py |
| `W_NO_EARLY_INTEGRATION_CHECKPOINT` | warning | NEW-3 | validator.py |
| `W_COVERS_CLAIM_UNVERIFIABLE` | warning | RV-3 | validator.py |
| `W_VERIFICATION_BEHAVIOR_MISMATCH` 降级 | (行为变更) | RV-4 | validator.py |

**总计：17 个新诊断码 + 1 行为变更**（与修订前数量一致，但分布和语义有变化）

### 5.5 审查采纳追溯表

| 审查项 | 采纳方式 | 落入波次 |
|--------|---------|---------|
| A1: verification 单一真相源 | 直接采纳 — 统一 plan/runtime verification 字段 | Wave 1 前置 |
| A2: RV-2 projected state | 采纳（限定依赖闭包） — 合并"计划写入意图"判断 | Wave 2A |
| A3: RV-2 wrapper unwrap | 采纳（scope limit） — env/timeout/uv run/poetry run | Wave 2A |
| A4: RV-1 改为 verification coverage gap | 直接采纳 — 不再要求 claim 测试文件 | Wave 2B |
| A5: task event contract | 直接采纳 — 作为 Wave 4 前置 | Wave 4 前置 |
| A6: repo 元数据 | 修改采纳 — 最小 `.cccc/ralph.yaml` plan_defaults | Wave 3 |
| A7: project_root 解析链 | 直接采纳 — CLI > config > git root > plan dir > cwd | Wave 1 |
| A8: covers 规则前移 | 直接采纳 — 移入 validator.py + Wave 1 | Wave 1 |
| B2: 图感知 checkpoint | 采纳方向 — 简化版深度比例，迭代校准 | Wave 2B |
| B3: FS 短路 | 采纳 — fatal structural error 后跳过 FS 校验 | Wave 1 设计, Wave 2 实现 |
| B4: stdlib/第三方处理 | 采纳 — importlib.util.find_spec fallback | Wave 2A |
| B7: WorkspaceIndex | 采纳 — Wave 1 定接口, Wave 2 实现 | Wave 1 设计, Wave 2A 实现 |
| B1: RV-3 证据分层 | 推迟 — 依赖 B5 一起设计 | 后续 |
| B5: ValidationIssue enrichment | 推迟设计到 Wave 1, 实现到 Wave 2 | Wave 2B |
| B6: review_request 提前 | 推迟 — 不是正确性阻塞项 | Wave 5 |
| B8: RV-1 更强召回 | 推迟 — 先纠正语义再扩召回 | 后续 |

### 5.6 明确不做清单（v5 out-of-scope）

| 方向 | 原因 |
|------|------|
| grep 命令静态预检 | 变体过多，误报高 |
| `python -c` 方法存在性检查 | 需要完整 call graph，复杂度过高 |
| Dry-run sandbox 执行 | 环境噪声大 |
| Transitive test dependency | 完整 import graph 的误报/漏报都会急剧上升 |
| Codex 审查结果结构化回写 | v6 |
| 通用 ralph_policy 系统 | scope creep；最小 repo 元数据足够 |
| 运行时自动重派 | v5 只检测+告警 |
| `bash -lc` 等 shell 解析器 | 不属于 wrapper unwrap，归入 complex shell skipped |

### 5.7 与原始方案的主要变更

| 变更 | 原方案 | 修订后 | 原因 |
|------|--------|--------|------|
| Wave 结构 | 4 波 | 5 波 | 新增 Wave 1 Foundation 层 |
| covers 图规则 | Wave 2 | Wave 1 | 纯结构规则应先于 FS 规则（A8） |
| RV-2 文件检查 | 只看当前文件系统 | 合并 projected state | 避免误杀新建文件任务（A2） |
| RV-2 wrapper | 无 | unwrap 常见前缀 | 堵住低成本逃逸面（A3） |
| RV-1 语义 | "未 claim 测试" | "验证覆盖缺口" | 避免污染 write-set（A4） |
| Verification 字段 | 未处理 | 统一为单一真相源 | 消除 plan/runtime 分叉（A1） |
| project_root | cwd | 优先级链 | 避免非项目目录假阳性（A7） |
| WF-NEW-3 前置 | 直接做 stalled 检测 | 先补 task event contract | 缺少 started/progress 事件，检测会高噪声（A5） |
| Composition root | 只靠 planner 手填 | repo 元数据自动注入 | 减少 planner 遗漏（A6） |
| Early checkpoint | 固定阈值 | 图感知深度比例 | 更准确的触发条件（B2） |
| Import 检查 | 只看 repo-local | + stdlib/第三方 fallback | 避免误报外部包（B4） |

---

## 六、Wave 5 实施完成记录

> 日期：2026-04-02
> 范围：RV-1, RV-11, RV-12, RV-13, WF-NEW-3 (monitor wiring)
> 计划文件：plans/wave5-validate-noise.yaml (6 tasks, 3 batches)
> 工作流：计划生成 → Ralph validate (0 error) → Codex 审查 (7 findings fixed) → 并行执行 → 302 tests passed

### 已完成

- ✅ **RV-11**: `awareness_paths` 模型扩展 — `TaskSpec.awareness_paths: List[str]` + `_check_critical_coverage()` 双集合拆分（`owned_paths` = claimed ∪ awareness for entrypoint ownership, `write_paths` = claimed only for _plan_touches_subsystem）
- ✅ **RV-1**: `W_UNCLAIMED_TEST_FOR_SOURCE` — 改源文件漏 claim 测试文件检测。扫描 tests/ 下 import claimed source 的文件，若无任务 claim 该测试则 warn
- ✅ **RV-13**: `ralph validate --suppress CODE...` CLI 参数 — 命令行级代码豁免，内存合并不修改 plan 文件
- ✅ **RV-12**: `W_VERIFICATION_PYTEST_K_NO_MATCH` 降级 — task claims test file → hint（不再 warning）
- ✅ **WF-NEW-3 补全**: `check_unauthorized_subagent` 接入 `on_task_completed()`；`check_path_deviation` 通过 `monitor_incoming_event()` 公共 API 暴露

### 新增诊断码

| 码 | 严重度 | 来源 | 位置 |
|----|--------|------|------|
| `W_UNCLAIMED_TEST_FOR_SOURCE` | warning | RV-1 | filesystem_validator.py |

### 新增模型字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `TaskSpec.awareness_paths` | `List[str] = []` | 读感知路径，不参与 write-set 冲突，满足 entrypoint ownership |

### Codex 审查关键发现（已修复进计划）

1. **T1 函数名错误**：计划写 `_check_critical_entrypoints()` 但实际是 `_check_critical_coverage()`
2. **T1 all_claimed 污染**：naive merge awareness_paths 到 all_claimed 会改变 `_plan_touches_subsystem()` 语义
3. **T4 调用位置不可行**：`check_path_deviation` 在 orchestrator 无合适 event 入口，改为公共 API
4. **T4 check_unauthorized_subagent 时序问题**：检查需在 `_task_to_agent` 更新前
5. **T4 pytest -k 语法错误**：`path_deviation_or_unauthorized` 应为 `"path_deviation or unauthorized"`
6. **T5 early-return 遗漏场景**：_check_path_target 提前返回时 _check_pytest_k 不可达
7. **T-int 未覆盖 T4**：集成测试 addresses/covers 遗漏 WF-NEW-3

---

## 七、Wave 6 实施完成记录

> 日期：2026-04-02
> 范围：RV-10, RV-14, RV-16
> 计划文件：plans/wave6-false-negative.yaml (4 tasks, 3 batches)
> 工作流：计划生成 → Ralph validate (0 error) → Codex 审查 (4 findings fixed) → 并行执行 → 314 tests passed
> 执行中发现回归：conftest.py 被 _is_direct_test_file 错误归类为 indirect → 手动修复

### 已完成

- ✅ **RV-10**: W_TEST_COVERAGE_GAP 召回精炼 — 新增 `_is_direct_test_file()` stem 匹配启发式，direct test → warning (W_TEST_COVERAGE_GAP), indirect import → hint (W_INDIRECT_TEST_IMPORT), conftest 保持独立分类 (W_CONFTEST_COVERAGE_GAP)
- ✅ **RV-14**: `W_SHARED_FILE_PARTIAL_VERIFICATION` — 两依赖任务共享文件但验证均不覆盖 → hint
- ✅ **RV-16**: `W_INTEGRATION_INTERFACE_MISMATCH` — 消费契约但验证不测提供者路径 → hint

### 新增诊断码

| 码 | 严重度 | 来源 | 位置 |
|----|--------|------|------|
| `W_INDIRECT_TEST_IMPORT` | hint | RV-10 | filesystem_validator.py |
| `W_SHARED_FILE_PARTIAL_VERIFICATION` | hint | RV-14 | validator.py |
| `W_INTEGRATION_INTERFACE_MISMATCH` | hint | RV-16 | validator.py |

### Codex 审查关键发现（已修复进计划）

1. **claimed_paths 漏测试文件**：历史 plan 均 claim 测试文件，本计划遗漏
2. **_is_direct_test_file 对短 stem 不稳健**：stem contains 启发式对 "core"/"utils" 等短词可能误匹配
3. **_check_test_coverage_gaps accumulator 需同步改**：_coverage_gap_issue 返回的 code/severity 在上层被丢弃，需重构 accumulator
4. **T2 需 _command_mentions_any_path**：validator.py 无命令解析能力，需复用已有子串检查

---

## 八、RV-17 补充实施记录

> 日期：2026-04-02
> 范围：RV-17（W_VERIFICATION_PYTEST_K_NO_MATCH plan-level 降级）

- ✅ **RV-17**: pytest -k pattern 对 plan 中任意 task claims 的测试文件自动降级为 hint — 新增 `all_plan_claimed` 参数穿透 `validate_filesystem → _check_verification_command → _check_pytest → _check_pytest_k`

---

## 九、RV-23/24/25 实施记录

> 日期：2026-04-02
> 范围：RV-23, RV-24, RV-25（v3 E2E 实战新发现）
> 计划：plans/rv23-24-25-verify-hardening.yaml
> 流程：计划生成 → Ralph validate (0 error) → Codex 审查 #1 (needs-attention, 4 findings) → 实施 → Codex 审查 #2 (needs-attention, 2 findings) → 修复 → 全量测试 219 passed

### 已完成

- ✅ **RV-23**: `_run_verification_check()` 支持 shell 操作符 — 新增 `_has_shell_operators()` 字符级扫描器（跟踪引号状态，正确处理 `echo "a && b"` 不误判、`echo first&&echo second` 正确检测）。检测到操作符时用 `["bash", "-c", command]` 执行，否则保持 `shlex.split` 的安全 argv 模式
- ✅ **RV-24**: 自验证悖论检测 — `workspace_index.projected_paths()` 新增 `include_self=False` 参数；`validate_filesystem` 计算 `upstream_projected` 并贯穿到 `_check_path_target`（py_compile/pytest）和 `_check_import_from`（python -c）。任务验证引用仅自身 claim 的文件/模块时从 "hint" 升级为 "warning"
- ✅ **RV-25**: 可疑执行时间检测 — `_run_verification_check()` 在 `duration_ms < 50` 且命令非 trivial（排除 echo/true/printf）时，message 前缀 `[SUSPICIOUS: completed in Xms]`，details 添加 `suspicious_duration: True`。outcome 保持 "passed" 不阻断工作流

### Codex 审查关键发现（均已修复）

**第一轮审查（计划阶段）**：
1. 测试文件归属错误 — RV-24 测试应放 test_filesystem_validator.py 而非全部放 test_ralph_standalone.py
2. RV-23 shell 检测方案过粗 — 不能用 substring 匹配，需词法级检测
3. RV-24 影响面被低估 — 不应改 `projected_paths()` 全局语义，`_projected_module_candidate` 行为不能受影响
4. RV-25 需边界测试和 monkeypatch

**第二轮审查（实施阶段）**：
1. **[high]** 无空格操作符漏检 — `shlex.split` + token 匹配漏掉 `echo first&&echo second`。修复：改用字符级扫描器
2. **[medium]** `python -c` 导入路径未接 `upstream_projected` — `_missing_module_issue()` 新增 `self_only` 参数

### 新增/变更诊断行为

| 变更 | 来源 | 位置 |
|------|------|------|
| `W_VERIFICATION_TARGET_MISSING` severity 区分 self/upstream | RV-24 | filesystem_validator.py |
| `W_VERIFICATION_IMPORT_MODULE_MISSING` severity 区分 self/upstream | RV-24 | filesystem_validator.py |

### 新增运行时行为

| 行为 | 来源 | 位置 |
|------|------|------|
| shell 操作符命令走 `bash -c` | RV-23 | ralph_service.py |
| `duration_ms < 50` 标记 suspicious_duration | RV-25 | ralph_service.py |

---

## 九b、2026-04-18 文档回补（从未解决清单迁入）

> 说明：以下 3 项在代码与测试中已具备实现证据，2026-04-18 从 `问题清单-v5-ralph.md` 的“未解决”列表迁回 full 文档，避免继续作为待办误导。

### 已确认完成

- ✅ **RO-8n**: `W_VERIFICATION_PYTEST_K_NO_MATCH` 对“将创建测试文件”的场景已降级处理。当前 task claims 测试文件时降为 `hint`；plan 中其他 task claims 同一测试文件时也可降为 `hint`。对应实现与记录见 Wave 5 `RV-12`、`RV-17`。
- ✅ **RO-9n**: `W_VERIFICATION_NO_CHECKS` 已实现并接入 `validate()` 主流程；当 `verification.command` 存在但 `checks=[]` 时会发出 warning，提示拆分 compile / test 等结构化 check。
- ✅ **RO-11**: `failure_path` 字段与 `W_NO_FAILURE_PATH` 规则已实现；涉及 assignment / actor / worker / agent / async 场景但未声明失败处理时，Ralph 会报 warning。当前强度仍为 `warning`，尚未升级为 hard gate。

### 文档对齐说明

- `RO-8n` 的实现证据已在本文档 Wave 5 / Wave 8 记录中存在，本次仅修正其在“未解决”文档中的过期状态。
- `RO-9n` 与 `RO-11` 属于后续代码已实现、但未及时从“未解决”清单迁出的文档漂移；本次一并回补到 full 文档。

---

## 十a、v5-final-six 实施记录

> 日期：2026-04-02
> 计划：plans/v5-ralph-final-six.yaml
> 流程：计划生成 → Ralph 验证(0 error) → Codex 审查(6 findings adopted) → 并行执行(Batch1: T1/T2/T3/T6 × Codex, Batch2: T4/T5 × Codex) → 全量测试

| 任务 | 改进 | 文件 | 新测试 |
|------|------|------|--------|
| T1 (RV-6) | `_collect_pytest_k_names` 递归 ClassDef | filesystem_validator.py | 4 |
| T2 (RV-9) | Plan._provenance PrivateAttr + load/merge 标记 | models.py, plan_io.py | 5 |
| T3 (RO-1) | `_check_flow_segment_ownership` | validator.py | 4 |
| T4 (RO-2) | `_contract_schema_hints_compatible` 深度类型检查 | validator.py | 7 |
| T5 (RO-3) | `_check_role_constraints` (4 个 warning 码) | validator.py | 7 |
| T6 (RO-4) | `suggest()` 两遍排序 + `_unlock_score` | core.py | 6 |

**Codex 审查采纳**：
- F1 (严重): T6 排序在 batch 冲突之前而非之后
- F2 (严重): 用 PrivateAttr 防止 YAML 输入注入
- F3 (高): 只计算真正会被解锁的下游任务
- F4 (高): T3/T5 awareness_paths 交叉用例
- F5 (中): 用 model_dump() 验证不序列化
- F6 (中): 嵌套属性类型不匹配覆盖

**新发现的 Ralph 不足**（NOTE 类）：
- RO-5n: `W_FLOW_SEGMENT_UNOWNED` 对 verification role 的 T-int 类任务过度报警
- RO-6n: 同一 entrypoint 被多个 flow 使用时 `W_FLOW_OWNER_NO_VERIFICATION` 噪音大

**新增规则**：

| 诊断码 | 严重度 | 来源 | 位置 |
|--------|--------|------|------|
| `W_FLOW_SEGMENT_UNOWNED` | warning | RO-1 | validator.py |
| `W_FLOW_OWNER_NO_VERIFICATION` | warning | RO-1 | validator.py |
| `W_INTEGRATION_ROLE_WEAK_VERIFICATION` | warning | RO-3 | validator.py |
| `W_VERIFICATION_ROLE_NO_COVERS` | warning | RO-3 | validator.py |
| `W_VERIFICATION_ROLE_CLAIMS_SOURCE` | warning | RO-3 | validator.py |
| `W_LEAF_ROLE_IS_INTEGRATOR` | warning | RO-3 | validator.py |

**增强（非新码）**：
- `W_CONTRACT_SCHEMA_MISMATCH`: 深度 properties/items/required 类型兼容检查 (RO-2)
- `_collect_pytest_k_names`: 递归 ClassDef 内 test 方法 (RV-6)
- `suggest()`: 按 unlock score 排序 ready 批次 (RO-4)
- `Plan._provenance`: 追踪 merge 来源 (RV-9)

**测试**：252 ralph tests passed

---

## 十、当前规则全量统计（43 条 + 3 行为变更 + 3 运行时增强）

| # | 类别 | 诊断码 | 严重度 | 来源 |
|---|------|--------|--------|------|
| 1 | 图结构 | `E_DUPLICATE_TASK_ID` | error | 基础 |
| 1 | 图结构 | `E_DEP_UNKNOWN` | error | 基础 |
| 1 | 图结构 | `E_DEP_SELF` | error | 基础 |
| 1 | 图结构 | `E_DEP_CYCLE` | error | 基础 |
| 1 | 图结构 | `W_DISCONNECTED_COMPONENTS` | warning | 基础 |
| 1 | 图结构 | `W_ISOLATED_TASK` | warning | 基础 |
| 1 | 图结构 | `W_IMPLICIT_SERIALIZATION` | hint | 基础 |
| 1 | 图结构 | `W_SHARED_FILE_PARTIAL_VERIFICATION` | hint | Wave 6 RV-14 |
| 2 | 字段完整性 | `E_MISSING_CLAIMED_PATHS` | error | 基础 |
| 2 | 字段完整性 | `E_MISSING_VERIFICATION` | error | 基础 |
| 2 | 字段完整性 | `W_EMPTY_ACCEPTANCE` | warning | 基础 |
| 2 | 字段完整性 | `W_GLOBAL_WRITE_CLAIM` | warning | 基础 |
| 3 | 验证强度 | `E_NO_CROSS_TASK_VERIFICATION` | error | 基础 |
| 3 | 验证强度 | `W_WEAK_VERIFICATION_ONLY` | warning | 基础 |
| 3 | 验证强度 | `W_VERIFICATION_DUPLICATE_COMMAND` | hint | Wave 1 |
| 3 | 验证强度 | `W_VERIFICATION_BEHAVIOR_MISMATCH` | warning/hint | Wave 2B RV-4 |
| 3 | 验证强度 | `W_COVERS_CLAIM_UNVERIFIABLE` | warning | Wave 2B RV-3 |
| 4 | 契约 | `E_CONSUMER_WITHOUT_PROVIDER` | error | 基础 |
| 4 | 契约 | `E_CONSUMER_FROM_UNKNOWN` | error | 基础 |
| 4 | 契约 | `W_CONTRACT_SCHEMA_MISMATCH` | warning | 基础 |
| 4 | 契约 | `W_PROVIDER_UNUSED` | hint | 基础 |
| 4 | 契约 | `W_CONSUME_WITHOUT_DEP` | warning | 基础 |
| 4 | 契约 | `W_DEP_WITHOUT_CONSUME` | hint | 基础 |
| 4 | 契约 | `W_INTEGRATION_INTERFACE_MISMATCH` | hint | Wave 6 RV-16 |
| 5 | 关键覆盖 | `E_CRITICAL_ENTRYPOINT_UNOWNED` | error/hint | 基础+RV-7 |
| 5 | 关键覆盖 | `E_CRITICAL_FLOW_UNCOVERED` | error | 基础 |
| 5 | 关键覆盖 | `E_CRITICAL_FLOW_ENTRYPOINT_UNOWNED` | error/hint | 基础+RV-7 |
| 5 | 关键覆盖 | `E_CRITICAL_FLOW_LEVEL_TOO_WEAK` | error | 基础 |
| 5 | 覆盖图 | `E_COVERS_UNKNOWN_TASK` | error | Wave 1 |
| 5 | 覆盖图 | `E_COVERS_WITHOUT_DEP_ORDER` | error | Wave 1 |
| 5 | 覆盖图 | `W_NO_EARLY_INTEGRATION_CHECKPOINT` | warning | Wave 2B |
| 6 | 禁止流 | `E_FORBIDDEN_FLOW_UNCOVERED` | error | 基础 |
| 6 | 禁止流 | `E_FORBIDDEN_FLOW_LEVEL_TOO_WEAK` | error | 基础 |
| 7 | 问题覆盖 | `E_UNCOVERED_REQUIRED_ISSUE` | error | 基础 |
| 7 | 集成脊柱 | `E_MISSING_INTEGRATION_SPINE` | error | 基础 |
| 7 | 集成脊柱 | `W_CROSS_BOUNDARY_WITHOUT_GLUE` | warning | 基础 |
| 8 | 文件系统 | `W_TEST_COVERAGE_GAP` | warning | Wave 2B+Wave 6 |
| 8 | 文件系统 | `W_INDIRECT_TEST_IMPORT` | hint | Wave 6 RV-10 |
| 8 | 文件系统 | `W_CONFTEST_COVERAGE_GAP` | warning | Wave 2B |
| 8 | 文件系统 | `W_UNCLAIMED_TEST_FOR_SOURCE` | warning/hint | Wave 5 RV-1 |
| 8 | 文件系统 | `W_DYNAMIC_TEST_IMPORT_OPAQUE` | hint | Wave 2B |
| 8 | 文件系统 | `W_REGISTRATION_INVARIANT_UNCOVERED` | warning | Wave 3 |
| 8 | 文件系统 | `W_SEMANTIC_DEP_HINT` | hint | v5-remaining |
| 9 | 验证命令预检 | 10 个码（见 §5.4） | 各异 | Wave 2A |
| 10 | 流段所有权 | `W_FLOW_SEGMENT_UNOWNED` | warning | v5-final-six RO-1 |
| 10 | 流段所有权 | `W_FLOW_OWNER_NO_VERIFICATION` | warning | v5-final-six RO-1 |
| 11 | 角色约束 | `W_INTEGRATION_ROLE_WEAK_VERIFICATION` | warning | v5-final-six RO-3 |
| 11 | 角色约束 | `W_VERIFICATION_ROLE_NO_COVERS` | warning | v5-final-six RO-3 |
| 11 | 角色约束 | `W_VERIFICATION_ROLE_CLAIMS_SOURCE` | warning | v5-final-six RO-3 |
| 11 | 角色约束 | `W_LEAF_ROLE_IS_INTEGRATOR` | warning | v5-final-six RO-3 |
| 12 | 验证强度 | `W_VERIFICATION_SHALLOW_CHECKS` | warning | RO-17 |
| 12 | 验证强度 | `W_VERIFICATION_NO_CHECKS` | warning | Batch G |
| 12 | 验证强度 | `W_NO_FAILURE_PATH` | warning | Batch G |
| 13 | Finding 引用 | `W_FINDING_REF_INCOMPLETE` | warning | RO-12 |
| 13 | Finding 引用 | `W_FINDING_REF_UNKNOWN_ENFORCER` | hint | RO-12 |

---

## 十一、RO-7n~RO-19 全量修复实施记录

> 日期：2026-04-19
> 计划：plans/fix-v5-ralph-ro.yaml
> 流程：计划生成 → Ralph 验证(0 error, 5 warning) → Codex 审查(3 CRITICAL + 4 IMPORTANT fixed) → 并行执行(4 batch) → 365 tests passed
> 涵盖：9 项待实施改进全部完成

### 批次执行

| Batch | Task | 改进项 | 文件 | 新测试 |
|-------|------|--------|------|--------|
| 1 | T1 | **RO-15** filesystem validator 目录崩溃 | filesystem_validator.py | 3 (49 total) |
| 1 | T2 | **RO-17** W_VERIFICATION_SHALLOW_CHECKS | validator.py | 5 (22 total) |
| 1 | T7 | **RO-19** 前端测试质量门 | web/package.json, vite.config.ts, ci.yml | 117 vitest |
| 1 | T8 | **RO-18** 质量门 rollout 模式 | cli.py, quality-gate.yaml | 4 (154 total) |
| 2 | T3 | **RO-7n/14n/13n** 流段+叶角色+plan_scope | validator.py, models.py | 8 (162 total) |
| 3 | T4 | **RO-16/12** test_created_by + finding_refs | models.py, validator.py, fsv | 10 (81 total) |
| 4 | T-int | 集成测试 + 回归 | test_v5_ro_integration.py | 7 (365 total) |

### 已完成改进详情

- ✅ **RO-15** (P1): `IsADirectoryError` 修复 — `_load_issue_file_map_cached` 捕获 IsADirectoryError；`_check_pytest` 检测目录路径后跳过 -k 和 node 解析
- ✅ **RO-17** (P1): `W_VERIFICATION_SHALLOW_CHECKS` 规则 — 当 verification.checks 全为 compile/import/help 类（无 pytest behavior test）时 warn
- ✅ **RO-19** (P1): 前端测试质量门 — web/package.json 新增 test/test:run/quality 脚本；vite.config.ts 添加 vitest jsdom 配置；CI 接入 test:run
- ✅ **RO-18** (P2): 质量门 rollout 模式 — .cccc/quality-gate.yaml 配置 terminal/branch/repo 三层 gate；CLI `--gate` 参数支持 shadow/warn/enforce 模式
- ✅ **RO-7n** (P2): Python 符号路径解析 — `_resolve_symbol_entrypoint()` 将 `module.Class.method` 解析为文件路径匹配 owned_paths
- ✅ **RO-14n** (P2): Leaf 角色豁免 — `W_FLOW_OWNER_NO_VERIFICATION` 在 leaf 任务 + integration/verification 角色覆盖时降为 hint
- ✅ **RO-13n** (P2): plan_scope 过滤 — `Plan.plan_scope` 字段 + `_entrypoint_in_scope()` 限制 critical entrypoint 检查范围
- ✅ **RO-16** (P2): test_created_by 支持 — CriticalFlow/ForbiddenFlow 新增 `test_created_by` 字段；未完成的创建任务使 flow uncovered 降为 hint
- ✅ **RO-12** (P2): finding_refs 校验 — `FindingRef` 模型 + `_check_finding_refs()` 校验 id/mitigation/enforced_by

### 新增模型字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `Plan.plan_scope` | `List[str] = []` | 限定 critical entrypoint 检查范围 |
| `Plan.finding_refs` | `List[FindingRef] = []` | 结构化 finding 引用与缓解措施 |
| `CriticalFlow.test_created_by` | `List[str] = []` | 标记测试由哪个任务创建（延迟检查） |
| `ForbiddenFlow.test_created_by` | `List[str] = []` | 同上 |
| `BatchResult.task_metadata` | `Dict[str, Any] = {}` | 每任务元数据（verification_mode 等） |
| `BatchResult.batch_sequence` | `int = 0` | 批次序号 |
| `BatchResult.batch_boundary` | `bool = True` | 批次边界标记 |

### Codex 审查关键发现（均已修复进计划）

1. **[CRITICAL] T7 缺 CI 文件**：RO-19 要求 CI 接入但 claimed_paths 未包含 .github/workflows/ci.yml → 已加入
2. **[CRITICAL] T3 测试文件放错**：flow/entrypoint 测试应在 test_ralph_standalone.py 不是 test_workflow_state.py → 已迁移
3. **[CRITICAL] T3 RO-14n 条件写错**：只检查 covering_ids 非空，未过滤 role → 改为过滤 integration/verification role
4. **[IMPORTANT] T4 漏 claim filesystem_validator 测试**：修改 _check_pytest_k 但未 claim 对应测试文件 → 已加入
5. **[IMPORTANT] T3 awareness_paths 回归**：helper 只看 claimed_paths 会漏掉 awareness ownership → 改为使用 owned_paths
6. **[IMPORTANT] T4 enforced_by 校验**：RO-12 要求 enforced_by 绑定已知 ID → 从 optional 改为 required
7. **[IMPORTANT] T7 jsdom 依赖缺口**：vitest environment: "jsdom" 需要安装 jsdom 包 → 加入 goal_behavior

### 实践新发现的 Ralph 不足

- **RO-20** (P2): Worker 越界修改 claimed_paths 之外的文件 — T-int Codex worker 修改了 agent.py、core.py、workspace_index.py、plan_io.py（均不在 claimed_paths 中）。verify gate 无法拦截。建议新增 `W_WORKER_EXCEEDED_SCOPE`
- **RO-13n-obs** ~~(已知局限)~~ **已修复**: ~~已有测试引用未实现功能~~ → RO 全量修复时补充了 batch_sequence/batch_boundary/verification_mode 实现，6 测试全部通过

### E2E v13 验证结果（2026-04-19）

> 干净 group g_3d4bace911d9，5 任务笔记应用，9 分钟完成
> 报告：todo/e2e-实战评估报告-v13.md

| 维度 | 分数 | 关键发现 |
|------|------|----------|
| 结果 | 4/5 | 0 CRITICAL（v5 的 SQLite 错误处理已通过验收标准驱动修复）, 8 WARN |
| 过程 | 4/5 | verification_passed 5/5，自动闭环 4/5（T2 completer_mismatch），DAG 门控生效 |
| 体验 | 3.5/5 | Ralph validate/suggest/verify 全部正面，Worker 不自行 complete 是主要摩擦 |
| 综合 | 3.8/5 | 历史最高 |

RO 改进在 v13 中的验证效果：
- ✅ **RO-17 (W_VERIFICATION_SHALLOW_CHECKS)**: 验收标准中明确要求 behavior test，Worker 遵守。但 checks 深度仍不够（无并发/错误路径测试）—— 属 RO-17 "acceptance→checks 交叉检查" 增强方向
- ✅ **RO-15**: 未触发目录路径崩溃（v13 plan 未使用目录路径验证命令，但修复已就绪）
- ✅ **RO-19**: web/package.json 测试脚本 + CI 接入已生效（117 vitest tests）
- ℹ️ **RO-18/13n/14n/7n/16/12**: v13 E2E 使用干净 plan，未直接触发这些改进的场景

### 实践新发现

- **RO-21** (P2): Ralph validate 执行无 ledger 事件 — Codex 过程审查发现 batch_registered 时戳早于 validate 声明。ralph validate 通过 CLI 执行不向 ledger 写事件，无法审计"先验证再提交"。对应 v3 问题清单 FIX-E2E-5

---

## v14 E2E 验证确认（2026-04-22）

> 来源：E2E v14 全栈笔记应用实战，2146 tests pass
> 评估报告：[e2e-实战评估报告-v14.md](./e2e-实战评估报告-v14.md)

### 已验证修复

| 编号 | 问题 | 解决方式 | 验证 |
|------|------|----------|------|
| RO-20 | Worker 越界修改 claimed_paths 之外文件 | `W_WORKER_EXCEEDED_SCOPE` warning 在 verify gate `_build_scope_warnings()` | 代码验证 + 2146 tests pass |
| RO-22 | schema_version forbid 无迁移引导 | `_format_allowed_fields()` 附加允许字段列表到错误信息 | 代码验证 + 2146 tests pass |
| RO-23 | required_issues 格式不一致 | `_required_issues_format_issue()` 检测 dict→string 并附示例 | 代码验证 + 2146 tests pass |

### 部分修复

| 编号 | 问题 | 现状 |
|------|------|------|
| RO-21 | validate 无 ledger 事件 | `_write_validation_event()` 已实现，但 v14 Foreman 未传 --group 参数，ledger 无事件。需自动检测 group |

### v14 实践新发现

- **RO-24** (P2): Verification checks 跨 task scope 未检测 — T1 的 check `pytest backend/tests/` 引用了 T2 的 claimed_paths，T1 首次 verification_failed 因 T2 尚未创建测试目录。ralph validate 应检测 checks 命令中的路径是否在当前 task 的 claimed_paths 范围内

### v14 E2E 评分

| 维度 | v14 |
|------|-----|
| 结果 | 2/5 |
| 过程 | 3/5 |
| 体验 | 3.8/5 |
| 综合 | 3.0/5 |

---

## 2026-04-25 Codex 复核新增问题

### RO-32 AI 修复测试/验收准入标准缺失（P1）
> **来源**：2026-04-25 Codex 复核 + 用户反馈

- **问题**：项目已有“真实场景验收”“verify gate”“E2E 实战”的设计原则，但没有沉淀为 P1/P2 修复的硬性测试准入标准。AI 容易用局部 mock、schema smoke、helper 单测或错误预期测试证明“测试通过”，真实 CLI/IPC/daemon 路径仍未被验证。
- **典型表现**：
  1. IPC verification 测试只断言 fake orchestrator 被调用，不断言 `WorkflowEngine` 状态变化。
  2. TTL cleanup 测试使用 `_created_at` synthetic 数据，没有覆盖 handler 真实写入的 `created_at`。
  3. 状态源合并测试没有构造 engine 空但 shadow state 污染的负向场景。
  4. RA-3 测试曾把 `agent_pending` 可 complete 的错误行为固化为预期。
- **改进方向**：建立测试等级与验收准入：`runtime-contract`、`unit-contract`、`schema-smoke`、`api-surface`。P1/P2 修复必须至少有一个 `runtime-contract` 测试，从 CLI/IPC op/daemon public entrypoint 进入，断言 public response、`WorkflowEngine`/ledger 权威状态和实际副作用。
- **验收标准**：每个 P1/P2 修复必须提供修复前失败、修复后通过的真实入口测试；mock 不得替代被验证核心调用链；涉及”不再 fallback/不再 completed/不再 sync”的需求必须有负向测试；浅层 smoke 测试不得单独作为完成依据。

---

## 2026-05-01 E2E v15 实测归档

### v15 E2E 评分

| 维度 | v15 | 审查者 |
|------|-----|--------|
| 结果 | 3/5 | Codex（1 CRITICAL: title=null 崩溃搜索主流程） |
| 过程 | 5/5 | Codex + 内置 Agent 一致（10/10） |
| 体验 | 4/5 | Foreman 自评 |
| 综合 | 4.0/5 | 历史最高 |

### RF-2026-04-25-1 IPC verification 回写 — ✅ v15 验证通过
> v15 E2E 中 5/5 任务的 `workflow.verification_passed` 事件含真实 `checks[]`（name + outcome=passed + stdout 捕获 + duration_ms），engine state 从 running → completed 正确转换。此项从”待完整回归”升级为”已验证”。

### RO-35 Gemini CLI trust directory 导致 Ralph Agent 失败 — ✅ 已修复
> **来源**：2026-05-01 E2E v15
> - **现象**：`ralph validate` 在非信任目录（如 `/tmp/`）运行时 Gemini CLI 返回 exit code 55（”not running in a trusted directory”）
> - **根因**：Gemini CLI v0.40+ 要求运行目录被显式信任；Ralph Agent 的 `_gemini_command()` 未带 `--skip-trust`
> - **修复**：在 `src/cccc/ralph/agent.py::_gemini_command()` 中加 `--skip-trust` 标志
> - **验证**：v15 第二轮 `ralph validate` 包含 Gemini Agent review，`workflow.plan_validated` valid=true

### RO-41 E_AGENT_REVIEW_FAILED 阻塞 validate 当 Agent 不可用 — ✅ 已修复
> **来源**：2026-05-02 v16 plan validate 实践
> - **现象**：`ralph validate plans/fix-v5-open-issues.yaml` → Gemini CLI 超时或返回无效 suggestion → `E_AGENT_REVIEW_FAILED` error → 规划 AI 被迫添加 `suppress_codes: [E_AGENT_REVIEW_FAILED]`
> - **根因**：Agent 不可用/返回异常时 validate 阶段报 error 阻塞验证流程。suppress 后降低了验证可信度 — 无法区分"Agent 发现真实问题"和"Agent 自身故障"
> - **修复**：`src/cccc/ralph/cli.py::_agent_review_failure_issue()` — `E_AGENT_REVIEW_FAILED` (error) → `W_AGENT_REVIEW_SKIPPED` (warning)。Agent 不可用时结构性验证不被阻塞，Agent 审查结果以 warning 形式呈现
> - **触发实例**：v16 plan validate 因 Gemini CLI 30s 超时触发 error，必须 suppress 才能继续工作流

### v15 验证的已有修复生效确认

| 修复 | v15 验证证据 |
|------|-------------|
| FIX-1 (metadata 传递) | 5 个 task_registered 含完整 claimed_paths + verification.checks + contracts |
| FIX-2 (auto-dispatch) | 5/5 任务由 service:workflow_orchestrator 自动下发，100% 自动化 |
| FIX-3 (DAG gating) | 每个任务在依赖 verification_passed 后 14-39s 内启动 |
| FIX-5 (verification 语义) | 5/5 verification_passed 含真实 checks、stdout、exit code，无 skipped |

### v15 新发现问题

| 编号 | 严重度 | 状态 | 说明 |
|------|--------|------|------|
| RO-34 | Medium | 未解决 | actor restart 后 inbox 消息不重投递，Foreman idle 8 分钟 |
| RO-35 | Medium | ✅ 已修复 | Gemini CLI trust directory，`--skip-trust` 修复 |
| RO-36 | Medium | 未解决 | Foreman 批次手工 submit 摩擦，5 任务 = 5 次手工 submit |

### v15 代码验证确认已解决的条目（11 项）

以下条目在 2026-05-01 通过代码逐项验证确认已实现，从主文档移入 full。

| 编号 | 验证结果 | 代码证据 |
|------|----------|---------|
| RO-24 | ✅ RESOLVED | `validation_rules/coverage.py:293-364` 实现 `_check_verification_cross_scope()`，发出 `W_VERIFICATION_CROSS_SCOPE` warning；有专项测试 `test_cross_scope_verification.py` |
| RO-25 | ✅ RESOLVED | `verification_gate.py:173-185` 将 skipped 路由到 `on_task_failed_fn()`；`workflow_state_engine.py:594,679` 映射 `KIND_VERIFICATION_SKIPPED_BLOCKED` → FAILED；测试 `test_ralph_verification_skipped_block.py:125-137` |
| RO-26 | ✅ RESOLVED | `ralph_service.py:153` 注释 `"RO-26: _task_statuses removed"`；仅保留 `_task_refs`(cache) 和 `_processed_keys`(dedup)；engine 为唯一写入源 |
| RO-27 | ✅ RESOLVED | `ralph_ipc_handler.py:287-288` 缺 group_id/project_root 返回 error；`assignment_batches.py:143-147` fallback 需显式 `fallback_allowed` 标志 |
| RO-28 | ✅ RESOLVED | `kernel/claimed_paths.py:31-87` 统一 `normalize_write_set()` + `paths_overlap()`；`ralph/core.py:26-31` 和 `validation_rules/coverage.py:11` 均从 kernel 导入 |
| RO-29 | ✅ RESOLVED | `models.py:374-383` BatchResult 无重复字段；`test_batch_result_defaults.py:21-25` 防回归测试 |
| RO-32 | ✅ RESOLVED | `docs/standards/CCCC_TESTING_ACCEPTANCE_V1.md` 定义 P1/P2 runtime-contract 准入标准 |
| RO-33 | ✅ RESOLVED | `assignment_startup.py:112-118` 现在传 `issues`/`recommended_tests`/`forbidden_flows` 给 `_build_task_prompt()` |
| RA-1 | ✅ RESOLVED | `agent.py:30,45,135,182` 真实 Gemini CLI 调用；`cli.py:249-252` `--no-agent` 标志 |
| RA-2 | ✅ RESOLVED | `ralph/beyond_scope_checklist.yaml` 存在；`models.py:406` `ValidationIssue.beyond_scope: bool = False` |
| RA-3 | ✅ RESOLVED | `models.py:118` `verification_mode: Literal["ralph","agent"]`；`core.py:187-188` + `ralph_service.py:506-513` agent 模式路由 |

## 2026-05-02 E2E v16 实测归档

### v16 E2E 评分

| 维度 | v16 | 审查者 |
|------|-----|--------|
| 结果 | 3/5 | Codex（1 CRITICAL: javascript: URL XSS，4 WARN） |
| 过程 | 3/5 | Codex（8/10 正面，自动化 14.3%，29 monitor_violation） |
| 体验 | 3/5 | Foreman 自评 |
| 综合 | 3.0/5 | PTY worker 可靠性 + digest 同步退步 |

### RO-34 Actor restart 后 inbox 消息不重投递 — ✅ v16 验证通过
> **来源**：2026-05-01 E2E v15（发现），2026-05-02 v16（验证解决）
> - **原现象**：v15 Foreman restart 后 idle 8 分钟，inbox 消息不重投递
> - **修复**：`actor_lifecycle_ops.py:34-42` `_reset_inbox_cursor_on_actor_restart()` 在 restart 时删除 cursor
> - **v16 验证**：2 次 `actor.restart`（backend-worker 07:47:25, frontend-worker 07:47:26），frontend-worker restart 后恢复工作（T4 heartbeat 09:39:38），无需手动发送提醒消息

### RA-4 两阶段拆分对齐 — ✅ v16 验证通过
> **来源**：2026-04-04 工作流蓝图 v0.3
> - **要求**：suggest() 输出 Task 批次，正确反映依赖和写冲突
> - **v16 验证**：4 个 batch 严格按依赖+写冲突调度：[T1]→[T2(backend/)+T4(frontend/)]→[T3(backend/tests/)+T5(frontend/)]→[T6(frontend/)+T7(tests/)]。T2+T4 并行（不同 claimed_paths），不等彼此完成。suggest 算法在 Task 级拆分 + Module 级并行模型中工作正常

### v16 验证的已有修复生效确认

| 修复 | v16 验证证据 |
|------|-------------|
| FIX-1 (metadata 传递) | 7 个 task_registered 含完整 claimed_paths + verification.checks(1-3个) + provides/consumes + depends_on |
| FIX-2 (auto-dispatch) | T1→[T2,T4] 1s 自动推进；T5→[T6,T7] 2s 自动推进；首次 submit 后无需手工 submit |
| FIX-3 (DAG gating) | 4 batch 严格按依赖顺序，不等整批完成，单任务完成即解锁下游 |
| FIX-4 (stall detection) | 29 个 monitor_violation 正确检测 T2/T4/T6 的 stall（300s 阈值） |
| FIX-5 (verification 语义) | 7/7 verification_passed 含真实 checks(15个 total)、outcome=passed，无 skipped |

### v16 新发现问题

| 编号 | 严重度 | 状态 | 说明 |
|------|--------|------|------|
| RO-38 | P0 | 未解决 | plan_digest_divergence 死锁：`ralph complete` 改 plan.yaml → engine digest 过期 → task complete 被 veto（5 次） |
| RO-39 | P1 | 未解决 | manual completion 不触发 auto-advance：Foreman 手动 complete T2 后 T3 未自动推进 |
| RO-40 | P1 | 未解决 | PTY Worker completion protocol 缺失：1/7 自主完成率，6 个 completer_mismatch |

### v16 退步分析

| 指标 | v15 | v16 | 退步原因 |
|------|-----|-----|----------|
| 过程 | 5/5 | 3/5 | PTY worker 1/7 自主率（v15 100%）；29 monitor_violation |
| 体验 | 4/5 | 3/5 | plan_digest_divergence 新问题；双状态机冲突 |
| 结果 | 3/5 | 3/5 | 持平：v15 title=null → v16 javascript: XSS（类型不同） |

---

## v17-v19 已解决条目（2026-05-02/03 三轮 E2E 验证）

### RO-37 Verification gate 对 Worker 自测盲区无对抗能力 — ✅ v17-v19 E2E 验证通过
> **来源**：2026-05-01 E2E v15 Codex 审查；v16 再次印证
> **代码修复**：三层架构全部实现：
>   1. Ralph validate 层：`W_CRITICAL_FLOW_WORKER_ONLY_VERIFICATION` warning（coverage.py:679-701）
>   2. Engine 默认层：auto-upgrade verification_mode 到 challenge（ralph_service.py:526-534）
>   3. Agent 审查层：challenge 模式先执行 worker verification 再 Agent 对抗（ralph_service.py:589-612）
> **E2E 验证**：v17/v18/v19 三轮均确认 challenge mode 自动升级并执行。T1-T4 全部走 challenge 路径。
> **残留**：challenge agent（Gemini）产生假阳性（见 RO-42），但机制本身已正确运行。

### RO-38 plan_digest_divergence 死锁 — ✅ v18+v19 E2E 验证通过
> **来源**：2026-05-02 E2E v16 实战
> **代码修复**：structural digest 排除 state 字段（plan_io.py:74-87 `_strip_plan_state()`），测试覆盖（test_digest_state_exempt.py）
> **E2E 验证**：v17/v18/v19 连续 3 轮 0 次 plan_digest_divergence 事件

### RO-39 manual completion 不触发 auto-advance — ✅ v19 E2E 验证通过
> **来源**：2026-05-02 E2E v16 实战
> **代码修复**：`_resuggest_ready_tasks()` 无条件调用（assignment_completion.py:36），测试覆盖（test_manual_complete_resuggest.py）
> **E2E 验证**：v17/v18 被 RO-41 cwd bug 掩盖；v19 通过 --force 在引擎内完成后下游批次自动出现（Codex 日志分析确认）

### RO-40 PTY Worker completion protocol 缺失 — ✅ 2026-05-02 Codex 审查确认已实现
> **来源**：2026-05-02 E2E v16 实战
> **解决**：agent_pool.py:530-534 已有完整 COMPLETION PROTOCOL section，prompt_builder.py:295 有 runtime hint

### RO-41 verify gate cwd bug — ✅ v18+v19 E2E 验证通过
> **来源**：2026-05-02 E2E v17 实战
> **代码修复**：CLI 端 plan_path resolve 为绝对路径（workflow_cmds.py:139），daemon 端 _store_workflow_meta resolve（assignment_batches.py:288），_load_cached_workflow_plan fallback 到 project_root（ralph_service.py:986）
> **E2E 验证**：v17 T1 全部 FileNotFoundError；v18+v19 T1 verification_passed，verify gate 正常运行

### RO-43 auto-dispatch 不抗故障 — ✅ v19 E2E 验证通过
> **来源**：2026-05-02 E2E v17 实战
> **代码修复**：retry_task() 末尾调用 _resuggest_ready_tasks()（workflow_orchestrator.py:1292）
> **E2E 验证**：v18 retry 后任务重新 started（7 次 vs 5 个任务）；v19 自动化率 88.9%（8/9 批次自动）

### RO-44 challenge 失败后无 foreman override 机制 — ✅ v19 E2E 验证通过
> **来源**：2026-05-03 E2E v18 实战
> **代码修复**：`--force` flag 线程传递 CLI→daemon→orchestrator→verification_gate，hook_ctx.force_complete 跳过 verify gate（verification_gate.py:138-148）
> **E2E 验证**：v19 4/4 任务成功使用 `cccc task complete --force` 绕过 challenge 假阳性，下游自动推进

### RO-36 Foreman 批次手工 submit 摩擦 — ✅ v19 E2E 验证通过
> **来源**：2026-05-01 E2E v15 Foreman 体验反馈
> **解决**：`--auto-dispatch --assignment-map` + DAG gating + RO-39 修复 + RO-44 --force 联合作用
> **E2E 验证**：v19 自动化率 88.9%（8/9 批次自动），Foreman 只需一次 `cccc workflow submit`

### RO-42 challenge verification 假阳性 — ✅ v20 核心修复验证通过（残留子问题拆分为 RO-45/46）
> **来源**：2026-05-02 E2E v17 实战；v18/v19 连续印证
> **解决**：commit bc32665 实现 `_run_verification_pre_check()` + `verification_output` / `source_code` / `git_diff` 三类证据注入 daemon-path agent
> **压力测试**：13 个 live Gemini 测试全部正确判定（改进前 0/5 → 改进后 13/13），幻觉率从 100% 降为 0%
> **E2E v20 验证**：5 任务中 4 个一次通过 challenge，1 个重试后通过（首次失败因 RO-45/46 子问题）；过程分从 3/5 跃升至 5/5
> **残留**：拆分为 RO-45（directory paths 未展开）和 RO-46（新项目 git diff 为空）

### RL-3 含 shell 操作符的验证命令被跳过 — ✅ bc32665 实现 shell operator 拆分
> **来源**：2026-05-02 fix-v5-remaining 计划轮次
> **解决**：commit bc32665 实现 quote-aware scanning 将 &&/; 拆分为子命令逐个执行，不再整体 skip
> **测试**：`tests/ralph/test_shell_operator_split.py` 覆盖
> **E2E v20**：本轮 plan.yaml 无 && 命令，未触发，但代码已验证

### RL-5 W_INDIRECT_TEST_IMPORT 对高 import 文件爆炸 — ✅ bc32665 实现 ≥10 条折叠
> **来源**：2026-05-02 fix-v5-remaining 计划轮次
> **解决**：commit bc32665 对 ≥10 条 W_INDIRECT_TEST_IMPORT hints 折叠为单条摘要
> **测试**：`tests/ralph/test_indirect_import_fold.py` 覆盖
> **E2E v20**：本轮 plan.yaml 结构简单无大量 import，未触发，但代码已验证

### RO-30 RalphService 运行时接口与文档设计漂移 — ✅ bc32665 修复文档
> **来源**：2026-04-24 Codex 设计审查
> **解决**：commit bc32665 替换 cccc_message_send 引用为 CLI 等价命令；新增 Ralph 三形态描述（CLI 静态验证 / daemon 内 verify gate / Agent 审查）
> **E2E v20**：文档与代码职责一致

### RO-49 verification check 默认 60s 超时对集成测试过短 — ✅ v21 E2E 验证通过
> **来源**：2026-05-03 E2E v20 T5 验证超时
> **解决**：`VerificationCheckSpec` 和 `CheckSpec` 增加 `Optional[int] timeout`；`_run_verification_check` 和 `_run_check` 优先使用 spec timeout，fallback 到默认值
> **测试**：`tests/test_verification_timeout.py`（5 passed）
> **E2E v21 验证**：T6 run_integration check 180s timeout（实际 3650ms），T4 install check 120s timeout（实际 1675ms）。自定义 timeout 被引擎正确使用

### RO-50 已完成任务收到虚假失败通知 — ✅ v21 E2E 验证通过
> **来源**：2026-05-03 E2E v20 Foreman inbox 混乱
> **解决**：`on_task_failed()` 检查 `_active_workflows` 中 task 的 terminal 状态（completed/archived），跳过覆写和通知
> **测试**：`tests/test_terminal_state_guard.py`（4 passed）+ `test_foreman_workflow.py` 回归通过
> **E2E v21 验证**：T1 的 3 次失败全在最终 completed 之前（retry 循环中）。完成后无虚假失败通知

### RO-54 下游 auto-dispatch 需手工 re-submit — ✅ v22 E2E happy path 验证通过（残留异常路径 → RO-55）
> **来源**：2026-05-07 E2E v21 Foreman 体验反馈
> **代码修复**：`_auto_dispatch_ready_tasks()` 方法 + `_resuggest_ready_tasks()` 中调用（workflow_orchestrator.py:696-814）；`WorkflowMeta.auto_dispatch` + `assignment_map` 字段
> **单测**：`tests/test_dag_auto_dispatch.py`（4 passed）
> **E2E v22 验证**：✅ T1→T2→T3 全部通过 `-auto` 后缀批次自动分发，零 Foreman 干预。batch IDs: `ralph-51cbd0177c9e-auto`(T2), `ralph-68c39feb22c6-auto`(T3)
> **残留**：stall→fail→retry 后 auto-dispatch 断裂（→ RO-55），因 `auto_dispatch` 设置未持久化到 engine 级

### RO-48 stall detection 无自动重分配 — ✅ v22 E2E stall detection 首次真实触发
> **来源**：2026-05-03 E2E v20 Foreman 体验反馈
> **代码修复**：`WorkflowMeta.stall_auto_reassign` + `_handle_stalled_task` + `check_stalled_tasks()` sweep
> **单测**：`tests/test_stall_auto_reassign.py`（4 passed）
> **E2E v22 验证**：✅ T4 Gemini worker 315s 零输出 → `monitor_violation` at threshold=300s → Foreman 收到 `status: stalled` 通知。触发了自动 retry（`workflow.retry_requested`），但 retry 路由回原 stalled worker（→ RO-56）。Foreman 手工创建 `frontend-worker-2`(claude) 并重新分配

## v22 新发现问题（2026-05-07 E2E v22）

### RO-55 retry-reassign 后 auto-dispatch 断裂 — ✅ v23 E2E 验证通过

> **来源**：2026-05-07 E2E v22 T4 stall→retry 后 T5/T6 需手工提交
- **严重度**：High — 直接导致自动化率从 100%（v20）降至 33%
- **现象**：T4 stall→fail→retry→manual re-submit 后，`auto_dispatch` 和 `assignment_map` 丢失，T5/T6 回退为 `tasks_ready` 需 Foreman 手工 `cccc workflow submit`
- **日志证据**：T5 batch `2a82d3a4-fcf2`（手工），T6 batch `bdd278f1-9fc6`（手工），均无 `-auto` 后缀
- **根因**：`auto_dispatch` 和 `assignment_map` 仅存在于 orchestrator 的 `_active_workflows` 字典，manual re-submit 创建新 batch 时无法继承
- **改进方案**：将 `auto_dispatch` 和 `assignment_map` 持久化到 `WorkflowMeta`（engine 级），retry/re-submit 后从 engine 读取
- **验收标准**：T4 stall→retry 后，T5 仍通过 `-auto` 批次自动分发
- **v23 验证**：✅ T1 retry 后 auto_dispatch 和 assignment_map 持续生效，T2/T3/T4 均通过 `-auto` 批次自动分发（batch IDs: `ralph-58706f453a16-auto`, `ralph-1bfb397b4345-auto`, `ralph-1477adfa5264-auto`）

### RO-56 retry 不支持 --assign 切换 worker（P1，v22 发现）

> **来源**：2026-05-07 E2E v22 Foreman 体验反馈
- **严重度**：Medium — retry 自动发回原 stalled worker，需 3 步手工操作
- **现象**：`cccc workflow retry T4` 自动分配给已 stalled 的 `frontend-worker`（gemini），而非新创建的 `frontend-worker-2`（claude）
- **日志证据**：`retry_requested` 后 `batch_approved` 仍分配给 `frontend-worker`（事件 `70e3ccbf`、`7134d51d`）
- **根因**：retry 使用 assignment_map 中的原始 agent_id，无法指定替代 worker
- **改进方案**：添加 `cccc workflow retry TASK_ID --assign ACTOR_ID` 标志
- **验收标准**：retry 可一步完成 worker 切换

### RO-57 re-submit 创建隐式 workflow_id（P1，v22 发现）

> **来源**：2026-05-07 E2E v22 T4 re-submit 后 worker 报 workflow_id_mismatch
- **严重度**：Medium — `cccc task complete T4` 报错，需 Foreman 用 `--workflow-id` 显式指定
- **日志证据**：T6 worker 自报 `workflow_id_mismatch`（事件 `30685512`）
- **根因**：单独 `cccc workflow submit` 已有 task 时创建子 workflow-id（如 `kanban-v22-t4`）
- **改进方案**：re-submit 已有 task 时应重用原 workflow_id
- **验收标准**：worker `cccc task complete` 无需指定 `--workflow-id`

### RO-58 `cccc send` 不更新引擎状态（P1，v22 发现）

> **来源**：2026-05-07 E2E v22 T4 手工发送后 worker 无法 complete
- **严重度**：Medium — 手工 `cccc send` 绕过引擎，task 仍在 `ready` 状态
- **根因**：chat message 不触发引擎状态转换
- **改进方案**：当 `cccc send --to WORKER` 的消息包含 `[Foreman Assignment] Task ID: XXX` 时，自动将 task 状态推进到 `running`
- **验收标准**：手工发送后 worker 可直接 `cccc task complete`

### RO-59 batch 注册含已完成 task 报 E_INTERNAL_REGISTER（P1，v22 发现）

> **来源**：2026-05-07 E2E v22 Foreman 尝试提交 T1+T4 批次
- **严重度**：Medium — 2 次 `ralph_internal_error`
- **日志证据**：事件 `cc62724c`（06:12:14）和 `d2707a8c`（06:16:41），`ValueError: cannot register batch: task T1 in non-batchable status completed`
- **根因**：batch 注册不过滤已完成 task
- **改进方案**：batch 注册时自动跳过已完成的 task（或 Foreman 端在提交前过滤）
- **验收标准**：包含已完成 task 的 batch 不报错，自动过滤

### RO-47 retry 后 auto-dispatch assignment-map 丢失 — ✅ v23 E2E 验证通过

> **来源**：2026-05-03 E2E v20 Foreman 体验反馈
- **严重度**：Medium — T2 重试后不继承原始 assignment-map，需手工 re-submit
- **根因（Codex 审查修正）**：stall 任务处于 RUNNING，`retry_after_verification()` 只接受 VERIFYING/FAILED → retry 直接报错
- **实现**：`retry_task()` 对 RUNNING 先调 `fail_task()` 转 FAILED 再 retry；新增 `engine.fail_task()` 方法
- **单测**：`tests/test_retry_running_task.py`（2 passed）
- **v21 验证**：✅ T1 retry 3 次均被重新分配到 backend-worker。但 Foreman 仍需手工 re-submit（→ RO-54）
- **v23 验证**：✅ T1 retry 后自动重新分配到 worker-be，后续 T2/T3/T4 通过 auto-dispatch 继续自动分发

---

## v23 新发现问题（2026-05-11 E2E v23）

### RO-60 verification 命令 shell 语义（P0，v23 发现）

> **来源**：2026-05-11 E2E v23 T1 验证失败
- **严重度**：High — 直接导致正确代码验证失败 + 触发 digest divergence 级联
- **现象**：verification check command `PYTHONPATH=backend python -c '...'` 被 subprocess 解释为查找名为 `PYTHONPATH=backend` 的可执行文件，报 `[Errno 2] No such file or directory`
- **日志证据**：`workflow.verification_failed` 事件 18:00:42，check `test` outcome=`failed`，message=`test failed to start: [Errno 2] No such file or directory: 'PYTHONPATH=backend'`
- **根因**：`ralph_service.py` 的 verification runner 对不含 shell 操作符（`&&`, `||`, `|`, `;`）的命令使用 `subprocess.run(shlex.split(cmd))`，不经过 shell。`VAR=val cmd` 是 shell 语法，不是 exec 语法
- **改进方案**：(A) 扩展 shell 操作符检测增加 `VAR=` 模式（`re.search(r'\b\w+=\S+ ', cmd)`）；或 (B) Ralph validate 对 verification command 中的 `VAR=val` 模式发出 `W_VERIFICATION_SHELL_SYNTAX` warning
- **验收标准**：`PYTHONPATH=backend python -c '...'` 格式的命令能正确执行

### RO-61 plan_digest_divergence 分级（P0，v23 发现）

> **来源**：2026-05-11 E2E v23 全流程被 digest guard 阻塞
- **严重度**：High — 20 次 divergence 事件，4/4 任务需 `--force` 完成
- **现象**：Foreman 修改 plan.yaml 的 verification command（从 `PYTHONPATH=...` 改为 `sh -c '...'`）后，所有 workflow 操作（task complete, fail, retry）被 digest guard 拒绝
- **日志证据**：20x `workflow.plan_digest_divergence` + 4x `plan_digest_divergence_post_hoc`
- **根因**：digest guard 对 plan.yaml 做全文 hash，不区分核心字段（task ID / depends_on / claimed_paths）和运维字段（verification.checks.command）
- **改进方案**：将 digest 分为 structural digest（核心字段：task id, depends_on, claimed_paths, role, type）和 operational digest（运维字段：verification.checks.command, goal_behavior）。structural 变更严格 guard，operational 变更只发 advisory warning
- **验收标准**：修改 verification command 后 task complete 不被 digest guard 阻塞

### RO-62 force-complete 产生 verification_passed 事件（P1，v23 发现）

> **来源**：2026-05-11 E2E v23 交叉验证
- **严重度**：Medium — 语义误导，Foreman 和日志分析可能将 skipped 误判为 passed
- **现象**：`--force` 跳过验证的 task 产生 `workflow.verification_passed` 事件，summary 为 `verification skipped: foreman force-complete override`
- **日志证据**：T2/T3/T4 的 `workflow.verification_passed` 事件 checks=[]，summary=`verification skipped: foreman force-complete override`
- **根因**：force-complete 路径复用了 verification_passed 事件类型
- **改进方案**：force-complete 应产生 `verification_skipped` 或 `verification_overridden` 事件（同 FIX-5 原则）
- **验收标准**：force-complete 不产生 `verification_passed` 事件

### RO-63 ASSIGNED 状态不可 retry/fail（P1，v23 发现）

> **来源**：2026-05-11 E2E v23 T3 Gemini stall 后无法回收
- **严重度**：Medium — Foreman 无干净途径回收 stalled assigned task
- **现象**：`cccc workflow retry T3` 拒绝操作（"task not retryable: status=assigned"），`cccc workflow fail T3` 也因 digest divergence 被拒
- **根因**：retry/fail 的状态前置条件只接受 RUNNING/VERIFYING/FAILED，不接受 ASSIGNED
- **改进方案**：扩展 retry 和 fail 的状态前置条件，增加 ASSIGNED
- **验收标准**：ASSIGNED 状态的 task 可以 retry 或 fail

### RO-64 stall detection 不覆盖 ASSIGNED 状态（P1，v23 发现）

> **来源**：2026-05-11 E2E v23 T3 Gemini 5+ 分钟无响应
- **严重度**：Medium — ASSIGNED 但未启动的 worker 不会被 stall detection 发现
- **现象**：worker-fe (Gemini) 分配 T3 后完全沉默 5+ 分钟，无 `workflow.task_stalled` 事件
- **根因**：`check_stalled_tasks()` 只扫描 RUNNING 状态的 task（`engine.get_tasks_by_status("running")`）
- **改进方案**：增加 ASSIGNED 状态的超时检测（独立阈值，如 assigned_threshold=120s，区别于 running_threshold=300s）
- **验收标准**：ASSIGNED 超过阈值的 task 触发 stall 告警

---

### v17-v23 版本趋势

| 版本 | 日期 | 结果 | 过程 | 体验 | 综合 | 自动化率 | 关键修复 |
|------|------|------|------|------|------|----------|----------|
| v17 | 2026-05-02 | 2/5 | 2/5 | 3/5 | 2.3/5 | 20% | challenge mode 首次运行；verify gate cwd P0 bug |
| v18 | 2026-05-03 | 3/5 | 2/5 | 3/5 | 2.7/5 | 60% | +RO-41 cwd fix |
| v19 | 2026-05-03 | 3/5 | 3/5 | 3/5 | 3.0/5 | 88.9% | +RO-44 --force; depends_on 首次通过 |
| v20 | 2026-05-03 | 3/5 | 5/5 | 3/5 | 3.7/5 | 100% | +RO-42 证据注入; 过程首次满分; Codex 审查 4 CRITICAL |
| v21 | 2026-05-07 | 3/5 | 4/5 | 3.5/5 | 3.5/5 | 83.3% | +RO-45~50 代码修复; 0 CRITICAL; Gemini challenge 3x 失败 |
| v22 | 2026-05-07 | 2/5 | 3/5 | 3/5 | 2.7/5 | 33% | +RO-54 auto-dispatch ✅ +RO-48 stall ✅; Gemini 0% 可靠; auto-dispatch 异常路径断裂(RO-55) |
| v23 | 2026-05-11 | 3/5 | 3/5 | 3.5/5 | 3.2/5 | 100%分发/0%闭环 | +RO-47 ✅ +RO-55 ✅; DAG+auto-dispatch 稳定; digest guard 过严; shell 语义新 P0 |
| v24 | 2026-05-11 | 2/5 | 4.5/5 | 4/5 | 3.5/5 | 100%分发/67%自动 | +RO-61 structural digest ✅; verification 6/6 全部真正执行; 8min 历史最快; PATCH vs PUT 老 bug 重现 |

---

## v24 E2E 验证归档（2026-05-11）

### 已验证通过（迁入 full）

#### RO-61 plan_digest_divergence 分级 — ✅ v24 验证通过

> v24 验证：ledger 中无任何 `plan_digest_divergence` 事件。structural digest 区分生效——verification、goal_behavior、title 等 operational 字段变更不再触发 digest guard 阻塞。v23 的 20 次 divergence + 4 次 force-complete → v24 的 0 次。
> 实现：`plan_io.py:compute_structural_plan_digest()` 剥离 `_TASK_OPERATIONAL_KEYS`（verification, verification_mode, goal_behavior, acceptance_criteria, title）后计算 SHA256。`workflow_orchestrator.py` pre-transition hook 使用 structural digest 比较。
> 单测：`test_ralph_plan_digest_guard.py`（5 tests：verification_command_change_same_digest, title_change_same_digest, structural_change_different_digest, claimed_paths_change_different_digest, goal_behavior_change_same_digest）

### 代码已修复，v24 间接验证（保留在短版观察）

#### RO-60 verification 命令 shell 语义 — ⚠️ 代码修复已验证（单测），E2E 未直接触发

> v24 验证状态：代码修复已通过单测（`test_ralph_standalone.py` 4 tests：env_var_detected, env_var_multiple_detected, env_var_not_false_positive_on_equals_in_args, env_var_prefix_executes_via_shell）。但 v24 E2E 中 Foreman 未使用 `VAR=val cmd` 格式（全部用 `cd dir && cmd`），核心修复路径未被直接触发。
> 实现：`ralph_service.py:_has_shell_operators()` 增加 `_ENV_VAR_PREFIX_RE` 正则检测。

#### RO-62/63/64 — ⚠️ v24 中未触发对应场景

> v24 中无 force-complete 事件（RO-62）、无 ASSIGNED 状态 retry/fail（RO-63）、无 ASSIGNED stall（RO-64），因 workers 全部正常运行。这些代码修复待后续有触发场景时验证。

### v24 新发现

#### RO-65 challenge mode Gemini 不可达应 graceful degradation（P1）

> **来源**：2026-05-11 E2E v24 T2 首次 verification
- **严重度**：Medium — 导致 1 次 retry（本轮自愈，但非必然）
- **现象**：T2 worker checks（app-import + routes-registered）全部 passed，但 challenge mode 因 Gemini CLI ECONNRESET（`cloudcode-pa.googleapis.com`）直接报 failed
- **日志证据**：`workflow.verification_failed` 事件 06:39:31，T2 challenge 报 `Error authenticating: _GaxiosError: request to cloudcode-pa.googleapis.com/v1internal:loadCodeAssist failed`
- **根因**：`ralph_service.py` challenge 失败时仅当 payload 含 `degraded:true` 时走降级路径；Gemini CLI 网络错误不产生 `degraded` payload，直接返回 `failed`
- **Foreman 反馈**："The auto-upgrade should degrade gracefully — if the challenge agent is unavailable, the task should pass with a warning, not fail entirely"
- **改进方案**：Gemini CLI 网络错误（ECONNRESET/timeout/auth failure）时自动设置 `degraded=True`，走 `W_CHALLENGE_DEGRADED` warning 路径
- **验收标准**：Gemini 不可达时 challenge 降级为 worker-only + warning，不 fail task

#### RO-67 ralph validate 噪音过大（P2）

> **来源**：2026-05-11 E2E v24 Foreman 体验反馈
- **严重度**：Low — 不影响功能，影响 Foreman 体验
- **现象**：6 task plan 产出 15 warnings + 32 hints，信噪比过低
- **Foreman 反馈**："Signal-to-noise ratio needs improvement for small projects"
- **改进方案**：新增 `--compact` 模式只显示 actionable 项（errors + 高 confidence warnings）
- **验收标准**：`--compact` 模式输出 ≤10 项

---

### 结果分持续低迷根因分析——监察机制缺口

**现象**：24 轮 E2E 中，结果指标只有 v13 拿过 4/5，其余全在 2-3/5 徘徊。过程和体验已稳定提升，唯独结果分无法突破。问题不在产出物本身（Worker 的代码能力已到位），而在**监察机制未能在完成时拦截这些 bug**。

**CRITICAL bug 归类（按监察机制缺口分）**：

| 版本 | CRITICAL 类别 | 当前机制为何漏检 | 应由哪个机制拦截 |
|------|--------------|----------------|-----------------|
| v1/v24 | FK 未启用 | verification 只跑 happy-path 单测 | challenge agent：检查 SQLite 是否启用 PRAGMA foreign_keys |
| v14/v20/v24 | 前端 PATCH vs 后端 PUT | 各栈 verification 独立，不做跨栈接口检查 | challenge agent：对比 API client HTTP method 与 router decorator |
| v20/v24 | position 无边界校验 | 单测只覆盖正常值 | challenge agent：构造负数/超界反例 |
| v17 | verify gate cwd bug | 基础设施 bug | 已修复 |
| v22 | Gemini 输出 CRITICAL | Worker 不可靠 | 已通过 runtime 选择规避 |

**监察机制现状与缺口**：

```
verification checks（命令验证）
  ✅ 能力：运行 pytest/tsc/build，检查各组件独立可用
  ❌ 盲区：跨栈接口一致性、边界/防御性检查
  → 原因：checks 由 Foreman 在 plan.yaml 中手写，Foreman 倾向写 happy-path 检查

challenge agent（Gemini 对抗审查）
  ✅ 能力：读源码+diff，语义审查，理论上可检测跨文件不一致
  ❌ 盲区 1：仅对 critical_flow entrypoint 触发，前端 UI 组件不在其中
  ❌ 盲区 2：Gemini 不可靠（网络/auth），降级后变成空操作
  → 原因：触发范围过窄 + 降级策略不足

integration task verification（T6 级跨栈验证）
  ✅ 能力：覆盖多 task 的 covers_tasks/covers_flows
  ❌ 盲区：T6 的 verification checks 只跑 "pytest + npm build"，不含跨栈 HTTP 调用
  → 原因：能力指南和计划模板没有引导 Foreman 写跨栈集成检查
```

**核心结论**：过程机制（调度、分发、digest guard）已到 4.5/5，结果分的天花板完全在**验证深度**——"各组件独立正确"不等于"组合后正确"。现有三道防线（checks、challenge、integration）都没有覆盖"跨栈接口匹配"这个最高频的 CRITICAL 类别。

**监察机制增强方向**：

1. **challenge agent 触发范围扩展（P0 效果）**
   - 现状：仅 claimed_paths 命中 critical_flow.entrypoints 时触发
   - 方案：当 plan 同时包含前端 API client 文件（`*/api/*.ts`）和后端 router 文件（`*/routers/*.py`）时，对 integration task 强制触发 challenge，prompt 中注入"对比 API client 的 fetch method 与 router decorator，检查是否一致"
   - 验收：PATCH vs PUT 类 bug 被 challenge agent 拦截

2. **challenge agent 降级策略修复（RO-65，已记录）**
   - 现状：Gemini 网络错误 → task failed
   - 方案：降级为 worker-only passed + `W_CHALLENGE_DEGRADED`
   - 验收：Gemini 不可达不阻塞任务完成

3. **integration verification 模板引导（capability guide 层面）**
   - 现状：能力指南告诉 Foreman "每个 task 至少 compile + test 两步"
   - 方案：增加 "integration task 的 verification 必须包含至少一个跨栈调用检查"示例，如 `cd backend && python -c "from fastapi.testclient import TestClient; from app.main import app; c=TestClient(app); r=c.put('/api/tasks/1/move', json={...}); assert r.status_code != 405"`
   - 验收：T6 的 verification checks 能检测到前后端 HTTP method 不匹配

4. **Ralph validate 新规则（长期，静态分析方向）**
   - 方案：`W_CROSS_STACK_NO_INTEGRATION_CHECK` — 当 plan 同时有 `api/client.ts` 和 `routers/*.py` 在 claimed_paths 中，但 integration task 的 verification checks 不含跨栈命令时发出 warning
   - 验收：纯静态分析层面提醒 Foreman 补充跨栈检查

---

## v26 E2E 验证归档（2026-05-13）

> 综合 3.0/5（结果 2/5，过程 3/5，体验 4/5）
> 总耗时 ~19 分钟 / 3 tasks / Workers: Codex(3/3 100%) + Gemini(0/1 0%)
> 评估报告：[e2e-实战评估报告-v26.md](./e2e-实战评估报告-v26.md)

### 已验证通过（迁入 full）

#### RO-62 force-complete 产生 verification_passed 事件 — ✅ v26 验证通过

> v26 验证：T1 force-complete 产生 `workflow.verification_skipped` 事件（而非 `verification_passed`），事件 summary 为 `verification skipped: foreman force-complete override`。语义正确。
> 实现：`workflow_state_engine.py` force-complete 路径使用 `verification_skipped` 事件类型。
> 状态：从短版移除。

#### RO-69 verification 缺少跨栈集成 check — ✅ v26 验证通过

> v26 验证：验收标准明确要求 "Backend 必须配置 CORS（allow_origins 包含前端地址）" + "有集成验证（前后端联调 smoke test，包含 CORS 验证）"。T3 integration test 包含 CORS OPTIONS 预检验证，检查 `Access-Control-Allow-Origin` 头。Codex 对抗审查确认 CORS 配置 OK。
> v14/v22/v25 反复出现的 CORS 缺失问题在 v26 首次被双重拦截：验收标准 + 集成测试。
> 关键：这不是代码修复，而是**验收标准引导**生效——在任务描述中明确要求 CORS 配置和集成验证。
> 状态：从短版移除。

### 代码已修复，v26 间接验证（保留在短版观察）

#### RO-45/46/51 — ⚠️ v26 中 T1 force-complete 跳过 challenge，目录展开/git diff/scope 检查路径未被触发

> 连续 6 轮（v21-v26）未被直接触发。代码修复存在但缺少 E2E 覆盖。

#### RO-60 verification 命令 shell 语义 — ⚠️ Foreman 未使用 `VAR=val` 格式

> v26 Foreman 全部使用 `cd dir && cmd` 格式，`VAR=val` 修复路径连续 3 轮（v24-v26）未被触发。

### v26 新发现

#### RO-70 verification 命令被 runtime 变形（P1，v26 发现）

> **来源**：2026-05-13 E2E v26 T1 verification_failed
- **严重度**：Medium — 导致 1 次 false negative + force-complete，自动闭环率降至 66.7%
- **现象**：plan.yaml 中 import-check 命令为 `cd backend && python -c 'from main import app'`，但 Codex worker 创建了 package-style import（`from backend.api import ...`），verification 执行 plan 中命令失败
- **日志证据**：`06:30:41 workflow.verification_failed` T1 `import-check exited with 1 (expected 0)`
- **根因**：plan.yaml 的 verification 命令假设特定 import 风格，但 worker 可能用不同代码组织方式。plan 阶段无法预知 worker 实现细节
- **Foreman 反馈**："The foreman doesn't know what import style the worker will use — verification commands should be more resilient"
- **改进方案**：能力指南建议使用 resilient 验证命令（如仅检查 `pytest` 通过，或使用 `importlib.import_module()`）
- **验收标准**：下一轮 verification 命令不因 import 风格差异而失败

#### RO-71 completer_mismatch 应更严格处理（P2，v26 发现）

> **来源**：2026-05-13 E2E v26 T1 force-complete
- **严重度**：Low — 功能不受影响但审计链断裂
- **现象**：T1 由 planner 执行 `task complete`（而非 assigned worker-be），产生 `completer_mismatch` 警告但 verification_skipped
- **日志证据**：`06:31:40 workflow.verification_warning` T1 `completer_mismatch: completed by planner, assigned to worker-be`
- **根因**：force-complete 允许任何 actor 完成 task，且跳过 verification
- **改进方案**：completer_mismatch 时 verification 应升级为 mandatory（不允许 skip）
- **验收标准**：completer_mismatch + verification_skipped 不同时出现

#### RO-72 retry 后 worker 类型错配 — ✅ v27 E2E 验证通过

> **来源**：2026-05-13 E2E v26 T2 Gemini stall → retry
- **严重度**：Low — 功能上 Codex 完成了 frontend task，但分配语义不精确
- **现象**：T2 (frontend) Gemini stall 后 retry 分配给 worker-be (Codex/backend worker)
- **v27 验证**：T2 (frontend) Codex stall 后 Foreman 自主创建 worker-fe2 (claude)，task type=frontend 与 worker 类型匹配。非代码修复，而是 Foreman 行为改善（Gemini 排除后 Foreman 不再复用 backend worker，而是创建新的类型匹配 worker）

---

## v27 E2E 验证归档（2026-05-13）

> 综合 3.3/5（结果 2/5，过程 4/5，体验 4/5）
> 总耗时 ~19 分钟 / 3 tasks / Workers: claude(3/3 100%) + codex(0/1 0% stall)
> 变更点：Gemini 从 worker 分配中移除（agent_pool.py + 能力指南），仅保留 Ralph challenge agent
> 评估报告：[e2e-实战评估报告-v27.md](./e2e-实战评估报告-v27.md)

### 已验证通过（迁入 full）

#### RO-72 retry 后 worker 类型错配 — ✅ v27 验证通过

> v27 验证：T2 (frontend) Codex stall 后 Foreman 创建 worker-fe2 (claude)，类型匹配。v26 中 frontend task 被分配给 backend worker 的问题未重现。

### 代码已修复，v27 间接验证

#### RO-70 verification 命令变形 — ⚠️ v27 未重现

> v27 T1 verification 9 checks 全部 passed（含 challenge mode）。Foreman 写了更 resilient 的 verification 命令。但不确定是否稳定修复——可能是 Foreman 行为偶发改善而非系统性修复。

#### RO-71 completer_mismatch — ⚠️ v27 未触发

> v27 零 force-complete，零 completer_mismatch。验证场景未被触发。

### v27 新发现

#### RO-73 Codex 前端任务 stall（P1，v27 发现）

> **来源**：2026-05-13 E2E v27 T2 worker-fe (codex)
- **严重度**：Medium — 导致 12 min 浪费 + 1 次手工 retry
- **现象**：Codex worker scaffold 了 Vite 项目并安装了 @hello-pangea/dnd，但从未写入 kanban 组件代码。有 heartbeat 但 12+ 分钟无文件修改
- **日志证据**：`08:20:33 workflow.task_failed` T2 "Codex worker active with heartbeats but no file modifications after 12 minutes"
- **根因**：Codex runtime 对复杂前端组件生成能力不足或卡在内部推理
- **Foreman 反馈**："Codex scaffolded project but never wrote components; no visibility into what worker is doing"
- **改进方案**：(A) 能力指南推荐前端任务使用 claude runtime；(B) stall detection 增加"有 heartbeat 但无文件写入超 5 min"检测
- **验收标准**：前端任务不因 Codex stall 需要手工 retry

---

## v28 E2E 验证归档（2026-05-13）

> 综合 4.2/5（结果 3/5，过程 5/5，体验 4.5/5）——**历史最高**
> 总耗时 ~8 分钟 / 504s engine time / 3 tasks / Workers: codex(2/2 100%) + claude(1/1 100%)
> 评估报告：[e2e-实战评估报告-v28.md](./e2e-实战评估报告-v28.md)

### 已验证通过（迁入 full）

#### RO-51 scope 目录匹配 — ✅ v28 验证通过
> Worker scope 正确限定在项目目录内，未出现 scope 误报。

#### RO-52 Gemini JSON 解析 — ✅ v28 验证通过（间接）
> v28 未使用 Gemini worker，Gemini 仅用于 Ralph challenge agent，JSON 解析正常。

#### RO-70 prompt 引导零命令变形 — ✅ v28 验证通过
> 3/3 任务 verification checks 全部正确执行，零命令变形。

#### RO-73 claude runtime 零 stall — ✅ v28 验证通过
> worker-fe (claude) 完成 T3 (frontend)，零 stall，100% 可靠。

### v28 新发现

#### RO-74 Worker prompt 首尾重复 cccc task complete（P2）
> Worker prompt 中 completion reminder 出现在 top 和 bottom 两处，Foreman 观察到冗余提醒消息。
> **v30 修复**：确认 top+bottom 两处是设计意图（确保 Worker 不遗漏），非 bug。

#### RO-75 workflow 全部完成后自动转终态（P1）
> v28 workflow 完成后需人工确认。
> **v30 修复**：workflow_state_engine 在所有任务进入终态后自动转 completed。

---

## v30 代码修复归档（2026-05-13）

> 修复条目：RO-74/75/76、RL-21、BP-1/BP-3
> 验证：全量 pytest 2616 passed / 0 failed / 120 skipped
> E2E v29 实战验证：全部通过

### RO-74 prompt 首尾重复 cccc task complete — ✅ 确认设计意图
> top（mandatory）+ bottom（reminder）两处 completion 提醒是刻意设计，确保 Worker 不遗漏。非 bug。

### RO-75 workflow 自动转终态 — ✅ v29 E2E 部分验证
> workflow_state_engine 在所有任务终态后自动转 `kind=completed`。
> **v29 新发现**：状态机生效但 ledger 缺少 `workflow.completed` 事件 → RO-77。

### RO-76 validate 错误附带字段建议+示例+--show-schema — ✅ v29 E2E 验证
> Foreman 确认 validate 报告了 covers_flows 无效字段、mock_tests.input 格式要求等。

### RL-21 W_SHARED_PATH_NO_DEPENDENCY — ✅ 代码已实现，v29 未触发
> `_check_implicit_serialization` 升级为 `W_SHARED_PATH_NO_DEPENDENCY`（warning 级别），消息包含冲突路径和建议。v29 plan 无路径冲突，未触发。

### BP-1 mock_tests 集成 agent 验证 — ✅ v29 E2E 首次实战拦截
> mock_tests 在 T1 verification 中成功拦截问题（mock_test_2 的 verify_command 有 Python 逻辑错误），verification_failed → 修复 → 第二次 pass。**首次在真实 E2E 中证明对抗性验证价值。**

### BP-3 expected_input/output 渲染到 worker prompt — ✅ v29 E2E 验证
> Foreman 确认 "expected_input/expected_output contracts were rendered into worker prompts, helping workers understand interfaces"。

---

## v29 E2E 验证归档（2026-05-13）

> 综合 3.3/5（结果 2/5，过程 4/5，体验 4/5）
> 总耗时 ~30 分钟（含 codex stall 重试）/ 167s engine time / 8 tasks
> Workers: claude(8/8 100%) + codex(0/5 0% stall)
> 评估报告：[e2e-实战评估报告-v29.md](./e2e-实战评估报告-v29.md)

### v30 新能力验证结果

| 能力 | 验证结果 |
|------|---------|
| BP-1 mock_tests | ✅ 首次实战拦截（T1 verification_failed → fix → pass）|
| BP-3 expected_input/output | ✅ 渲染到 worker prompt 确认 |
| RO-75 auto-terminal | ⚠️ 状态机生效（status=completed），缺 ledger 事件 → RO-77 |
| RO-76 validate 报错质量 | ✅ Foreman 确认 |
| RL-21 shared path warning | 未触发（plan 无冲突路径）|

### v29 新发现

#### RO-77 workflow 自动终态缺少 ledger 事件（P1）

> **来源**：2026-05-13 E2E v29 Codex 过程审查
- **严重度**：Medium — 状态机生效但日志审计无法确认
- **现象**：`cccc workflow status` 返回 `kind=completed`，但 ledger 161 条事件中无 `workflow.completed` 事件
- **根因**：workflow_state_engine 转终态时更新内部状态但未发射 ledger 事件
- **改进方案**：转终态时发射 `workflow.completed` / `workflow.failed` 事件
- **验收标准**：下一轮实战中 ledger 包含 `workflow.completed` 事件

#### RO-78 Foreman retry 创建新 workflow_id（P2）

> **来源**：2026-05-13 E2E v29 T8 retry
- **严重度**：Low — 需用户一次手工指导恢复
- **现象**：Foreman 用 `kanban-v1-fix` 新 workflow_id 重新注册 T8，触发 `E_INTERNAL_REGISTER: workflow_id mismatch for task T1`
- **根因**：Foreman 对 retry CLI 语义理解不准确
- **改进方案**：能力指南明确 retry 语义；或 engine 对已有 workflow 的 resubmit 自动归并
- **验收标准**：Foreman retry 不创建新 workflow_id

#### RO-79 mock_test verify_command Python 错误无法 validate 检测（P2）

> **来源**：2026-05-13 E2E v29 T1 mock_test_2
- **严重度**：Low — validate 通过但 verification 时失败，需一次 retry
- **现象**：mock_test_2 verify_command 含 `python -c 'if False ...'` 逻辑错误，validate 通过但 verification 失败
- **根因**：ralph validate 不解析 verify_command 中的 Python 代码
- **改进方案**：对 `python -c` 类 verify_command 做 `compile()` 语法检查
- **验收标准**：Python 语法错误的 verify_command 在 validate 阶段报 warning

---

## v31 代码修复归档（2026-05-14）

> 修复条目：RO-77/78/79、BP-2/BP-4/BP-5
> 验证：全量 pytest 2628 passed / 0 failed / 120 skipped
> E2E v32 实战验证：RO-77 ✅ / RO-78 ✅ / BP-2 ✅ / BP-4 ✅ / RO-79 未触发 / BP-5 未使用

### RO-77 workflow 终态 ledger 事件 — ✅ v32 E2E 验证通过
> complete_workflow 在 cleanup 前 emit `workflow.completed` / `workflow.failed` 事件。
> v32 E2E 18:37:03 ledger 包含 `workflow.completed` 事件，data 显示 `completed_count=4, failed_count=0`。

### RO-78 retry workflow_id 解析 — ✅ v32 E2E 验证通过
> register_and_suggest_inner 调用 resolve_workflow_id_for_tasks，retry 不再 mismatch。
> v32 E2E 零 retry/error 事件，无 workflow_id_mismatch。

### RO-79 python -c 语法检查接入 validate — ⚠️ 代码已实现，v32 未触发
> check_verification_command_syntax 接入 validate。v32 plan 中 verify_command 无 python -c 语法错误，未直接触发。

### BP-2 ModuleSpec 模型 + prompt 渲染 + 验证规则 — ✅ v32 E2E 验证通过
> ModuleSpec Pydantic 模型、TaskRef 传递、prompt_builder 渲染、_check_module_consistency 验证规则。
> v32 plan.yaml 使用 module_spec，元数据在 task_registered 事件中正确传递。

### BP-4 provides/consumes 静态验证 + 运行时 contract check — ✅ v32 E2E 验证通过
> _check_cross_task_io_contracts 静态验证 + _check_output_contract 运行时 check。
> v32 plan_validated 事件含契约验证。provides/consumes 从 plan.yaml 正确传递到 task_registered 事件。

### BP-5 batch_e2e_command/timeout + verify_batch_e2e() — ⚠️ 代码已实现，v32 未使用
> batch_e2e_command/timeout Plan 字段 + verify_batch_e2e() + batch completion 触发（非阻塞线程）+ W_BATCH_E2E_NO_COMMAND 验证规则。
> v32 Foreman 未设置 batch_e2e_command 字段，W_BATCH_E2E_NO_COMMAND warning 已输出但 Foreman 未响应。

---

## v32 E2E 验证归档（2026-05-14）

> **综合 4.3/5（历史新高）**（结果 4/5，过程 5/5，体验 4/5）
> 总耗时 ~13 分钟 / 4 tasks / DAG: T1→(T2||T3)→T4
> Workers: codex(3/3 100%) + claude(1/1 100%) = 4/4 100%
> 评估报告：[e2e-实战评估报告-v32.md](./e2e-实战评估报告-v32.md)

### v31 修复验证结果

| 能力 | 验证结果 |
|------|---------|
| RO-77 workflow.completed 事件 | ✅ 18:37:03 事件确认，data 含 completed_count/failed_count |
| RO-78 retry workflow_id | ✅ 零 retry/error 事件 |
| RO-79 python -c 语法检查 | 未触发（本轮无语法错误） |
| BP-2 ModuleSpec | ✅ plan.yaml module_spec 正确传递到 task_registered |
| BP-4 provides/consumes | ✅ plan_validated 含契约验证，task_registered 含 provides/consumes |
| BP-5 batch_e2e_command | 未使用（Foreman 未设置） |

### v32 Codex 审查结果

| 维度 | 审查者 | 结果 |
|------|--------|------|
| 结果指标 | Codex 对抗式代码审查 | 0 CRITICAL, 8 WARN, 21 OK → 4/5 |
| 过程指标 | Codex 工作流日志分析 | 10/10 必检项 positive + 3 额外检查通过 → 5/5 |
| 体验指标 | Foreman WORKFLOW_EVALUATION.md | 自评 4.2/5, 零手工干预执行阶段 → 4/5 |

### v32 关键亮点
- **过程指标连续两轮满分**（v28+v32）
- **结果指标首次达到 4/5**（0 CRITICAL 实现 bug）
- **100% 自动化率**（auto-dispatch + DAG gating + verification 全自动）
- **零 stall/failure/retry**
- **瓶颈转移**：从"机制是否工作"→"plan 编写体验优化"

### v32 新发现

#### UX-1 provides/consumes 格式文档与 schema 不一致（P2）

> **来源**：2026-05-14 E2E v32 Foreman 反馈
- **严重度**：Low — 增加 validate 迭代次数（5 次 vs 预期 2-3 次）
- **现象**：Foreman 用字符串格式声明 provides（`provides: "backend_api"`），被 validate 拒绝，需改为 `{name: "backend_api", kind: "api"}` 对象格式。capability guide 示例用 `mode` 但 schema 要求 `level`
- **根因**：foreman-capability-guide.md 中 provides/consumes 示例不够精确
- **改进方案**：在 foreman-capability-guide.md 增加完整 provides/consumes 示例（含 from_task 字段），与 `ralph validate --show-schema` 输出一致
- **验收标准**：下一轮实战中 Foreman validate 迭代 ≤3 次

#### UX-2 Greenfield 项目 W_VERIFICATION_SHAPE_UNKNOWN 大量重复（P2）

> **来源**：2026-05-14 E2E v32 Foreman 反馈
- **严重度**：Low — 噪音影响 Foreman 判断
- **现象**：4 任务 plan 产生 17 warnings + 20 hints，W_VERIFICATION_SHAPE_UNKNOWN ×12 占主要噪音
- **根因**：验证规则不区分 greenfield 项目和已有项目
- **改进方案**：`--compact` 模式或 warning 分级（actionable vs informational）
- **验收标准**：同类 4 任务 plan 验证输出 ≤10 条 warning/hint

#### UX-3 E_VERIFICATION_TARGET_MISSING_FILE 在 greenfield 应为 warning（P2） — ✅ 已由现有代码处理（v33 Codex 审查确认）

> **来源**：2026-05-14 E2E v32 Foreman 反馈
- **严重度**：Low — 需 suppress_codes workaround
- **现象**：T4 integration task 的 verification 目标文件由上游 task 创建，但 validate 阶段该文件不存在，报 E_VERIFICATION_TARGET_MISSING_FILE（error 级别）
- **根因**：validate 在执行前运行，无法预知上游 task 将创建哪些文件
- **改进方案**：当 verification target 所在路径被上游 task 的 claimed_paths 覆盖时，降级为 warning
- **验收标准**：上游 task claim 的路径中的 verification target 不再报 error
- **v33 处置**：Codex 审查发现现有代码已处理此场景。`_check_path_target()` 的 `upstream_projected` 参数通过 `workspace.projected_paths(plan, task.id, include_self=False)` 构建，包含所有上游 task 的 claimed_paths。当 `covered_by_upstream=True` 时已降级为 hint 而非 error。v32 实际触发可能是因为文件名 stem 不匹配（如 "test_integration" vs "api"），属于计划编写问题而非 validator bug。标记为已处理，无需代码修改。

---

## v33 E2E 验证归档（2026-05-15）

> 综合 4.0/5（结果 3/5，过程 5/5，体验 4/5）
> 总耗时 ~9 分钟 / 4 tasks / Workers: Codex(4/4 100%)
> 评估报告：[e2e-实战评估报告-v33.md](./e2e-实战评估报告-v33.md)
> 新发现：RO-82（metadata 透传）、UX-7（validate 噪音降级）、UX-8（冲突提示）、FL-1/2/3（flow 自动化）——详见短版问题清单

## v34 代码修复归档（2026-05-15）

> 修复项：RO-82、UX-7、UX-8、FL-1、FL-3
> 确认已修复：RO-80/RO-81/UX-2（详见下方确认记录）
> 新增 RL：RL-23/24/25（goal_behavior 语义验证缺口，Codex 审查暴露）
> 全量 pytest：2694 passed / 0 failed / 120 skipped（并行 108s）
>
> v34 E2E 实测修复（基础设施）：
> - `_reject_incomplete_tasks()` in `assignment_batches.py` — 引擎层拦截缺少 claimed_paths/verification 的 task（两条路径：register_and_suggest_inner + _register_batch_inputs）
> - E2E flow step-2 模板 — 嵌入完整工作流强制要求（plan.yaml + ralph validate + claimed_paths + verification.checks）于 `flow_steps_e2e.py`
> - 移除 step-0 pytest 门禁 — `_check_code_verify()` 直接返回 pass
> - 根因追踪：`_workflow_guidance_excerpt()` 只提取 1 个 fragment，foreman prompt 丢失关键工作流指导 → UX-9
>
> v34 E2E 评分：综合 3.7/5（结果 3/5，过程 4/5，体验 4/5）
> - 4 任务拆分（setup→models→api→tests），verification 真实执行
> - 1 CRITICAL（XSS routes.py:73），与 v33 同类
> - 新发现：RO-83（verify gate 安全检查）/RO-84（validate ledger 事件）/UX-9（prompt 裁剪过度）

### ~~RO-80 challenge/agent 验证不可用时降级为通过~~ — ✅ v34 计划分析确认已修复

> `_failed_agent_verification()` 已返回 `"failed"`（ralph_service.py:1170）。challenge 模式下 `_verify_completion_with_challenge()` 也返回 `"failed"`（line 833）。有 `test_challenge_infrastructure_failure_is_fail_closed` 测试覆盖。

---

### ~~RO-81 _check_cross_task_io_contracts 多上游场景误报~~ — ✅ v34 计划分析确认已修复

> `_check_cross_task_io_contracts()` 的 `upstream_keys.update(dep.expected_output.keys())` 已实现 N:1 union 聚合（contracts.py:317）。多个上游的 keys 被合并后再与 expected_input 比较。

---

### ~~UX-2 Greenfield 项目 W_VERIFICATION_SHAPE_UNKNOWN 大量重复~~ — ✅ v34 计划分析确认已修复

> `_group_repeated_issues()` 已实现 threshold=3 的分组逻辑（cli.py），10 个重复 hint 合并为 1 行 `(x10)` 输出。有 `test_repeated_hints_grouped_in_output` 测试覆盖（test_ralph_standalone.py:530）。

---

### FL-4 flow step-7 guide 生成覆盖运行时章节（v34 修复过程中发现并修复）

- **现象**：`ralph guide --output` 只生成 schema/rules/CLI 三个 section，覆盖掉了旧版手写的运行时行为章节（Verification Modes、DAG Gating、Stall Detection、Auto-Dispatch、Monitor Invariants、Ledger Events），导致指南从 386 行缩水到 230 行
- **根因**：`generate_guide()` 只有 3 个 auto-generator，不覆盖运行时行为
- **修复**：flow step-7 改为自动调用 `update_guide()`（增量更新），只重新生成有 auto-generator 的 section。运行时章节被代码变更影响时 step 失败并报 warning，强制手动更新
- **验收**：step-7 自动生成 + 运行时章节有代码变更时阻断

### FL-5 flow step-6 verify 未检查 pytest 并行执行（v34 修复过程中发现并修复）

- **现象**：flow test-cmd 使用 `pytest -o addopts=` 清除了 `-n auto`，导致 2778 个测试串行执行（390s vs 并行 110s）
- **根因**：flow 启动时传入 `-o addopts=` 是为了规避 xdist 未安装的问题，但 xdist 已装好后未更新
- **修复**：`_check_verify()` 新增并行检查——pytest 输出中必须包含 xdist worker 标志（`workers`/`gw`），否则 step 失败并提示安装 pytest-xdist
- **验收**：非并行执行直接报错

---

## v36 代码修复归档（2026-05-16）— 14 项批量修复

> 全量 pytest 2696 passed / 0 failed / 120 skipped
> 修复范围：v33/v34/v35 发现的 P1/P2 问题

### 已验证修复条目

| ID | 标题 | 修复内容 |
|----|------|----------|
| RO-82 | failure_path/awareness_paths 未透传 | workflow submit 序列化逻辑补全字段透传 |
| RO-83 | aegis/challenge/mock_tests 不可见 | capability guide + template 补全文档 + 示例 |
| RO-85 | force_complete 无 ledger 事件 | KIND_FORCE_COMPLETED ledger 事件实现 |
| RO-86 | 编排层 verification_passed 语义矛盾 | notification_outcome 区分 force_passed |
| UX-1 | provides/consumes 格式文档不一致 | foreman-capability-guide.md 补全示例 |
| UX-4 | plan.yaml 模板不全 | plans/_template.yaml 全字段 + 注释 |
| UX-7 | 串行链 W_FLOW_OWNER_NO_VERIFICATION 噪音 | covers.tasks 包含时降级为 hint |
| UX-9 | workflow_guidance 未注入 foreman prompt | wanted_fragments 扩展到 8 行关键指导 |
| AD-5 | prompt_builder 无 aegis intent 注入 | _aegis_sections_for_task() 按 intent 注��� |
| AD-6 | Foreman system prompt 无 Aegis 感知 | system_prompt.py 加 Plan Discipline 段 |
| FL-1 | e2e step-1 不自动准备环境 | auto mkdir + git init + docs copy |
| FL-3 | step-6 不区分短版/full 写入 | 检查两个 tracker 都有变更 |
| RL-23 | goal_behavior 算法逻辑错误不可检测 | agent rule 8 实现 |
| RL-24 | goal_behavior 与运行时行为矛盾不可检测 | agent rule 9 实现 |

---

## v35 E2E 归档（2026-05-15）— Codex foreman 首测

> Foreman：Codex runtime（首次）| Worker：Claude runtime
> 综合评分：2.3/5（结果 2/5，过程 2/5，体验 3/5）
> 4 任务拆分（T1→T2→T3→T4），claimed_paths 精确到文件，verification 已配置但全部被 force-complete 跳过
>
> 关键发现：
> - Codex foreman 使用 force_complete_unverified() 跳过 4/4 verification
> - 编排层报 verification_passed，引擎层实际是 verification_skipped + force_passed（语义矛盾）
> - 14 次 plan_digest_divergence（注册后继续修改 plan.yaml）
> - 2 次 ralph_internal_error（TasksAlreadyExistError）
> - 3 CRITICAL XSS（rendering.py:10/18/22），比 v34 多 2 个（title 注入 + 链式 XSS）
> - Foreman 自评 7/10，手工验证磁盘文件 + 补写测试
>
> 新发现：RO-85（force-complete ledger 事件）/RO-86（编排层 outcome 语义）/RO-87（plan 漂移锁定）
> 结论：Codex 作为 foreman 当前不可靠，建议继续用 Claude 作为 foreman

## v35b E2E 归档（2026-05-16）— Claude foreman 复测

> Foreman：Claude runtime | Worker：Claude runtime（worker-1）
> 综合评分：3.3/5（结果 3/5，过程 3/5，体验 4/5）
> 3 任务串行（db-layer → routes-and-templates → integration-tests）
> 项目：Flask 留言板（SQLite FTS5 + XSS 防护 + 输入校验 + 分页）
>
> 关键发现：
> - db-layer 一次通过验证，routes-and-templates 因 GNU timeout exit 127 失败
> - workflow recovery 不可用（deferred 状态无法 retry/re-verify），手动绕过
> - integration-tests 无正式 workflow 事件链（chat 下发）
> - 代码质量高：Jinja2 autoescaping, 参数绑定, FTS5 触发器
> - 安全缺口：FTS5 NUL/control → 500, debug=True 写死, 测试缺异常输入
> - claimed_paths 不完整（routes 实际写 app.py 但未声明）
> - Foreman 自评 8/10 偏高，Codex review 给 3/5
> - 31/31 pytest 通过，wall time ~5min，零手工干预
>
> 新发现：RO-89（FTS5 malformed 500）/RO-90（debug=True 检测）/UX-11（deferred retry）/RO-91（claimed_paths 推断）
> 结论：Claude foreman 流程正确性高于 Codex foreman，但 verify gate 深度不足（连续 v33/v34/v35b 问题）
