# CCCC 问题清单 v5 (未解决) — Ralph 改进专项

> 日期：2026-04-04（v5.2 蓝图对齐更新）
> 状态：10 项待实施改进 + 4 项蓝图新增（Ralph Agent 层 + 超出范围清单 + verification_mode + 两阶段拆分对齐）
> 已完成：RO-7n/12/13n/14n/15/16/17/18/19（2026-04-19 fix-v5-ralph-ro.yaml，365 tests pass）
> 已完成：RO-20/21/22/23（2026-04-22 fix-ro-20-23.yaml，278 tests pass）
> 已完成（v14 验证）：RO-20（W_WORKER_EXCEEDED_SCOPE）、RO-22（schema_version 引导）、RO-23（required_issues 格式提示）
> E2E v14 验证：综合 3.0/5（结果 2/5，过程 3/5，体验 3.8/5）
> 更新：2026-04-22 v14 E2E 新增 RO-24（verification checks 跨 task scope 未检测）
> 更新：2026-04-24 Codex 设计审查新增 RO-25~RO-31（verify gate、状态源、fallback、claimed_paths、模型重复字段、运行时漂移、复杂度）
> 更新：2026-04-25 Codex 复核：4 个 review finding 已有修复/测试覆盖；RA-1/RA-3 的真实 Ralph Agent 路径仍未落地，保持未解决
> 更新：2026-04-25 Codex 复核新增 RO-32（AI 修复测试/验收准入标准缺失）
> 全量版本：[问题清单-v5-ralph-full.md](./问题清单-v5-ralph-full.md)
> 审查依据：[v5-综合审查报告.md](./v5-综合审查报告.md)
> 蓝图对齐：[工作流蓝图.md](./工作流蓝图.md) v0.3（两阶段拆分 + Ralph Agent）
> 评估报告：[e2e-实战评估报告-v14.md](./e2e-实战评估报告-v14.md)
>
> **本文档只保留未解决的改进项和已知局限。已完成条目与历史实现记录保存在 full 版本中。**

## 一、待实施改进

### RO-21 Ralph validate 执行无 ledger 事件（P2，部分修复）
- **严重度**：Medium — 过程审查无法审计 validate 时序
- **现状（2026-04-22）**：`_write_validation_event()` 已实现，支持 `workflow.plan_validated` / `workflow.plan_validation_failed` 事件含 plan_hash + ruleset_digest。但 v14 E2E 中 Foreman 未传 `--group` 参数，ledger 无事件
- **改进方案**：ralph validate 自动检测当前 group（从 project_root 反查 attached group），无需手工传 --group
- **验收标准**：ledger 中出现 `workflow.plan_validated` 事件，时戳早于同一 plan 的 batch_registered 事件
- **触发实例**：v14 E2E Codex 过程审查判定 "Foreman 是否执行 ralph validate" 为 "NO evidence"，因 ledger 无事件
- **与已有条目关系**：对应 v3 问题清单 FIX-E2E-5

### RO-24 Verification checks 跨 task scope 未检测（P2）
> **来源**：2026-04-22 E2E v14 实战
- **严重度**：Medium — 任务验证命令引用其他任务的文件范围，导致验证失败
- **现象**：v14 T1 的 verification check `test_backend` 执行 `pytest backend/tests/`，但 `backend/tests/` 属于 T2 的 claimed_paths。T1 首次 verification_failed 因为 T2 的测试目录还不存在
- **根因**：ralph validate 检查 claimed_paths 声明完整性，但不检查 verification.checks[].command 中是否引用了其他 task 的 claimed_paths
- **改进方案**：validate 新增规则：解析 checks[].command 中的路径引用，如果引用了不在当前 task claimed_paths 中的路径，报 `W_VERIFICATION_CROSS_SCOPE` warning
- **验收标准**：T1 的 check 引用 `backend/tests/`（T2 scope）时 validate 报 warning
- **触发实例**：v14 T1 verification_failed `test_backend exited with 1`，因 backend/tests/ 由 T2 创建但 T2 尚未执行

### RO-25 verification skipped 被当作 completed（P1）
> **来源**：2026-04-24 Codex 设计审查
- **严重度**：High — 没有真实验证的任务可进入完成态，削弱 Ralph verify gate 的核心价值
- **现象**：`RalphService.verify_completion()` 在无验证命令时返回 `overall_outcome="skipped"`；`WorkflowOrchestrator.apply_task_event()`、`WorkflowEngine.record_verification_result()`、`sync_plan_state()` 均把 skipped 作为可完成/可同步状态处理
- **根因**：`skipped` 同时表达“无法验证”和“可接受跳过”，缺少显式模式、人工决策或 agent 验证结果区分
- **改进方案**：默认将无验证命令视为 blocked/failed；只有显式 `verification_mode=agent` 且有独立验证结果时，才允许非 Ralph 命令完成；`workflow.verification_skipped` 不应默认进入 completed sync 集合
- **验收标准**：无 verification 的 task complete 不会产生 completed；ledger 中能区分 `verification_skipped_blocked` 与显式批准的 agent verification
- **触发实例**：`src/cccc/daemon/foreman/ralph_service.py` 无 specs 返回 skipped，后续 orchestrator/engine 将 skipped 推进完成态

### RO-26 Ralph/Workflow 状态事实源仍分裂（P1）
> **来源**：2026-04-24 Codex 设计审查
- **严重度**：High — CLI、UI、ledger、Ralph 可能读取到不同进度，导致重试、完成、清理和审计语义不一致
- **现象**：`ralph_ipc_handler.py` 维护 `_RALPH_STATE`；`RalphService` 维护 `_task_refs`、`_task_statuses`、`_processed_keys`；`WorkflowOrchestrator` 维护 `_active_workflows`；同时 `WorkflowEngine` 已经有 ledger-backed projection
- **根因**：早期内存态、运行时服务态和 ledger engine 在演进中叠加，没有明确“唯一写入源 + projection 只读源”边界
- **改进方案**：以 `WorkflowEngine`/ledger 为唯一写入源；`RalphService` 改为纯计算/验证服务，不保存生命周期状态；`_RALPH_STATE` 只保留未进入 engine 的外部 pending 消息，且有 TTL/清理规则
- **验收标准**：workflow progress、task verify、task complete、sync-state 均从 engine projection 推导；删除或隔离 `_task_statuses` 后 E2E 仍通过
- **触发实例**：`src/cccc/daemon/ralph_ipc_handler.py`、`src/cccc/daemon/foreman/ralph_service.py`、`src/cccc/daemon/foreman/workflow_orchestrator.py` 各自维护状态集合

### RO-27 fallback/降级路径弱化失败暴露（P1）
> **来源**：2026-04-24 Codex 设计审查
- **严重度**：High — 系统可能把“未处理/未配置/无可用 agent”包装成 ok 响应或自动改派，掩盖真实配置错误
- **现象**：`_try_process_batch()` 缺少 `group_id`/`project_root` 或 orchestrator 不可用时返回 `status="skipped"`，外层 `ralph_batch_suggest` 仍返回 ok；agent pool rejected 后 `_fallback_to_group_actors()` 自动批准并改派 group peer
- **根因**：为保持流程继续运行引入了隐式降级，但没有显式人工决策、配置开关或 ledger 级错误事件
- **改进方案**：auto_process 路径中缺关键参数/无 orchestrator 应返回 error；group actor fallback 必须改为显式 Foreman decision 或显式配置项，并写入可审计事件
- **验收标准**：缺 `group_id`/`project_root` 的 auto_process 返回失败；pool rejected 不会自动变 approved，除非请求里显式允许 fallback 并记录 reason
- **触发实例**：`src/cccc/daemon/ralph_ipc_handler.py::_try_process_batch()` 与 `src/cccc/daemon/foreman/workflow_orchestrator.py::_fallback_to_group_actors()`

### RO-28 claimed_paths 冲突语义在多层不一致（P1）
> **来源**：2026-04-24 Codex 设计审查
- **严重度**：High — admission control 可能放行父子路径冲突的并发写任务
- **现象**：`ralph.core._paths_overlap("src", "src/a.py")` 判定冲突；`kernel.claimed_paths.detect_write_set_conflicts()` 和部分 orchestrator pressure/single-writer 逻辑只做精确集合交集
- **根因**：路径规范化、全局写 claim、父子路径 overlap 的实现散落在 `ralph.core`、`ralph_service`、`workflow_orchestrator`、`kernel.claimed_paths`
- **改进方案**：把 `_normalize_claimed_path()`、`_paths_overlap()`、`detect_write_set_conflicts()` 收敛到 `kernel.claimed_paths`，所有调度/审批/验证只调用同一实现
- **验收标准**：`["src"]` 与 `["src/a.py"]` 在 Ralph suggest、engine approve_batch、cross-workflow pressure 中都被一致阻断
- **触发实例**：轻量探针显示 `kernel.claimed_paths.detect_write_set_conflicts([src, src/a.py]) == []`，而 `ralph.core._paths_overlap("src", "src/a.py") == True`

### RO-29 BatchResult 模型重复字段导致默认语义漂移（P2）
> **来源**：2026-04-24 Codex 设计审查
- **严重度**：Medium — suggest 输出的 batch 边界语义可能与代码作者预期相反
- **现象**：`BatchResult` 中 `task_metadata`、`batch_sequence`、`batch_boundary` 重复定义；后定义的 `batch_boundary=False` 覆盖前面的 `True`
- **根因**：模型演进时追加字段没有清理旧定义，Pydantic/Python 类体以后者为准，静态阅读容易误判默认值
- **改进方案**：删除重复字段，只保留一个明确的 `batch_boundary` 默认值；为默认值加模型单测
- **验收标准**：`BatchResult.model_fields["batch_boundary"].default` 与设计文档一致；重复字段静态检查通过
- **触发实例**：`src/cccc/ralph/models.py` L380-L385 同名字段重复；运行时检查默认值实际为 `False`

### RO-30 RalphService 运行时接口与文档设计漂移（P2）
> **来源**：2026-04-24 Codex 设计审查
- **严重度**：Medium — 文档承诺的观察能力与当前可执行能力不一致，容易产生假验收和死代码
- **现象**：设计文档仍描述 Ralph 为外部 Python daemon/Git watcher；当前 `ralph_service.py` 明确是 daemon-internal service；`merge_worktree()` 恒返回 `False`，`analyze_import_graph()` / `detect_test_impact()` 返回空列表
- **根因**：独立 daemon、CLI validator、daemon-internal service 三条路线同时存在，未统一职责边界；占位接口未从文档能力表中降级
- **改进方案**：统一目标架构：明确 Ralph 的三种形态（CLI 静态验证、daemon 内 verify gate、可选 Agent 审查）及其边界；删除或标记未实现接口，禁止文档把 stub 当作已完成能力
- **验收标准**：docs 与代码职责一致；stub 接口要么落地，要么不出现在主能力清单；对应测试不再接受恒 false/空列表作为成功路径
- **触发实例**：`src/cccc/daemon/foreman/ralph_service.py` L1-L5 与 `docs/ralph-foreman-workflow.md` 的外部 daemon 描述不一致

### RO-31 Ralph 核心模块复杂度超过维护阈值（P2）
> **来源**：2026-04-24 Codex 设计审查
- **严重度**：Medium — 过大的 orchestrator/validator 文件让状态转换、错误路径和验证规则难以审查，容易复发“接线正确但路径未执行”的问题
- **现象**：`workflow_orchestrator.py` 约 3072 行，`validator.py` 约 2262 行，`semantic_validator.py` 约 1330 行；`_build_task_prompt()`、`_apply_task_event_inner()`、`process_batch_suggestion()` 等函数超过 100 行
- **根因**：admission control、assignment、prompt 构造、verification gate、progress projection、ledger projection、通知逻辑集中在少数文件/函数中
- **改进方案**：按职责拆分：`admission.py`、`assignment_controller.py`、`verification_gate.py`、`prompt_builder.py`、`workflow_projection.py`、`validation_rules/`；拆分前先用现有 E2E/ledger replay 固定行为
- **验收标准**：核心 workflow/Ralph 文件回到项目约束范围或有明确例外；关键状态转换函数小于 50 行；拆分后现有 Ralph/Workflow 测试通过
- **触发实例**：静态 AST 扫描显示 `workflow_orchestrator.py` 有 13 个函数超过 50 行，`validator.py` 有 8 个函数超过 50 行

### RO-32 AI 修复测试/验收准入标准缺失（P1）
> **来源**：2026-04-25 Codex 复核 + 用户反馈
- **严重度**：High — AI 可用局部 mock、schema smoke 或 helper 单测证明“测试通过”，但真实 CLI/IPC/daemon 路径仍然失效，导致 P1/P2 修复反复在实际运行中暴露问题
- **现象**：现有文档已强调真实场景验收、Ralph verify gate 和 E2E，但未形成当前问题清单中的硬性测试准入项。修复时容易把 `SimpleNamespace` fake、synthetic state、字段默认值检查或错误预期测试当作完成证明
- **根因**：测试等级未区分；runtime-contract、unit-contract、schema-smoke、api-surface 被混用。P1/P2 修复没有要求先写能复现生产 bug 的红测试，也没有要求从真实入口断言权威状态源和副作用
- **改进方案**：新增 Ralph/Foreman 测试准入标准：P1/P2 修复必须至少包含一个 runtime-contract 测试，优先从 CLI/IPC op/daemon public entrypoint 进入，断言 public response、`WorkflowEngine`/ledger 权威状态和实际副作用；mock 只能隔离外部 IO/时间/进程，不得替代被验证的核心调用链
- **验收标准**：每个 P1/P2 修复记录至少一个“修复前失败、修复后通过”的真实入口测试；测试文件或任务说明标注测试等级；浅层 smoke 测试不得单独作为 P1/P2 完成依据；涉及“不再 fallback/不再 completed/不再 sync”的需求必须有负向测试
- **触发实例**：本轮 review finding 中，IPC verification 旧测试只断言 fake orchestrator 被调用；TTL 测试使用 `_created_at` synthetic 数据而非真实 `created_at`；状态源测试未构造 engine 空但 shadow 污染的负向场景；RA-3 测试曾把 `agent_pending` 可 complete 的错误行为固化为预期

---

## 一-B、蓝图 v0.3 新增改进（Phase 5）

> 来源：2026-04-04 工作流蓝图 v0.3 对齐讨论
> 定位：架构偏移修复完成后落地蓝图新增能力，对应优化路径方案 v5.2 Phase 5

### RA-1 Ralph Agent 层实现（P5，蓝图 §3.1/3.4）
- **严重度**：Medium — 蓝图核心新增能力，补强 Ralph 已知的语义校验局限
- **当前状态（2026-04-25 复核）**：部分实现，未验收。已存在 `--no-agent`、`beyond_scope` 标记和模板化 `review_beyond_scope()`，但 `RalphAgent` 仍是 stub/advisory placeholder，不调用 Gemini CLI Flash，不复用持久化 agent 机制，也没有每 workflow 实例生命周期。RA-1 保持未解决。
- **现象**：Ralph 当前只有静态结构校验，二、已知局限中的 RV-15/18/19/20、RO-10n 无法通过增加静态规则解决
- **蓝图要求**：
  - Gemini CLI Flash 模型，每个 workflow 一个实例，可脱离 workflow 独立启动
  - 只审查 Ralph 标记的"超出结构校验范围"项
  - 不读代码，基于 Ralph 输出 + plan 文本做语义判断
  - 结果标注"仅供参考"，无决策权，只能标记 + 转交 Foreman
  - 默认启用，`--no-agent` 退回纯静态模式
  - 复用现有持久化 agent 机制
- **改进方案**：
  - Ralph CLI 新增 `--no-agent` 参数
  - 实现 agent 调用层（启动 Gemini Flash → 传入 Ralph 标记的超出范围项 → 接收语义建议）
  - agent 结果合并到 validate 输出，标注为"agent 建议，仅供参考"
- **验收标准**：Ralph Agent 可启动并审查超出范围项；`--no-agent` 退回纯静态行为不变
- **与已知局限的关系**：RV-18（函数名不存在）、RV-20（调用位置可行性）将首先由 Agent 覆盖审查

### RA-2 "超出范围检查项清单"机制（P5，蓝图 §3.5）
- **严重度**：Medium — RA-1 的前置依赖，Agent 需要知道审查什么
- **蓝图要求**：
  - 静态配置文件，随 Ralph 版本发布，工作流过程中不变
  - 初始内容来源于本文档"二、已知局限"：RV-15/18/19/20、RO-10n
- **改进方案**：
  - 新建配置文件（如 `ralph/beyond_scope_checklist.yaml`）
  - Ralph validate 时自动对照清单，匹配的问题标记为 `beyond_scope: true`
  - `ValidationIssue` 模型新增 `beyond_scope` 字段
  - validate 输出格式向后兼容（缺失字段默认 false）
- **验收标准**：validate 输出的 issue 中包含 beyond_scope 标记；标记内容与清单一致

### RA-3 verification_mode 字段支持（P5，蓝图 §3.2）
- **严重度**：Medium — 验证与执行分离的基础
- **当前状态（2026-04-25 复核）**：部分实现，未验收。`TaskSpec.verification_mode`、validator 检查、`suggest()` 元数据和 `complete --verify` 拒绝 `agent_pending` 已具备；但 `core.verify()` 与 daemon `RalphService.verify_completion()` 在 agent 模式仍只返回 `agent_pending`，未调用 Ralph Agent 执行 Foreman 预设模拟测试用例。RA-3 保持未解决。
- **蓝图要求**：
  - plan.yaml 每个 task 声明 `verification_mode: ralph|agent`
  - `ralph` 模式：结果可预期，走现有 `core.verify()` 路径
  - `agent` 模式：结果不可预期，由 Ralph Agent 执行 Foreman 预设的模拟测试用例
  - Worker 全程不知道测试输入和预期输出
- **改进方案**：
  - `TaskSpec` 模型新增 `verification_mode: Optional[str] = "ralph"`（向后兼容）
  - Ralph validator 新增规则：校验 verification_mode 值为 ralph|agent
  - verify gate 实现分流：ralph 模式走 `core.verify()`，agent 模式调用 Ralph Agent
- **验收标准**：plan.yaml 可声明 verification_mode；ralph 模式走现有路径不变；agent 模式走 Agent 路径

### RA-4 两阶段拆分对齐（P5，蓝图 §4.1）
- **严重度**：Medium — 保留 Ralph 已有的调度能力
- **蓝图要求**：
  - Ralph suggest() 输出 Task 批次（第一阶段）→ Foreman 对每个 Task 做 Module 拆分（第二阶段）
  - 现有 `_unlock_score()` / `_write_sets_conflict()` / `_dependency_block_reasons()` 在新流程中继续负责 Task 间并行安全
  - 批次完成后 Ralph suggest 计算下一批
- **改进方案**：
  - 验证现有 suggest 算法在"Task 级拆分 + Module 级并行"模型中工作正常
  - 如需调整 `BatchResult` 输出格式（如携带 Task 的功能描述供 Foreman 拆分），做向后兼容扩展
- **验收标准**：两阶段拆分 E2E 跑通；suggest 输出的批次正确反映依赖和写冲突

---

## 一-C、2026-04-25 Review findings 状态更新

> 来源：Codex 复核，按 v5 Ralph 蓝图重新判断本次改动是否偏离要求。

| 编号 | 对应问题 | 状态 | 当前判断 |
|------|----------|------|----------|
| RF-2026-04-25-1 | IPC verification 未回写 engine state | 已补修复，待完整回归 | 当前 `WorkflowOrchestrator._record_external_verification()` 已调用 `WorkflowEngine.record_verification_result()`，新增真实 IPC→orchestrator→engine 测试覆盖 `skipped -> FAILED` 与 `passed -> COMPLETED`。 |
| RF-2026-04-25-2 | `_RALPH_STATE` TTL cleanup 只处理 synthetic `_created_at` | 已补修复，待完整回归 | cleanup 已支持真实 model `created_at`，并在 `try_handle_ralph_op()` 入口运行；新增真实 `created_at` 和 dispatcher cleanup 测试。 |
| RF-2026-04-25-3 | `RalphService` 仍从 shadow `_active_workflows` fallback 读取状态 | 已补修复，待完整回归 | `_build_task_status_index()` / dependency check 已收敛到 workflow engine；新增 shadow 污染负向测试。 |
| RF-2026-04-25-4 | `agent_pending` 可被 CLI 标记 completed | 已补修复，待完整回归 | `complete --verify` 已拒绝 `agent_pending` 且不写 `completed_task_ids`。 |
| RF-2026-04-25-5 | RA-1/RA-3 真实 Ralph Agent 路径缺失 | 未解决，蓝图偏离 | 当前实现只是 stub + pending skeleton；未启动 Gemini CLI Flash，未复用持久化 agent，未执行 Foreman 预设高仿真模拟测试用例。此项并入 RA-1/RA-3 继续跟踪。 |

---

## 二、已知局限（NOTE 类，无代码改进空间）

> 📋 蓝图 v0.3 新增：标注"🤖 Agent 可覆盖"的条目将作为 Ralph Agent 的首批审查目标（RA-1/RA-2），
> 纳入"超出范围检查项清单"（蓝图 §3.5）。

| 编号 | 观察 | 说明 | Agent |
|------|------|------|-------|
| RV-15 | Ralph 新规则自身的 bug 无法自检 | 印证 findings #13：结构校验和代码审查互补 | 🤖 可覆盖 |
| RV-18 | goal_behavior 中引用的函数名可能不存在 | 超出结构校验范围，需 Codex 审查。2026-04-22 fix-ro-20-23 T3 原方案引用 `_check_strict_extra_fields()` 作为 critical_flows 校验入口，但实际入口是 `_collect_manual_load_issues()`——Codex 审查发现并修正 | 🤖 可覆盖 |
| RV-19 | 模型扩展可能破坏已有语义（awareness_paths 案例） | Codex 审查发现，已在实施中正确处理 | 🤖 可覆盖 |
| RV-20 | monitor wiring 调用位置可行性无法静态验证 | TaskEvent 类型受限，已改为公共 API 方案 | 🤖 可覆盖 |
| RV-21 | accumulator 重构易引入分类回归（conftest 案例） | Wave 6 手动修复，提示需完整回归测试 | — |
| RV-22 | W_UNCLAIMED_TEST_FOR_SOURCE 对高 import 文件产生大量警告 | RV-10 indirect→hint 已缓解 | — |
| RO-5n | W_FLOW_SEGMENT_UNOWNED 对 verification role 的 T-int 类任务过度报警 | T-int 天然覆盖所有 flow 但不 claim 入口，应考虑 verification role 豁免 | — |
| RO-6n | 同一 entrypoint 被多个 flow 使用时 W_FLOW_OWNER_NO_VERIFICATION 噪音大 | T3/T4/T5 共享 validator.py 但各自只验证自己的 flow，触发大量 NO_VERIFICATION | — |
| RO-10n | verification 命令强度无法检测连接级/运行时语义 bug | v4 pytest 全过但 SQLite FK 未启用；印证 findings #13 结构校验和代码审查互补。2026-04-22 fix-ro-20-23 T2 原方案将已实现的 `_write_validation_event()` 当作待实现功能——Ralph validate 通过但 Codex 审查发现任务目标已在代码中存在，避免了重复实现冲突 | 🤖 可覆盖 |
| RO-11n | 计划中"删除函数"的副作用链无法静态检测 | Batch C Codex 审查发现：删除 _fallback_to_group_actors 后 rejected batch 仍走 on_batch_started 等副作用，Ralph 无法建模函数内控制流 | 🤖 可覆盖 |
| RO-12n | 同一文件多入口只覆盖部分时 Ralph 不报警 | Batch C Codex 发现：plan 修改了 process_batch_suggestion 但遗漏了 register_and_suggest 这条绕过入口，Ralph 的 claimed_paths 是文件级不是函数级 | 🤖 可覆盖 |
