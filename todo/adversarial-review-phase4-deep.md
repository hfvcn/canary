# Phase 4 Deep Integration 审查报告

## 结论摘要

Phase 4 当前交付质量的核心问题不是“语义能力实现得不够”，而是“语义能力没有进入生产主路径”。我确认了你列出的 `RARCH-1`、`RARCH-2`、`RAUTO-1`，并且发现了更深一层的结构性断点：

- daemon 调度与验证都停留在 `TaskRef`/`RalphService` 侧，而 Phase 4 语义能力都长在 `Plan`/`TaskSpec`/`ralph.core` 侧。
- `workflow submit --plan` 在进入 daemon 前就把 `semantic` / `semantic_mode` / `auto_infer` 等信息降级丢失了，所以仅把 `RalphService.suggest_ready_batch()` 包一层委托并不能让生产链路“自动获得” Phase 4。
- 测试体系大量覆盖纯函数、CLI help、monkeypatch 后的 orchestrator 调用，但几乎没有覆盖 `plan -> daemon -> orchestrator -> resuggest/verify -> metrics` 的真实集成路径，因此出现了“测试绿、生产死”的假阳性。

## 已确认问题

### CRITICAL 1. `RalphService` 与 `ralph.core` 调度分裂，生产不会执行 Phase 4 调度语义

- 破坏点：
  daemon 生产调度仍走 `RalphService.suggest_ready_batch()`，只看 `depends_on + claimed_paths`；Phase 4 的 `semantic_gate`、`compute_semantic_weight()`、`_detect_semantic_conflicts()` 只存在于 `ralph.core.suggest()`。
- 证据：
  `src/cccc/daemon/foreman/ralph_service.py:184-229` 只做依赖和写集 gating。
  `src/cccc/ralph/core.py:293-371` 才有 `semantic_gate`、`semantic_conflicts`、`blocked_by_semantic`、语义排序。
  `src/cccc/daemon/foreman/workflow_orchestrator.py:431-449` 与 `1251-1302` 注册和 resuggest 都调用 `self.ralph.suggest_ready_batch(...)`。
- 影响：
  `--semantic-gate hard`、语义冲突阻塞、语义排序提升都不会进入 daemon 实际调度。
- 建议修复：
  将 daemon 调度统一到 `ralph.core.suggest()`，但前提不是“直接把 TaskRef 列表传过去”，而是先恢复完整 `Plan` 语义输入和运行态 `Plan.state`。

### CRITICAL 2. `workflow submit --plan` 在 IPC 边界丢弃语义数据，现有委托修复方向单独做不通

- 破坏点：
  即使把 `RalphService.suggest_ready_batch()` 改成委托 `core.suggest()`，daemon 当前也拿不到 `semantic`、`semantic_mode`、`auto_infer`。
- 证据：
  `src/cccc/ralph/models.py:127-128` 中 `TaskSpec` 持有 `semantic`。
  `src/cccc/ralph/models.py:276-277` 中 `Plan` 持有 `semantic_mode` 和 `auto_infer`。
  `src/cccc/contracts/v1/ralph_ipc.py:74-100` 的 `TaskRef` 没有任何 `semantic` / `auto_infer` 字段。
  `src/cccc/ralph/models.py:137-157` 的 `TaskSpec.to_task_ref()` 只保留验证/契约等字段，没有传输 `semantic`。
  `src/cccc/cli/workflow_cmds.py:86-97` 的 `_load_tasks_from_plan()` 先把 plan 降级成 `TaskRef`。
  `src/cccc/daemon/foreman/workflow_orchestrator.py:437-445` 收到后再次 `TaskRef.model_validate(...)`。
- 影响：
  这是比 `RARCH-1` 更深的输入层断裂。当前 daemon 根本没有 Phase 4 需要的数据形态。
- 建议修复：
  两种路线二选一：
  1. `plan` 提交路径改为 daemon 持有 `plan_path` 并在调度/验证时重新 `load_plan()`，把 engine 状态回填到 `plan.state` 后调用 core。
  2. 扩展 `TaskRef` / IPC 协议，把 `semantic`、`semantic_mode`、`auto_infer` 显式带过来。
  对于 `--tasks` 裸 JSON 提交，应明确标记“无完整语义上下文，不启用 Phase 4 语义自动化”。

### CRITICAL 3. 验证链路也存在同样分裂，`T6 consistency` 与 `T5 smart-tests` 在生产中同样不可达

- 破坏点：
  daemon 验证不是走 `ralph.core.verify()`，而是走 `RalphService.verify_completion()`；因此 `verify_post_change_consistency()`、`recommend_tests()` 只在 CLI 路径生效。
- 证据：
  `src/cccc/daemon/foreman/workflow_orchestrator.py:1782-1788` 生产完成事件调用 `self.ralph.verify_completion(...)`。
  `src/cccc/daemon/ralph_ipc_handler.py:1016-1043` `ralph_task_verify` 也调用 `orchestrator.ralph.verify_completion(...)`。
  `src/cccc/ralph/core.py:440-555` 才有一致性报告挂接逻辑。
  `src/cccc/ralph/cli.py:277-299` CLI `verify` 才会返回 `consistency_report` / `recommended_tests`。
  `src/cccc/daemon` 与 `src/cccc/kernel` 内搜索不到 `SemanticProvider` / `SerenaAdapter` / `_create_semantic_provider` 调用。
- 影响：
  `--consistency-check`、测试建议、语义后验校验全部是 CLI-only，daemon 验证永远不会产出这些数据。
- 建议修复：
  验证链路与调度链路一起统一：daemon 在 plan-backed workflow 上解析完整 `TaskSpec` + `SemanticProvider`，统一走 `core.verify()`。

### HIGH 4. 指标回流不仅“没接调用”，而且默认路径还是进程级相对路径，CLI/daemon/test 结果可能各看各的文件

- 破坏点：
  `record_semantic_outcome()` 在生产代码里没有调用；同时默认指标路径是 `Path(".ralph/semantic_metrics.jsonl")`，依赖当前进程工作目录。
- 证据：
  `src/cccc/ralph/semantic_metrics.py:11` 默认路径是相对路径。
  `src/cccc/ralph/semantic_metrics.py:98-120` 定义了写入函数。
  全局检索 `src/cccc`，除了定义和测试，没有任何生产调用 `record_semantic_outcome(...)`。
  `tests/test_ralph_semantic.py:1005-1066` 等测试通过 `monkeypatch.chdir(tmp_path)` 或手写 metrics 文件驱动 gate；这掩盖了真实 daemon 运行目录不稳定的问题。
- 影响：
  即使后续接入自动标注，如果 CLI、daemon、测试跑在不同 cwd，gate 仍会读取不同 metrics 文件，表现不稳定且难以审计。
- 建议修复：
  指标路径必须显式锚定到 `project_root` 或 `plan_path.parent / .ralph`，不要依赖进程 cwd。
  `record_semantic_outcome()` 的调用也必须通过统一的 runtime label sink 完成。

### HIGH 5. Phase 4 计划本身把“集成”定义成 CLI 集成，生产 daemon 根本不在 T8/T9 交付边界内

- 破坏点：
  `phase4-deep-integration.yaml` 的 T8 集成任务只覆盖 `validator.py` 和 `cli.py`；daemon/orchestrator/IPC/TaskRef/submit path 都不在 claimed paths 里。
- 证据：
  `plans/phase4-deep-integration.yaml:596-658` 的 T8 claimed paths 只有 `src/cccc/ralph/validator.py` 与 `src/cccc/ralph/cli.py`，goal/acceptance 也全部是 CLI flag 与 `gate-report`。
  `plans/phase4-deep-integration.yaml:668-690` 的 T9 测试只要求补 `tests/test_ralph_semantic.py`，没有 daemon/e2e 路径。
- 影响：
  当前结果并不只是“实现没接好”，而是计划边界从一开始就没有覆盖生产主路径。
- 建议修复：
  新 remediation plan 必须把以下文件纳入交付边界：
  `workflow_cmds.py`、`ralph_ipc.py`、`ralph_ipc_handler.py`、`workflow_orchestrator.py`、`ralph_service.py`、worker prompt 构建链路，以及对应 e2e 测试。

### HIGH 6. Prompt 自动化缺口比“prompt 没提 flag”更严重：worker prompt 根本拿不到 Phase 4 语义上下文

- 破坏点：
  worker prompt 只消费 `TaskRef` 的 `goal_behavior`、`acceptance_criteria`、`claimed_paths`、`verification.command`，没有任何语义上下文载荷。
- 证据：
  `src/cccc/daemon/foreman/workflow_orchestrator.py:992-1016` 任务提示仅拼接 Goal、Acceptance Criteria、Scope、Verification Command。
  `src/cccc/ralph/semantic_validator.py:1131-1170` 的 `format_semantic_context()` 只被 CLI `semantic-context` 调用。
  `src/cccc/contracts/v1/ralph_ipc.py:74-100` 的 `TaskRef` 不含 semantic data。
- 影响：
  即便调度统一后，agent 也不会自动看到目标 symbol、风险、推荐测试、语义冲突背景。
- 建议修复：
  prompt 注入也必须走 plan-backed full task context，而不是指望 agent 手工触发 CLI 子命令。

### MEDIUM 7. `ValidationReport.consistency_reports` 是死字段

- 破坏点：
  模型层声明了 `consistency_reports`，但没有任何生产写入或读取。
- 证据：
  `src/cccc/ralph/models.py:343-350` 定义字段。
  全局检索显示只有模型定义和默认值测试命中：`tests/test_ralph_semantic.py:171`。
  `src/cccc/ralph/validator.py:252-260` 返回报告时并未填充该字段。
- 影响：
  这会误导后续开发，以为验证报告具备一致性汇总能力，实际没有。
- 建议修复：
  要么删除该字段；要么在统一的 verify/report path 中真正汇总并写入。

### MEDIUM 8. `auto_infer` 的衍生数据在报告层不一致：验证用的是“推断后任务”，fingerprints 用的是原 plan

- 破坏点：
  `validate_semantic()` 会基于 `effective_plan` 跑 auto-infer；`validate_with_project()` 计算 fingerprint 时却仍使用原始 `plan`。
- 证据：
  `src/cccc/ralph/semantic_validator.py:117-140` 先构建 `effective_plan`。
  `src/cccc/ralph/semantic_validator.py:191-232` auto-infer 只作用于 task copy，不修改原 plan。
  `src/cccc/ralph/validator.py:212-219` `validate_semantic(plan, ...)` 后又 `compute_fingerprints(plan, ...)`。
- 影响：
  开启 `auto_infer` 时，issue/hint 与 fingerprint 可能描述的是两套不同输入。
- 建议修复：
  `validate_semantic()` 返回 `effective_plan` 或 `effective_tasks`，由 `validate_with_project()` 统一复用。

### MEDIUM 9. `semantic_findings` 专用字段漏收 Phase 4 的 auto-infer 结果

- 破坏点：
  `ValidationReport.semantic_findings` 的白名单没有包含 `S_AUTO_INFER_NOT_READY`、`S_TARGETS_AUTO_INFERRED`。
- 证据：
  `src/cccc/ralph/validator.py:241-248` 的 `semantic_codes` 不包含这两个 code。
  但 Phase 4 validator 会产出它们：`src/cccc/ralph/semantic_validator.py:223-232`。
- 影响：
  主报告里能看到 auto-infer 提示，但 `semantic_findings` 子视图会漏报，导致上层消费者对 Phase 4 结果理解不完整。
- 建议修复：
  补齐 semantic code whitelist，或取消这种硬编码分流。

### MEDIUM 10. `_compute_task_scope()` 注释与实现不一致，依赖方向混淆会降低语义规则准确性

- 破坏点：
  注释写的是“当前任务 + 所有传递 downstream 任务”，实现却用 `transitive_deps()` 取 upstream 依赖，再额外加一层直接 dependents。
- 证据：
  `src/cccc/ralph/semantic_validator.py:360-375`。
  `src/cccc/ralph/graph_utils.py:14-25` 的 `transitive_deps()` 明确返回依赖闭包。
- 影响：
  `S_INTERFACE_REFS_OUTSIDE_SCOPE`、`S_MASSIVE_REFACTOR` 等基于 scope 的规则可能产生假阳性/假阴性。
- 建议修复：
  明确 scope 语义后重写：若要 downstream，就构建反向图做传递闭包；不要混用 upstream + 一层 downstream。

## 测试缺口

### HIGH A. Phase 4 “integration” 验证实际上只验证 CLI 表面

- 证据：
  `plans/phase4-deep-integration.yaml:639-656` 的 T8 验收只检查 CLI help 和 `gate-report --help`。
- 结果：
  这不足以证明 daemon 调度、daemon 验证、worker prompt、metrics 回流任何一条真实链路是通的。

### HIGH B. orchestrator/daemon 测试大量 monkeypatch `suggest_ready_batch()`，绕过真实 Phase 4 逻辑

- 证据：
  `tests/test_foreman_workflow.py:1459-1462`、`1575-1583` 都把 `orchestrator.ralph.suggest_ready_batch` stub 掉。
- 结果：
  测试验证了 orchestration plumbing，但没有验证 Ralph 真实调度逻辑，更没有验证 semantic path。

### HIGH C. 现有 Phase 4 测试几乎都是纯函数/CLI 帮助文本，不覆盖 `submit --plan -> daemon -> resuggest/verify -> metrics`

- 证据：
  `tests/test_ralph_semantic.py:181-240` 直接手写 metrics；
  `1005-1066` 测 `suggest_deps` 纯函数；
  `1549-1658` 测 `core.suggest()`；
  `1849-1958` 测 `verify_post_change_consistency()` 和 `core.verify()`；
  `2229-2244` 只测 CLI help。
- 结果：
  Phase 4 的真实生产断链没有被任何端到端测试覆盖。

## 对拟议自动化修复方向的评估

### 1. 让 `RalphService.suggest_ready_batch()` 委托 `ralph.core.suggest()`

- 结论：
  方向正确，但“只做函数委托”本身不够，按当前数据流是不可行的。
- 必要前提：
  daemon 必须拿到完整 `Plan` + `TaskSpec.semantic` + `Plan.auto_infer` + `semantic_mode` + `SemanticProvider`。
  运行态还要把 engine 状态同步进 `plan.state`。
- 主要风险：
  若继续用当前 `TaskRef`，委托后仍然没有 semantic 输入，只会得到 Phase 3 之前的行为。
  daemon 当前没有 `SemanticProvider` 创建路径，`semantic_provider=None` 会让 `core.suggest()` 自动退化。

### 2. 在 `on_task_completed()` 增加自动标注，打通 metrics feedback loop

- 结论：
  可以做，但只能“有限规则、保守标注”，不能把所有 Phase 4 rule 一锅端地自动标注。
- 原因：
  `true_positive / false_positive / missed` 需要真实标签；而完成事件 + verification pass/fail 往往不足以给 `S_SUGGEST_CONFLICT`、`S_IMPLICIT_SYMBOL_DEPENDENCY`、`S_RECOMMEND_TESTS` 这类规则自动定性。
- 主要风险：
  如果标签质量差，`compute_gate_readiness()` 会被污染，最终把错误 gate 错误地打开。
- 建议：
  只对有明确 runtime truth 的规则先自动标注。
  每条 metric 增加 `label_source` / `label_reason` / `workflow_id`。
  对无法确定的情况显式不写入，不要猜。

### 3. 在 plan registration flow 自动做 `auto_infer` 和 `suggest_deps`

- 结论：
  方向也正确，但必须基于“shadow resolved plan”，不能在当前 `TaskRef` 流里偷偷改 engine DAG。
- 主要风险：
  `suggest_deps` 本来被设计为“不修改 plan，只给建议”；如果注册阶段直接改依赖图，而 plan 文件没有同步/audit，会造成 plan truth 与 engine truth 分叉。
  `auto_infer` 依赖 gate readiness 和 semantic provider；若静默失败或静默降级，会再次制造不可见状态。
- 建议：
  registration 先加载 full plan，生成 `resolved_plan`：
  1. 应用 `auto_infer`。
  2. 计算 `suggested_deps`。
  3. 明确记录哪些边是“建议采用”还是“自动采用”。
  4. 将 resolved graph 持久化到 workflow metadata，并对外可见。

## 建议整改优先级

1. 统一数据模型边界：决定 daemon 用 full plan 还是扩展 `TaskRef`；不解决这个，其他自动化都只是表面接线。
2. 统一生产主路径：调度走 `core.suggest()`，验证走 `core.verify()`，并在 daemon 内引入 `SemanticProvider`。
3. 引入 `resolved_plan` / shadow plan 机制：在注册阶段显式处理 `auto_infer`、`suggested_deps`、`plan.state` 同步。
4. 设计保守的 metrics labeler：只给有 runtime truth 的规则自动写 metrics，并把 metrics 路径锚定到 project root。
5. 补真实集成测试：至少覆盖 `workflow submit --plan -> register_and_suggest -> resuggest -> verify -> on_task_completed -> metrics`。
6. 清理报告/模型不一致项：`consistency_reports`、`semantic_findings` 白名单、auto-infer fingerprints、scope 方向 bug。

## 最终判断

当前 Phase 4 不是“实现不完整”，而是“实现位置错了”。它交付了一个功能丰富的 CLI/库层语义系统，但没有把该系统接入 daemon 的真实调度、验证、prompt、反馈闭环。若不先修复数据模型与生产主路径统一，任何局部补丁都会继续制造新的 CLI-only 特性和新的假阳性测试。
