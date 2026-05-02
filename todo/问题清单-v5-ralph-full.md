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

### v17-v19 版本趋势

| 版本 | 日期 | 结果 | 过程 | 体验 | 综合 | 自动化率 | 关键修复 |
|------|------|------|------|------|------|----------|----------|
| v17 | 2026-05-02 | 2/5 | 2/5 | 3/5 | 2.3/5 | 20% | challenge mode 首次运行；verify gate cwd P0 bug |
| v18 | 2026-05-03 | 3/5 | 2/5 | 3/5 | 2.7/5 | 60% | +RO-41 cwd fix |
| v19 | 2026-05-03 | 3/5 | 3/5 | 3/5 | 3.0/5 | 88.9% | +RO-44 --force; depends_on 首次通过 |
