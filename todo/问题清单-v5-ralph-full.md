# CCCC 问题清单 v5 — Ralph 改进专项（Full 版，v36 起）

> 历史归档（v1-v35）：[问题清单-v5-ralph-full-v1.md](./问题清单-v5-ralph-full-v1.md)
> 短版（仅未解决）：[问题清单-v5-ralph.md](./问题清单-v5-ralph.md)

---

## E2E v70 实战归档（2026-06-08）— v60–v69 反假完成机制真实 daemon 活体收口（live-verified）

> 报告：[e2e-实战评估报告-v70.md](./e2e-实战评估报告-v70.md)。项目：FastAPI 短链接服务（API Key 鉴权 + 限流 + 点击分析 + SSRF）。
> 注：「E2E v70」为 E2E 报告序列（v58→v70），区别于本归档中 solve 批次标签 v70/v71。

v60–v69 期间大量 **in-process** 验证（真实代码链但非子进程 ccccd）的反假完成机制，本轮首次在**真实 daemon E2E** 下全面活体背书，全部 ✅ 生效：

- **模型选择保真**（FL-74 默认 codex / MSE / AF-09）：foreman(claude) 读 foreman-capability-guide.md 后给 T1–T6/T8 执行任务全选 codex-gpt-5.4、仅 T7 安全审查用 claude；观察者实时监控 daemon 确认 actor runtime 分布为 3 codex(exec-a/b/c) + 1 claude(sec-rev) + foreman(claude)。
- **FL-73 并行度强制门**（D≥min(E,2)）：`ralph suggest` estimated_parallelism=3 → foreman 建 3 codex 执行者；B2 实测 `running=3` 三任务并行 fan-out，无串行退化（opus4.6→4.8 并行回归确认已修）。
- **AF 真异步 suspend-until-terminal**（AF-07/08）：WORKFLOW_EVALUATION execution_engine=af；8/8 完成，全程无死循环、无 deferred 卡死；执行期两次 fail→override 恢复链正常工作。
- **反假完成 / AEGIS evidence gate**：T1 compile + 6/6 pytest 全绿，仍因 `cccc task complete` 缺 `--evidence` 被 `E_AEGIS_EVIDENCE_MISSING` 拦下——"测试绿≠完成"活体复现。
- **章节实质化门**（M2-C / UX-23 修复）：flow step-4 检查逐项 PASS（正面反馈 833 / 负面反馈 1248 / 手工干预 837 / Worker 563 / 评分 599 chars）；预备版(01:41)空章节 → 定稿(01:49)补全，**UX-23 第五轮未复现**。
- **诚实测试统计**：自动采集 collection failed → `test_stats_reliable=false` + foreman 手动复跑 51 passed，未伪造绿。

**衍生开放项**（已登入短版 tracker「E2E v70 实战新发现」）：RV-64（state 不覆盖全任务/override 散落）、DG-43（model_key 默认漂移未覆盖 usage 日志）、FL-76（派发无视 --assignments）、FL-77（verifier 不走 shell）、FL-78（retry 状态机死锁）、FL-79（路由日志非 per-attempt）、RV-65（独立审查一等化）、DG-42（forbidden_flows/coverage_hints）、RV-66（交付代码缺陷 validate 盲点）、UX-24（派发原语/SUSPICIOUS 误报）。Codex 双盲：results=adjust/74，process=revise/43。

---

## 代码修复归档（2026-06-07）— v63 第二阶段里程碑：M1-5 verification 主路径行为命令门（behavior-verified）

> 来源：plan.yaml v63 批次（T1 M1-5）。用户指令「读取记忆中 solve flow，修复下一阶段问题」。经 solve flow
> 6/6 步通过 + Codex 设计评审（step-3 verdict=adjust，5 finding 全裁决：F1/F2/F4/F5 ACCEPTED 并改 plan，
> F3 PARTIAL → DG-18 + critical-flow 升 error DEFERRED）+ 独立 CLI 对抗验证（真实 `ralph validate` 翻转）。
> 全量套件 **3788 passed / 120 skipped / 0 failed**。衍生检测能力缺口 DG-18（主路径命令与被覆盖 flow 因果
> 关联）/ DG-19（launcher/wrapper/subshell 命令解析残余）记入短版 DG 规则族。

| ID | 标题 | 状态 | 归档原因 |
|----|------|------|---------|
| M1-5 | verification 主路径行为命令门 | behavior-verified | 真实 `ralph validate` CLI：运行时行为 task（role=integration / level=e2e / 覆盖 critical_flow）仅 pytest → W_VERIFICATION_NO_MAIN_PATH_COMMAND；含 cccc/ralph CLI 或 .log grep 不报；13 验收用例 + CLI 双向翻转 |

**evidence bundle（M1-5）**：
- issue_id: M1-5
- root_cause: `ralph validate` 无规则强制运行时行为 task 的 verification 含主路径命令；`_is_behavioral_check`(coverage.py:34) 把 pytest 直接判为 behavioral → pytest-only 运行时 task 一律放行（FL-66/RV-48 在 plan 层的温床）
- fix: 新增 `_check_verification_main_path_command` + `W_VERIFICATION_NO_MAIN_PATH_COMMAND`（coverage.py:136/334），helper `_split_shell_subcommands`/`_command_program`/`_is_main_path_command`/`_task_is_runtime_behavior`（coverage.py:287-331）
- canonical_owner: src/cccc/ralph/validation_rules/coverage.py::_check_verification_main_path_command
- active_path: 登记 get_all_rules()（__init__.py:139）+ __all__（:229/:240）+ 接入 validator._collect_structural_issues（validator.py:264，即 CLI `ralph validate` 活跃路径，非死代码）
- trigger_semantics: role=="integration" OR level=="e2e" OR 覆盖 critical_flow（复用 `_task_covers_flow`，认 covers.flows 与 claimed critical entrypoint 两种覆盖，采纳 Codex F2）
- candidate_semantics: 与 core.py::_resolve_verification_specs 真实执行一致 —— checks 非空只认 required check.command，否则才看 verification.command（采纳 Codex F1，堵「永不执行的 top 命令」与「非 required check」两条空投旁路）
- main_path_predicate: 程序名（经 filesystem_validator._unwrap_command 剥离 env/timeout/uv run/poetry run/pipenv run + sudo，shlex 切词，basename 小写）∈ {cccc,ralph}，或 ∈ {grep,rg,egrep,fgrep,zgrep} 且子命令含 ".log"；pytest（python）不算（采纳 Codex F4；按程序名而非 substring，不被 `python -m pytest tests/ralph/...` 路径里的 "ralph" 蒙混）
- behavior_verification_unit: tests/ralph/test_verification_main_path.py 13 passed（含负向 1/2/3/3b/7/7b/7c、正向 4/5/6/6b/8、登记 9）
- behavior_verification_cli: 独立 `ralph validate plan_neg.yaml --no-agent`（pytest-only integration task）→ W_VERIFICATION_NO_MAIN_PATH_COMMAND 命中 1；`plan_pos.yaml`（check=`cccc model suggest backend`）→ 命中 0（真实主路径双向翻转）
- regression: tests/ralph/test_integration_call_evidence.py + tests/test_module_split.py 全绿；全量 3788 passed / 120 skipped
- codex_review: step-3 verdict=adjust，5 finding 全裁决（F1/F2/F4/F5 ACCEPTED 落地；F3 PARTIAL → DG-18 记缺口 + critical-flow 升 error DEFERRED，evidence 带 covered_critical_flows 供后续升级）
- severity_scope: warning 可 suppress、不入 _NON_SUPPRESSIBLE_ALWAYS（强制门升级待误报率验证，沿用 DG-1/3/4 约定）
- derived_gaps: DG-18（causal-linkage）、DG-19（launcher-wrapper-resolution）
- regression_lock: python -m pytest tests/ralph/test_verification_main_path.py -v

---

## 代码修复归档（2026-06-07）— v62 第二阶段批量：DG-3 + DG-4 + M2-C/UX-23 + M2-B（behavior-verified）

> 来源：plan.yaml v62 批次（T1 DG-3 / T2 DG-4 / T3 M2-C+UX-23 / T4 M2-B / T5 集成脊柱）。用户在 solve flow
> 明确「都修复」。经 solve flow 6/6 步通过 + Codex 设计评审（step-3 verdict=incomplete，9 finding 全 accepted 并改 plan）
> + **独立对抗验证两轮**：首轮 verdict=defects-found（4 真实缺陷），修复后复核 3/4 CLOSED、第 4 项确认为
> 「warning 不翻 valid」的设计本意（非缺陷）。全量套件 3775 passed / 120 skipped / 0 failed。
> 衍生检测能力缺口 DG-15（writer↔checker 标题 parity）/ DG-16（跨函数守卫支配）/ DG-17（兜底信号可达性）记入短版 DG 规则族。

| ID | 标题 | 状态 | 归档原因 |
|----|------|------|---------|
| DG-3 | observable-fallback（except 静默兜底告警） | behavior-verified | 真实 `ralph validate`：except 吞异常/非抛出退出且无 warning+/ledger-emit → W_SILENT_FALLBACK；有信号不报；扫 plan_scope∪claimed 生产文件；独立复核 CLOSED |
| DG-4 | guard-ordering（守卫先于副作用） | behavior-verified | 真实 `ralph validate`：守卫晚于 emit_workflow_terminal → W_GUARD_AFTER_SIDE_EFFECT；真实 complete_workflow 正确顺序不误报；独立复核 CLOSED |
| M2-C | 空/不实质 EVALUATION 阻断 workflow.completed | behavior-verified | 真实 complete_workflow：空/占位/<40 字/八维缺失/改名标题 → pending + workflow.evaluation_incomplete，不 emit terminal；独立复核 CLOSED |
| UX-23 | 定性章节持续为空——系统级强制 | behavior-verified | 由 M2-C min_chars + 八维 writer/parser 一致 + 精确标题行匹配覆盖；独立复核改名绕过 CLOSED |
| M2-B | 选型决策留痕 + override 留痕（主路径） | behavior-verified | 真实 process_batch_suggestion 显式+pool 两路径均写 model.selection_decision；override 写 model.selector_bypass；独立复核 pool path CLOSED |

**DG-3 evidence bundle（v62）**
- issue_id: DG-3（warning 级第一道防线；间接信号可达性 → DG-17）
- original_symptom: 无规则检测 except handler 吞异常/静默回落（无 >=WARNING 日志/无 ledger emit）→ 静默 fallback 无人察觉
- claimed_fix: 新增 `_check_observable_fallback` + `W_SILENT_FALLBACK`（coverage.py），扫 plan_scope∪claimed 生产 .py；except 内非抛出退出（return 任意/continue/break/pass）且无 logger.warning+/logging.warning+/append_event/publish_event → warning
- changed_paths: src/cccc/ralph/validation_rules/coverage.py, __init__.py, validator.py, tests/ralph/test_observable_fallback.py
- active_entrypoint: CLI `ralph validate` → validate_with_project → _collect_structural_issues → _check_observable_fallback（validator.py:269，紧随 _check_active_path_reachability）
- active_path_trace: plan_scope∪claimed 生产模块 → AST 遍历 except handler → 无信号静默退出 → emit W_SILENT_FALLBACK（evidence: file/function/lineno）
- runtime_conditions: plan_scope 或 claimed_paths 含 src/**/*.py 非测试文件
- expected_behavior: 静默 except 回落被标记 warning；有 WARNING 日志/ledger emit 的不标记
- observed_behavior: 独立复现：app.py `except Exception: return "fallback"` → W_SILENT_FALLBACK；带 logger.warning 不报；claimed-only（plan_scope 空）也能扫到
- fallback_behavior: warning 级、可 suppress（第一道防线，非可压制强制门待误报率验证升级，记 DG-14 族）；不翻 valid:true（warning 设计本意）
- evidence_locations: .ralph-flow/step-5-execute/T1.json, adversarial_verify.json, reverify.json
- regression_test: python -m pytest tests/ralph/test_observable_fallback.py tests/ralph/test_integration_call_evidence.py -v
- archive_decision: 双独立验证（首轮发现自违例 + claimed-paths 盲区，已修复 CLOSED），全量 3775 passed

**DG-4 evidence bundle（v62）**
- issue_id: DG-4（同函数级；跨函数守卫支配 → DG-16）
- original_symptom: 无规则检测「声称阻断 X 的守卫晚于 X 副作用」（守卫顺序漂移）
- claimed_fix: 新增 `_check_guard_ordering` + `W_GUARD_AFTER_SIDE_EFFECT`，窄映射 {emit_workflow_terminal,on_workflow_completed}↔{workflow_evaluation_empty_sections,_check_section_substantive}；同函数内 min(guard lineno) > side-effect lineno → warning
- changed_paths: src/cccc/ralph/validation_rules/coverage.py, __init__.py, validator.py, tests/ralph/test_guard_ordering.py
- active_entrypoint: CLI `ralph validate` → _collect_structural_issues → _check_guard_ordering（紧随 _check_observable_fallback）
- active_path_trace: 函数体按 lineno 收集 ast.Call → side-effect 先于其映射 guard → emit（evidence: function/side_effect_call/guard_call + 两 lineno）
- runtime_conditions: plan_scope∪claimed 生产文件含受管副作用与对应守卫调用同函数
- expected_behavior: 守卫晚于副作用告警；守卫先于副作用或无守卫不告警；真实 complete_workflow（守卫先）不误报
- observed_behavior: 独立复现：负例告警、正例不报、真实 workflow_orchestrator.py 锚定不误报、claimed-only 也能扫到
- fallback_behavior: warning 级可 suppress；不翻 valid:true（设计本意）
- evidence_locations: .ralph-flow/step-5-execute/T2.json, adversarial_verify.json, reverify.json
- regression_test: python -m pytest tests/ralph/test_guard_ordering.py tests/ralph/test_integration_call_evidence.py tests/ralph/test_observable_fallback.py -v
- archive_decision: 双独立验证（claimed-paths 盲区已修 CLOSED），全量 3775 passed

**M2-C / UX-23 evidence bundle（v62）**
- issue_id: M2-C + UX-23
- original_symptom: complete_workflow 仅按 5 section「strip 非空」阻断；单字符过闸；八维定性维度未生成/未解析/未强制；定性章节持续空（v50/51/57/58）
- claimed_fix: _check_section_substantive(content,*,min_chars=40) + WORKFLOW_EVALUATION_RETRO_DIMENSIONS(8 维)；writer(workflow_evaluation_io.py) 生成 8 个 `## 维度` 子标题带占位符；parser 精确「## heading」整行匹配（修复改名前缀绕过）；judging 集合=5 section+8 维
- changed_paths: src/cccc/daemon/foreman/workflow_evaluation.py, workflow_evaluation_io.py, tests/test_workflow_evaluation_substantive.py（+回归更新 tests/test_foreman_workflow.py）
- active_entrypoint: WorkflowOrchestrator.complete_workflow → workflow_evaluation_empty_sections(min_chars=40) → 阻断在 emit_workflow_terminal/on_workflow_completed 之前（守卫顺序满足 DG-4）
- active_path_trace: 写评估文件 → empty_sections（含八维）非空 → emit workflow.evaluation_incomplete + 返回 pending，不 emit terminal；补齐后才 completed
- runtime_conditions: complete_workflow 真实执行
- expected_behavior: 空/占位/<40 字/八维缺失/改名标题 → 阻断 workflow.completed
- observed_behavior: 独立复现：缺八维→pending 无 completed；全填→completed；`## runtime 选择（改名）`→仍 incomplete（绕过 CLOSED）
- fallback_behavior: gate 不通过则 pending（不静默完成）
- evidence_locations: .ralph-flow/step-5-execute/T3.json, adversarial_verify.json, reverify.json
- regression_test: python -m pytest tests/test_workflow_evaluation_substantive.py tests/test_foreman_workflow.py -v
- archive_decision: 双独立验证（首轮改名绕过已修 CLOSED），全量 3775 passed

**M2-B evidence bundle（v62，部分闭合：留痕已落主路径；读端 selection/rating 算法 FC-1/FC-2 既有）**
- issue_id: M2-B（本批闭合 read-end 留痕 + override 留痕；rating 消费已在 select_model_for_task）
- original_symptom: 选型决策无可审计留痕事件；override 仅 logger.warning（@staticmethod 无 ledger 上下文）不可审计
- claimed_fix: _build_explicit_assignment_result 写 model.selection_decision；pool 分支 _evaluate_batch 后统一补发 model.selection_decision（不重复显式分支）；_warn_on_explicit_runtime_override 改实例方法 + 写 model.selector_bypass；except 内 logger.warning（非静默）
- changed_paths: src/cccc/daemon/foreman/assignment_batches.py, tests/test_model_selection_main_path.py
- active_entrypoint: WorkflowOrchestrator.process_batch_suggestion →（显式 _build_explicit_assignment_result / pool _evaluate_batch）→ append_event(group.ledger_path, kind="model.selection_decision"/"model.selector_bypass")
- active_path_trace: 真实 process_batch_suggestion 两分支均写 selection_decision（data: task_id/chosen_runtime/chosen_model_key/...）；runtime 不一致写 selector_bypass
- runtime_conditions: process_batch_suggestion 真实执行（显式 + pool）
- expected_behavior: 两路径均留痕；override 写 bypass；runtime 一致不误发 bypass
- observed_behavior: 独立复现：pool path（无显式 assignments）ledger 出现 model.selection_decision（chosen_runtime=codex）；override 写 selector_bypass
- fallback_behavior: ledger 写失败 best-effort + logger.warning（非 DG-3 静默）
- evidence_locations: .ralph-flow/step-5-execute/T4.json, adversarial_verify.json, reverify.json
- regression_test: python -m pytest tests/test_model_selection_main_path.py -v
- archive_decision: 双独立验证（首轮 pool-path 缺失已修 CLOSED）；**仍开放（移交短版 M2-B 表）**：rating 变化驱动 suggest 的 E2E、命名空间统一、actor add CLI 读端 等子项未在本批闭合，仅闭合留痕主路径

---

## 代码修复归档（2026-06-07）— v61 第二阶段开篇：DG-1 active-path reachability（模块级，behavior-verified）

> 来源：plan.yaml DG-1 批次（T1：新增 `_check_active_path_reachability` + `W_INTEGRATION_DORMANT_PATH`）。
> 经 solve flow（6/6 步通过）+ Codex 设计评审（step-3 verdict=incomplete，5 finding 全 accepted/deferred）
> + **双独立验证**（我方真实 CLI `ralph validate` 非 git 临时项目 + Codex 独立对抗复核）。
> Codex 独立对抗首轮发现 1 major 误报缺陷（自注册但无人 import 的模块被误判 dormant），已修；
> 复核 verdict=works、prior_defect_fixed=True、cli_warning_behaves_correctly=True、real_defects=[]。
> 全量套件 3751 passed / 120 skipped / 0 failed。衍生检测能力缺口 DG-14（函数级可达性 + 动态/re-export
> 导入解析 + 强制门升级）记入短版 DG 规则族，通用规则待后续。

| ID | 标题 | 状态 | 归档原因 |
|----|------|------|---------|
| DG-1 | active-path reachability（模块级 heuristic） | behavior-verified | 真实 `ralph validate` CLI：休眠路径告警 / 可达不告警 / opt-in 不启用 / 自注册无 import 不误报；Codex 独立复核 verdict=works real_defects=[] |

**DG-1 evidence bundle（v61）**
- issue_id: DG-1（模块级范围；函数级/动态导入剩余盲点 → DG-14）
- original_symptom: `_check_integration_call_evidence` 只验证「某生产文件 import+call 了 claimed 模块」，不验证该使用点从默认 entrypoint 可达 → 接到休眠/legacy 死路径的组件被放行（FL-66 v53 AF 引擎「零件造好没装到车上」、RV-48 死路径伪集成）
- claimed_fix: 新增 `_check_active_path_reachability(plan, *, project_root)` + 常量 `W_INTEGRATION_DORMANT_PATH`（coverage.py），从 plan 声明 entrypoint（critical_entrypoints / critical_flows[].entrypoints，复用 `_normalize_entrypoint` 支持 `::symbol`）做 seed，在 plan_scope 生产模块上构建 call-edge（import+call）+ activation-edge（import + 被导模块 import-time 自注册）有向图求可达闭包；per claimed module 判定「已 wired（被其它生产模块 import 且 call 或自注册）但从任一 entrypoint 不可达」→ warning。opt-in：未声明 entrypoint 时禁用，既有行为不变
- changed_paths: src/cccc/ralph/validation_rules/coverage.py, src/cccc/ralph/validation_rules/__init__.py, src/cccc/ralph/validator.py, tests/ralph/test_active_path_reachability.py
- active_entrypoint: CLI `ralph validate <plan>` → `validate_with_project(plan, project_root)` → `_collect_structural_issues` → `_check_active_path_reachability`（紧随 `_check_integration_call_evidence`，validator.py:267）
- active_path_trace: 声明 entrypoint → seed 生产模块 → call/activation 边闭包求 reachable → integration task 每个 claimed module：wired-but-unreachable → emit W_INTEGRATION_DORMANT_PATH（evidence 含 claimed_module / declared_entrypoints / reachable_modules）
- runtime_conditions: plan 声明 ≥1 个落在 plan_scope 内的生产 entrypoint（opt-in）
- verification_commands: 真实 CLI `ralph validate <tmp>/plan.yaml`（非 git 临时项目）；python -m pytest tests/ralph/test_active_path_reachability.py tests/ralph/test_integration_call_evidence.py tests/ralph/test_integration_call_patterns.py -v
- expected_behavior: 休眠 fixture（claimed 模块仅被不可达模块 import+call）→ CLI 输出含 W_INTEGRATION_DORMANT_PATH；可达 fixture（main→orchestrator→target）→ 不含；自注册被可达模块 import（activation-edge）→ 不含；自注册但无人 import → 不含（never-wired）；opt-in 无 entrypoint → 不含；`::symbol` entrypoint → 仍识别
- observed_behavior: 原始症状已消失、行为已确认——**双独立验证**：(1) 我方真实 `ralph validate` CLI 于非 git 临时项目：dormant 告警、reachable 不告警、opt-in 不启用、Codex 缺陷场景（自注册无 import）修复后不误报、dormant（import+call 不可达）仍告警；(2) Codex 独立对抗复核（全新临时 fixture×6，validate_with_project + 真实 CLI 双轨）verdict=works、prior_defect_fixed=True、cli_warning_behaves_correctly=True、real_defects=[]。targeted 17 passed；全仓 3751 passed / 120 skipped
- fallback_behavior: 不引入运行时 fallback（纯 validate 检测规则）。warning 且默认可 suppress（未入 _NON_SUPPRESSIBLE_ALWAYS）——「能检测」≠「能封堵」，强制门升级待误报率验证（DG-14）
- known_limitations: 模块级语法启发式——(i) 可达文件死分支/未调用函数内的 call 仍连边 → 可能漏报（保守不误伤）；(ii) 动态 importlib/getattr、`from x import *` 星号导入、package __init__ 相对导入 / re-export → 可能误判可达性。均记入 DG-14，本批不修
- codex_findings_adoption: step-3 设计评审 5 finding——blocker（self-wiring 误报）ACCEPT→activation-edge；major（per-task 去重不成立）ACCEPT→per-module；major（__init__ 相对导入盲点）DEFER→DG-14；major（过/欠近似）ACCEPT 收窄定位 + DEFER→DG-14；minor（`::symbol` 语义）ACCEPT。独立复核 major（自注册无 import 误报）ACCEPT→wired 改为「须被其它模块 import」+ 回归 test_self_wiring_without_import_not_dormant；star-import miss = DG-14 已声明限制（已列「星号导入」），不计新缺陷
- evidence_locations: tests/ralph/test_active_path_reachability.py（8 场景，走 validate_with_project 公共入口）；.ralph-flow/step-3-review/dg1-design.json（设计评审 verdict=incomplete 已采纳）；.ralph-flow/step-5-execute/T1.json（实现）；.ralph-flow/step-5-execute/T1-independent-verify.json（Codex 独立对抗，发现 major 误报）；.ralph-flow/step-5-execute/T1-reverify.json（Codex 复核 verdict=works real_defects=[]）
- regression_test: python -m pytest tests/ralph/test_integration_call_evidence.py tests/ralph/test_integration_call_patterns.py（既有规则不回归）；全仓 3751 passed / 120 skipped
- archive_decision: behavior-verified（真实 `ralph validate` CLI 主路径双独立验证，模块级 dormant-path 检测在活跃 validate 路径翻转 pass/fail；FL-66/RV-48 部分覆盖，函数级/动态导入剩余盲点 → DG-14）

---

## 代码修复归档（2026-06-07）— v60 第一阶段收尾：AF-07 异步重构 + AF-08 主路径接入（behavior-verified）

> 来源：plan.yaml AF-07 批次（T1~T6 真异步 suspend-until-terminal）+ 2 修复（线程生命周期/超时、orchestrator <2700 抽 AFDispatchMixin）+ AF-08（初始提交 AF 路由）。
> 经 solve flow（6/6 步通过）+ Codex 设计评审（F1/F3/F4 ACCEPT、F2 ACCEPT-core）+ **双独立 live 主路径验证**（我方 in-process 真实代码链 + Codex 对抗性独立脚本）。
> 全量套件 3739 passed / 120 skipped / 0 failed。Codex 独立验证两轮：首轮发现 AF-08 主路径绕过（已修），复验 verdict=works 6/6。
> 新发现 AF-09（AF compile 丢 task.type → 选错 worker model，独立于死循环，留短版跟踪）。

| ID | 标题 | 状态 | 归档原因 |
|----|------|------|---------|
| AF-07 | AF 引擎 fire-and-forget 死循环 → 真异步 suspend-until-terminal | behavior-verified | live 9/9×4：无瞬时合成完成、无死循环风暴、真实 terminal 单次完成；Codex verdict=works |
| AF-08 | plan 初始提交 register_and_suggest 绕过 AF → 接入 AF wrapper | behavior-verified | live 7/7（此前 4/7）：_try_af_execution=1、非 legacy prompt；无 transport 回归 legacy；Codex 复验 6/6 |

**AF-07 evidence bundle**
- issue_id: AF-07
- original_symptom: AF 引擎 fire-and-forget——ActorGatewayBridge.send_task 后毫秒级合成 task_completed，节点秒级 completed，验证失败→foreman override→重派→又走 AF→死循环（v59 实测 T4~T9 毫秒级假完成）
- claimed_fix: 真异步 suspend-until-terminal——废除 auto_complete_after_send（默认 False，无合成完成）；runner 挂起轮询等真实 worker terminal；attempt_id 端到端贯通 IPC/ops（completed+failed）；apply_task_event 按 attempt_id 精确桥接 + 旧 attempt 不唤醒新 + 移除 AF 回灌（验证门只跑一次）；caller 线程登记防丢唤醒(F1) + (wf,node,attempt) 去重 + per-task max-attempt 熔断(F3) + 严格 fail-closed + runtime readiness 强化 + 后台线程 cooperative cancel/conftest join + 超时 0.25→1800s(env 可调)
- changed_paths: src/cccc/daemon/foreman/af_gateway_bridge.py, src/cccc/agentflow/actor_runner.py, src/cccc/daemon/ralph_ipc_handler.py, src/cccc/daemon/ops/workflow_task_ops.py, src/cccc/daemon/foreman/workflow_orchestrator.py, src/cccc/daemon/foreman/af_dispatch_mixin.py, tests/conftest.py
- active_entrypoint: orchestrator.process_batch_suggestion（DAG auto-advance / process_pending / batch_suggest auto_process）→ _try_af_execution → AFExecutionEngine.execute_bundle → CCCCActorRunner.execute；真实 terminal 经 handle_ralph_task_event → apply_task_event → _bridge_af_terminal_event
- active_path_trace: try_af_execution(caller 线程登记 active_gateway/inflight) → 后台线程 execute_bundle → runner 挂起 poll_terminal；worker terminal → handle_ralph_task_event → complete_task(attempt_id) → apply_task_event → 验证门 + record_terminal(attempt_id) → runner 唤醒 → "[af] execution done"
- runtime_conditions: CCCC_AF_ENGINE_ENABLED 默认启用 + AF runtime ready（transport + pool.acquire 可用）
- verification_commands: python /tmp/af07_live_check.py（真实 group+orchestrator+handle_ralph_task_event IPC ingress）；python -m pytest tests/agentflow/test_af_async_terminal_integration.py -v
- expected_behavior: engine=af；无瞬时合成完成（task 停 ASSIGNED）；terminal 扣留时无死循环重派风暴；真实 terminal 唤醒挂起 runner、恰好一次过验证门完成；无静默 legacy fallback
- observed_behavior: 原始症状已消失、行为已确认——live 9/9 稳定 ×4：execution_engine_tag=af、status_after_dispatch=ASSIGNED（非秒完成）、sends 1→1（无风暴）、真实 worker terminal 经真实 apply_task_event 唤醒挂起 runner、final_status=COMPLETED 单次过门、gateway ~0.11s 清理、无 af_fallback 事件；Codex 独立对抗脚本 verdict=works
- fallback_behavior: AF 不可用非严格→显式 fallback（on_fallback 一次 + ledger af_fallback，无静默）；严格(CCCC_AF_STRICT)→fail-closed（af.execution_unavailable，不降级 legacy）；后台线程 module 级 cooperative cancel + tests/conftest.py hookwrapper join af-exec-* 杜绝泄漏
- evidence_locations: tests/agentflow/test_af_async_terminal_integration.py / test_gateway_bridge_terminal.py / test_actor_runner_suspend.py / test_apply_event_terminal_bridge.py / test_af_dispatch_guard.py；.ralph-flow/step-5-execute/AF07-independent-verification.json + AF0708-reverify.json；/tmp/af07_live_check.py
- regression_test: python -m pytest tests/agentflow/ tests/test_foreman_workflow.py tests/test_af_fallback_observability.py（全仓 3739 passed）
- archive_decision: behavior-verified（真实主路径 live 双独立验证，v59 死循环消除）

**AF-08 evidence bundle**
- issue_id: AF-08
- original_symptom: plan 驱动初始提交（CLI op ralph_register_and_suggest）→ orchestrator.register_and_suggest → register_and_suggest_inner → _submit_ready_suggestion → AssignmentController.process_batch_suggestion（legacy _start_assigned_agents）→ **完全绕过 AF**，_try_af_execution=0、发 [Foreman Assignment]，AF 仅再派发帧生效
- claimed_fix: WorkflowOrchestrator.process_batch_suggestion 新增 kw-only allowed_existing_task_ids 并透传 controller；assignment_batches._submit_ready_suggestion 改走 self._owner.process_batch_suggestion（AF wrapper）；wrapper 的 _should_run_af_execution 门保证 runtime 未就绪时仍走 controller legacy（最小爆破面）
- changed_paths: src/cccc/daemon/foreman/workflow_orchestrator.py, src/cccc/daemon/foreman/assignment_batches.py
- active_entrypoint: handle_ralph_register_and_suggest(auto_process=True, auto_start_agents=True) → orchestrator.register_and_suggest → register_and_suggest_inner → _submit_ready_suggestion → orchestrator.process_batch_suggestion（AF wrapper）
- active_path_trace: _submit_ready_suggestion → self._owner.process_batch_suggestion → _should_run_af_execution(ready=True) → controller.process_batch_suggestion(auto_start_agents=False) 注册 + _try_af_execution 派发
- runtime_conditions: AF enabled + runtime ready + plan_path 提交（op ralph_register_and_suggest，auto_process=True 为 CLI/web 默认）
- verification_commands: python /tmp/af07_ipc_path_check.py（真实 handle_ralph_register_and_suggest IPC 提交）；python -m pytest tests/agentflow/test_af08_initial_submit_routing.py -v
- expected_behavior: register_and_suggest(auto_process=True) 经 AF wrapper、_try_af_execution 被调用、非 legacy [Foreman Assignment] prompt、无瞬时完成；无 transport（runtime not ready）时仍 legacy
- observed_behavior: 原始症状已消失、行为已确认——live 7/7（此前 4/7）：_try_af_execution calls=1、legacy_prompt_seen=False、status=ASSIGNED、sends 1→1、真实 terminal 单次 COMPLETED；无 transport→runtime not ready→legacy（回归保持）；Codex 独立复验 verdict=works 6/6
- fallback_behavior: AF runtime not ready → AF wrapper 经 _should_run_af_execution 走 controller legacy（优雅降级，旧行为不回归）
- evidence_locations: tests/agentflow/test_af08_initial_submit_routing.py；.ralph-flow/step-5-execute/AF0708-reverify.json；/tmp/af07_ipc_path_check.py
- regression_test: python -m pytest tests/agentflow/test_af08_initial_submit_routing.py tests/ -q（3739 passed / 0 failed）
- archive_decision: behavior-verified（真实 IPC 主提交路径 live 双独立验证）

---

## 代码修复归档（2026-06-07）— v60 第一阶段收尾续：AF-09 模型选择保真（behavior-verified）

> 来源：plan.yaml AF-09 批次（T1：task_ref_to_plan_task 白名单补 type）。
> 经 solve flow（6/6 步通过）+ Codex 设计评审（verdict=adjust，已采纳：scope 收窄 + 测试改到运行时选型层 + 真实链路负向复现）。
> 负向复现确认：删白名单 type → 4/4 测试 fail；补回 → 4/4 pass（真实链路翻转，非死规则）。关联回归 99 passed，step-5 flow auto-verify 全仓套件通过。
> 衍生检测能力缺口 DG-12（AF adapter 字段 parity）/ DG-13（双引擎选型 parity）已记入短版 DG 规则族，通用规则待后续。

| ID | 标题 | 状态 | 归档原因 |
|----|------|------|---------|
| AF-09 | AF compile 丢 task.type → 选错 worker model（降级 general） | behavior-verified | 4/4 真实链路测试 pass；负向复现 4/4 fail；resolve_model_for_task 层断言 AF 与控制面选同一 model_key 且 != general fallback |

**AF-09 evidence bundle**
- issue_id: AF-09
- original_symptom: af_gateway_bridge.task_ref_to_plan_task 字段白名单不含 "type" → AF 编译丢 TaskRef.type → PlanCompiler._build_task_ref 回落 DEFAULT_TASK_TYPE="general" → agent_pool 按 task.type 选 worker 降级（实测 AF 选 codex-general-worker，控制面 legacy assignment 对同一 backend task 选 codex-backend-worker）
- claimed_fix: task_ref_to_plan_task 字段元组加入 "type"（唯一断点，保留既有 model_dump(exclude_none=True)/is not None 过滤逻辑不变；consumer 侧 PlanCompiler/agent_pool 已消费 task.type，未改）
- changed_paths: src/cccc/daemon/foreman/af_gateway_bridge.py, tests/agentflow/test_af_node_task_type.py
- active_entrypoint: AF 派发 — try_af_execution → task_ref_to_plan_task → PlanCompiler.compile → CCCCActorRunner._build_acquire_request(task=cccc_meta.task) → AgentPoolManager.acquire/resolve_model_for_task(task.type)
- active_path_trace: TaskRef(type="backend") → task_ref_to_plan_task（输出含 type）→ PlanCompiler._build_task_ref(type="backend"，非 general 回落) → bundle.cccc_meta[id].task.type=="backend" → resolve_model_for_task 读 task.type=="backend" → select_model_for_task 选 backend worker model
- runtime_conditions: AF compile 路径（CCCC_AF_ENGINE_ENABLED）+ task.type 为非 general（backend/frontend）
- verification_commands: python -m pytest tests/agentflow/test_af_node_task_type.py -v
- expected_behavior: task_ref_to_plan_task 输出 dict 含 type；AF node bundle.cccc_meta[id].task.type=="backend"（非 general）；受控 registry(backend≠general) 下 resolve_model_for_task 对 AF 节点 task 与控制面 TaskRef 选同一 model_key 且 != general fallback
- verified_scope: 已验证范围 = AF compile→新建 agent 选型路径（task_ref_to_plan_task→compile→_build_acquire_request→acquire/resolve_model_for_task）。AF/control-plane 更广 parity（suggestion 兑现 + reuse 旁路）不在本 scope，见 fallback_behavior + DG-13
- observed_behavior: 原始症状已消失、行为已确认——**双独立核验**：(1) 我方 live 真实函数链路 /tmp/af09_live_check.py ALL PASS，_generate_agent_id(af_task.type)=="codex-backend-worker"（原症状 codex-general-worker 已消失），af_key==cp_key=="backend-model"!=gen_key=="general-model"；(2) Codex 独立对抗脚本复现 acquire_lease.agent_id=="codex-backend-worker"/model_id=="backend-model-id"，负例删 type→compiled_type=="general"。targeted 4/4 passed；负向复现（删白名单 type）4/4 fail（真实链路翻转，非死规则）；关联回归 99 passed、tests/agentflow+test_foreman_workflow 197 passed；step-5 flow auto-verify 全仓套件通过
- fallback_behavior: 不引入新 fallback。Codex 独立核验 verdict=incomplete 仅针对 AF-09 未声称的更广 parity，复现两个 AF-09 范围外的既有旁路（即便 type 已修仍存在）：①suggestion_gap——AF runner 不消费 control-plane 已算 preferred_model_key/task_model_suggestions；②group-peer reuse——_find_group_peer_agent 复用分支不经 resolve_model_for_task，backend 任务复用 peer 时仍可拿 general 模型。二者均超出本批 scope（采纳 Codex 设计评审收窄建议），已记 tracker DG-13（检测能力 + 运行时行为缺口 + 已知局限），未修
- evidence_locations: tests/agentflow/test_af_node_task_type.py；/tmp/af09_live_check.py（我方 live 核验 ALL PASS）；.ralph-flow/step-3-review/af09-review.json（设计评审 verdict=adjust 已采纳）；.ralph-flow/step-5-execute/t1.json；.ralph-flow/step-5-execute/af09-independent-verify.json（Codex 独立对抗核验，verdict=incomplete 仅指 scope 外旁路）
- regression_test: python -m pytest tests/test_foreman_workflow.py tests/agentflow/test_engine_fallback.py tests/agentflow/test_plan_compiler.py tests/agentflow/test_plan_compiler_adapter.py -q（99 passed）；python -m pytest tests/agentflow tests/test_foreman_workflow.py -q（197 passed）
- archive_decision: behavior-verified（双独立核验确认 AF-09-scoped 原症状消失：真实 compile→新建 agent 选型链路 + 删字段负向复现 4/4 翻转；scope 外更广 parity 旁路另记 DG-13）

---

## 代码修复归档（2026-06-06）— v60 第二批：M0 归档纪律 + FL-75（behavior-verified）

> 来源：plan.yaml M0 批次（T1=MT1/M0-3、T2=MT2/M0-2+M0-1、T3=MT3/FL-75、T4=MT4/M0-4、T5=MT5/M0-5、T6=集成）。
> 经 solve flow（6/6 步通过）+ Codex review（11 findings 全采纳）+ 双重真实主路径验证（我 + Codex 对抗性，无 no-op/无回归）。
> 全量套件 916 passed（tests/ralph）/ 3703 passed（全仓）。Codex 对抗性验证确认 5 项均非死规则，仅存静态文本博弈面（见下「遗留局限」）。

| ID | 标题 | 状态 | 归档原因 |
|----|------|------|---------|
| M0-3 | 3 个集成/行为 warning 无条件不可抑制 | behavior-verified | `ralph validate` CLI 实证：加入 suppress 仍不降级 |
| M0-2 | evidence bundle 4→14 字段，按行 field:value 解析、值非空 | behavior-verified | 真实 `**ID evidence bundle**` 格式命中（死规则已修），缺字段拦 |
| M0-1 | archive_decision 状态分类门 | behavior-verified | implemented 等不可归档状态被拦 |
| M0-4 | false-completion-quarantine 隔离域 | behavior-verified | id→domain 映射 + 负向 observed 反例拦截 |
| M0-5 | 连续 2 轮 deferral→escalated→_check_plan 阻断 | behavior-verified | 真实 begin_round 两轮升级 + _check_plan 阻断，跳轮重置/clear 重启 |
| FL-75 | solve flow step-4 归档检查 advisory→blocking | behavior-verified | 真实 solve step-4 check_fn 在删除线短版上 result.passed=False |

**MT1 evidence bundle**
- issue_id: MT1
- original_symptom: W_VERIFICATION_BEHAVIOR_MISMATCH 等 3 个集成/行为 warning 可被 plan 作者写入 suppress_codes 豁免，掩盖主干逻辑缺乏生产调用测试
- claimed_fix: security.py 新增 _NON_SUPPRESSIBLE_ALWAYS（3 个 code），_non_suppressible_codes(plan) 无条件并入
- changed_paths: src/cccc/ralph/validation_rules/security.py
- active_entrypoint: ralph validate <plan>（CLI）→ validator._apply_suppression(non_suppressible_codes=_non_suppressible_codes(plan))
- active_path_trace: validate → _apply_suppression → suppress_set.difference_update(non_suppressible) → 3 个 code 被剔出可抑制集
- runtime_conditions: plan 触发该 warning 且 suppress_codes 含该 code（无论是否安全关键流）
- verification_commands: ralph validate /tmp/plan_bm.yaml（suppress W_VERIFICATION_BEHAVIOR_MISMATCH）
- expected_behavior: 该 warning 仍列于 Warnings 段，不出现 [suppressed] 降级
- observed_behavior: 原始症状已消失、行为已确认——CLI 实测 suppress_codes 含该 code 时仍无法豁免（Warnings 段保留 W_VERIFICATION_BEHAVIOR_MISMATCH、无 [suppressed] 降级）；非 always code 抑制不变（对照）
- fallback_behavior: 安全关键流时与 _NON_SUPPRESSIBLE_WHEN_SECURITY 取并集，不丢失既有安全不可抑制集
- evidence_locations: tests/ralph/test_non_suppressible_always.py（3 个 code 各一条 validate 真实链）；CLI 输出实测
- regression_test: python -m pytest tests/ralph/test_non_suppressible_always.py
- archive_decision: behavior-verified（ralph validate 主路径 CLI 行为已确认）

**MT2 evidence bundle**
- issue_id: MT2
- original_symptom: evidence bundle 只校验 4 字段且用整段 substring 包含；段落定位器只匹配 `#### ID`，但真实 full tracker 是 `**ID evidence bundle**` → 检查在真实数据上静默失效（死规则）
- claimed_fix: 必填字段扩到 14；按行解析 field:value（值非空）；locator 支持 `#### ID` 与 `**ID evidence bundle**`；新增 _ARCHIVABLE_STATUSES 状态门（archive_decision 本行）
- changed_paths: src/cccc/ralph/flow_improvement_check.py
- active_entrypoint: E2E flow step-6 _check_improvement_register / solve flow step-4（经 FL-75）
- active_path_trace: _check_improvement_register → _check_archive_evidence_bundle → _full_tracker_archive_paragraph(双格式) → 按行字段解析 + 状态门
- runtime_conditions: 短版出现新归档完成项，full tracker 含对应段落
- verification_commands: python -m pytest tests/ralph/test_archive_evidence_bundle.py tests/ralph/test_archive_status_taxonomy.py -v
- expected_behavior: 14 字段齐全 + 合法状态→过；缺字段/空值→列缺失 fail；状态 implemented→archive status fail；真实 `**ID evidence bundle**` 格式命中
- observed_behavior: full13 真实格式 PASS；缺 fallback_behavior/regression_test→FAIL 列缺失；implemented→FAIL "archive status must include one of [...]" ✅
- fallback_behavior: locator 在两种段落标题间正确截断；非归档 ID 不触发
- evidence_locations: tests/ralph/test_archive_status_taxonomy.py（含真实格式 + 空值 + 非法状态端到端）
- regression_test: python -m pytest tests/ralph/test_archive_evidence_bundle.py tests/ralph/test_archive_status_taxonomy.py
- archive_decision: behavior-verified（真实 `_check_improvement_register` 链路确认，含真实 tracker 格式样本）

**MT4 evidence bundle**
- issue_id: MT4
- original_symptom: AF/模型选择/评价闭环/WORKFLOW_EVALUATION/suppress 等反复假完成域，归档时仅靠关键词 + 词袋行为证据，可省略词绕过、泛词误伤、负向反例放行
- claimed_fix: _QUARANTINE_DOMAINS 注册表 + _is_quarantined（id→domain 映射优先，关键词补充）；隔离项强制 14 字段 + behavior-verified/fail-closed 状态 + observed 正向证据且负向 token（规范化多组同义词表）直接 fail
- changed_paths: src/cccc/ralph/flow_improvement_check.py
- active_entrypoint: _check_improvement_register → _check_archive_evidence_bundle（隔离项分支）
- active_path_trace: 归档 ID → _is_quarantined(id,paragraph) 命中 domain → 叠加全字段 + 状态 + observed 正反向判定
- runtime_conditions: 归档项属隔离域（id 映射或关键词命中）
- verification_commands: python -m pytest tests/ralph/test_false_completion_quarantine.py -v
- expected_behavior: 隔离项 4 字段→fail(quarantine+domain)；archived 状态→fail；observed 含 仍/依旧 复现→fail；普通项不误判
- observed_behavior: 原始症状已消失、行为已确认——is_quarantined("AF-9")→"af_engine"（无关键词亦识别）；隔离项仅 4 字段被拦（quarantine af_engine）；observed 含负向同义表达的样本被正确拒绝（加固后扩同义词表）
- fallback_behavior: 非隔离项走 MT2 标准路径不变；泛词（普通 FL 段落含 rating 文本）不被误判
- evidence_locations: tests/ralph/test_false_completion_quarantine.py（含 id 映射、负向同义词、泛词误判对照）
- regression_test: python -m pytest tests/ralph/test_false_completion_quarantine.py
- archive_decision: behavior-verified（真实 archive check + 加固后同义词回归）

**MT5 evidence bundle**
- issue_id: MT5
- original_symptom: 问题被连续标记"不在本次范围/已知局限"无升级机制；M0-5 要求连续 2 轮 defer→P0-Blocker→冻结新 plan
- claimed_fix: 新建 deferral_ledger.py（streak_count/last_deferred_version/cleared_version，begin_round 按轮结算、跳轮 reset、clear 重启）；_check_plan 叠加 deferral P0 blocker 门；_check_gap_record 解析"已知局限/不在本次范围"区按轮自动落账（生产写入点）
- changed_paths: src/cccc/ralph/deferral_ledger.py, src/cccc/ralph/flow_engine.py
- active_entrypoint: solve flow step-2 _check_plan（阻断）+ step-4 _check_gap_record（写入点）
- active_path_trace: 写：_check_gap_record→begin_round(默认 ledger 路径)；读：_check_plan→escalated_blockers(同一默认路径, evidence_fn 复用 MT2 evidence-bundle 判定)
- runtime_conditions: 提供 version（state.version/params）；ledger 缺失视为无 blocker（fail-open，见局限）
- verification_commands: python -m pytest tests/ralph/test_deferral_ledger.py -v
- expected_behavior: 连续两轮 escalated；跳轮不升级；clear 后重启；_check_plan 在未清 escalated 时 passed=False
- observed_behavior: 真实 begin_round v1/v2→escalated=['ZZ-1']；跳轮→[]；clear 重启→[]；_check_plan→passed=False "escalated deferrals missing evidence bundle: ZZ-1"；写/读端同一默认 ledger 路径 ✅
- fallback_behavior: ledger 不存在→escalated_blockers 返回 []（fail-open）；无 version→写入 no-op
- evidence_locations: tests/ralph/test_deferral_ledger.py（含真实 _check_gap_record→ledger→_check_plan 链）
- regression_test: python -m pytest tests/ralph/test_deferral_ledger.py
- archive_decision: behavior-verified（真实写入/读取链 + _check_plan 主路径阻断确认）

**FL-75 evidence bundle**
- issue_id: FL-75
- original_symptom: solve flow 对清单归档约束不足——step-4 归档检查全为 advisory 不阻断；删除线/已完成摘要/未归档项可留存短版
- claimed_fix: _check_gap_record 新增三个 blocking 子检查（strikethrough/completed-summaries/archive-blocking）计入 base_passed，对齐 E2E step-6；函数体内延迟 import 解 flow_improvement_check↔flow_engine 双向顶层循环
- changed_paths: src/cccc/ralph/flow_engine.py
- active_entrypoint: ralph flow next（solve flow step-4 gaps）→ _check_gap_record
- active_path_trace: ralph flow next → _run_step_check(step4) → _check_gap_record → 延迟 import flow_improvement_check 三个子检查 → base_passed
- runtime_conditions: solve flow，--tracker 提供
- verification_commands: 真实 solve flow step-4 check_fn on 含 ~~ID~~ 删除线短版（/tmp/fl75_test）
- expected_behavior: 短版 body 含删除线/完成摘要/未归档完成项→result.passed=False；干净短版通过
- observed_behavior: 实测 result.passed=False，"short tracker contains strikethrough items: ['AB-2'] — move to full tracker"；既有 test_archive_content_check_fail 口径已翻转 ✅
- fallback_behavior: _tracker_body_lines 只扫 `---` 之后 body，header 历史完成摘要不误伤
- evidence_locations: tests/ralph/test_solve_flow_archive_blocking.py；tests/ralph/test_flow_engine.py::test_archive_content_check_fail（翻转）
- regression_test: python -m pytest tests/ralph/test_solve_flow_archive_blocking.py tests/ralph/test_flow_engine.py
- archive_decision: behavior-verified（真实 solve step-4 check_fn 主路径阻断确认）

> **新发现检测能力缺口**（已记入短版 DG-5/6/7）：规则定位器与真实数据格式漂移（死规则）、阻断门无生产写入点（休眠门，DG-1 镜像）、substring vs 字段值解析（填词绕过）。本批修复具体实例，通用检测规则待后续。
> **遗留局限**（Codex 对抗性验证确认，属静态文本博弈上限，同 RV-51/59）：(1) `**ID evidence bundle**` locator 接受非真实归档区的注入文本（需完整 14 字段 + 合法状态才过，门槛已显著抬高但非不可绕过）；(2) quarantine 负向 token 虽已扩同义词表仍非穷尽；(3) M0-5 _check_plan 门只冻结 solve flow plan step，不拦直接编辑 plan.yaml / 独立 ralph validate，ledger 缺失为 fail-open。

---

## 代码修复归档（2026-06-06）— v60 FC 批次 Phase 1：FC-1 / FC-2（behavior-verified）

> 来源：plan.yaml FC 批次第一阶段（T1=FC-1 / T2=FC-2）+ 本轮 Codex review 修复（F1 复用路径 enabled gate / F2 create_agent 默认）。
> 经 solve flow（6/6 步通过）+ Layer-6 行为证据 + 反事实因果验证。全量套件 3669 passed, 0 failed。

| ID | 标题 | 状态 | 归档原因 |
|----|------|------|---------|
| FC-1 | agent_pool 默认执行 runtime claude→codex（legacy 主链 + 全部兜底点） | behavior-verified | 主路径行为已确认改变，反事实证因果，负向 grep 清零 |
| FC-2 | select_model_for_task 过滤 enabled=false（+ 复用路径 F1 闭合） | behavior-verified | disabled 模型选择/复用两路径均已排除，回归锁定 |

**FC-1 evidence bundle**
- issue_id: FC-1
- original_symptom: 默认执行 runtime 兜底为 claude；v58 实跑 legacy 主链时 worker 仍起 claude
- claimed_fix: `_acquire_auto_agent`/`create_agent_for_task` 兜底 `or "codex"`；`assignment_actor_registration` 兜底 `or "codex"`；`create_agent` helper 默认 codex（F2）
- changed_paths: src/cccc/daemon/foreman/agent_pool.py, src/cccc/daemon/foreman/assignment_actor_registration.py, src/cccc/daemon/ops/agent_ops.py
- active_entrypoint: process_batch_suggestion(auto_start_agents=True)（AF 不就绪时回退 legacy 主链 = v58 事实路径）
- active_path_trace: process_batch_suggestion → create_or_reuse_agent → create_agent_for_task → resolve_model_for_task → actor_add(runtime)
- runtime_conditions: registry model.runtime 为空时兜底；显式 runtime 优先不被覆盖
- verification_commands: `python -m pytest tests/test_agent_pool_default_runtime.py -v`
- expected_behavior: 空→codex；claude→claude；codex→codex；legacy 主链 actor_add runtime=codex
- observed_behavior: 原始症状已消失、行为已确认——空→'codex'、claude→'claude'、codex→'codex'；Layer-6 集成测试 actor_add runtime='codex' ✅
- fallback_behavior: 仅空值兜底 codex，显式值穿透（反事实：源码翻回 `or "claude"` → 行为立即变 'claude'，恢复后回 'codex'，证因果）
- evidence_locations: `test_process_batch_suggestion_legacy_path_defaults_runtime_to_codex`；`grep -rn 'or "claude"' src/` 已无执行兜底
- regression_test: `python -m pytest tests/test_agent_pool_default_runtime.py`
- archive_decision: behavior-verified（主路径行为已确认）+ 反事实证因果 + 负向 grep 清零

**FC-2 evidence bundle**
- issue_id: FC-2
- original_symptom: disabled 模型仍可被选；复用打分路径未过滤 enabled（Codex F1 发现）
- claimed_fix: `select_model_for_task` `if not model.enabled: continue`（锁定）；`evaluate_for_task` 复用路径增加 enabled gate（F1）
- changed_paths: src/cccc/daemon/ops/agent_ops.py, src/cccc/daemon/foreman/agent_pool.py
- active_entrypoint: select_model_for_task / find_best_agent → evaluate_for_task
- active_path_trace: create_or_reuse_agent → find_best_agent → evaluate_for_task →（绑定 disabled 模型的 agent 被排除）
- runtime_conditions: registry 含 enabled=false 模型；agent YAML enabled 但绑定模型已禁用
- verification_commands: `python -m pytest tests/test_select_model_enabled_filter.py -v`
- expected_behavior: disabled 高分模型不选；全 disabled→None；复用路径排除 disabled-bound agent
- observed_behavior: 原始症状已消失、行为已确认——选 'codex-safe'；全 disabled→None；候选集 {enabled-bound}，复用 'enabled-bound' ✅
- fallback_behavior: registry 中不存在的模型（unknown）不被排除，仅显式 enabled=false 排除
- evidence_locations: tests/test_select_model_enabled_filter.py（含 reuse-path 回归）
- regression_test: `python -m pytest tests/test_select_model_enabled_filter.py`
- archive_decision: behavior-verified；Codex review 复用路径盲区（F1）已闭合

> **关联开放项**：M2-B 的「数据修正：codex 覆盖执行类 task type」「enabled 过滤」两子点由本批满足并归档；M2-B 其余子点（读端闭合 / rating 消费 / override 留痕 / E2E 验证）仍开放，保留短版跟踪。
> **遗留检测缺口**：`ralph validate` 仍无法检测「兜底默认散落未同步」与「过滤不变量跨消费端缺失」——见短版 DG-2 实证。修复已落地但**检测规则未补**。
> **未达层级**：当前为 behavior-verified（主路径行为确认），尚未做活体 daemon + 真实 codex worker 进程级 E2E（runtime-ready 的最后一环）。

---

## v51 归档：RV-15/16/17/33 已解决或已知局限（2026-05-31）

| ID | 标题 | 归档原因 |
|----|------|---------|
| RV-15 | validate 不检测 plan 引用的函数名与代码不匹配 | ✅ v48 确认已实现（`_check_goal_symbol_in_claimed_paths`）|
| RV-16 | validate 不检测 assignment-map 绕过 agent_pool | ✅ v48 确认已解决（guide 640-659 已说明 assignment-map 绕过效应）|
| RV-17 | validate 不检测跨层返回值类型压缩导致信息丢失 | 已知局限：语义级检查超出结构验证范围 |
| RV-33 | 弱加密语义不可结构检测 | 已知局限：validate/test 无法区分 Base64 混淆与真实加密 |

---

## v48 E2E 归档：FL-45/FL-33/FL-20-21 已验证（2026-05-30，FastAPI RBAC 任务协作平台）

v48 E2E 验证了 v48 solve flow 代码修复。综合 3.5/5（结果 3.5/5，过程 3.0/5，体验 4.0/5）。报告：[e2e-实战评估报告-v48.md](./e2e-实战评估报告-v48.md)。

| ID | 标题 | v48 验证结果 |
|----|------|-------------|
| FL-45 | Foreman 仅创建执行者角色 | ✅ **修复已生效**：安全敏感 RBAC/JWT 关键流下 foreman 主动创建非执行者 `sec-reviewer`（Security Reviewer）角色，actor 列表实测确认，不再是 v47 的 executor-only team。|
| FL-33 | Codex review 前 secret 预检 | ✅ **修复已生效**：step-4 `_check_codex_review` 含 `secret_preflight`，未配置 `CODEX_BRIDGE_SECRET` 直接 FAIL；应用层 `app/config.py:18-27` 亦无 JWT_SECRET 默认值（fail-closed）。|
| FL-20/21 | codex_bridge HMAC 签名链路 | ✅ **修复已生效**：两路 review JSON 均含 `_sig`，flow 校验 `valid HMAC signature` 通过，未签名/伪造 JSON 无法蒙混。|

**部分生效（衍生新发现，留短版跟踪）**：FL-46（validate 0 error 但运行代码 `POST /projects` 无角色门禁 → RV-22）、FL-47（默认顺序全绿但反序 `test_config`+`test_auth` 2 failed → FL-50）、UX-18（必需章节齐全但全占位符仍过闸 → UX-18b）。
**v48 E2E 新发现（短版跟踪）**：UX-18b/FL-48/FL-49/RV-22/FL-50/UX-19/FL-51。
**核心教训**：「ralph validate 0 error + flow 全 PASS」≠「实现正确 + 评估闭合」，结构校验需向实质内容（占位符检测、恢复留痕、reviewer 参与证据、乱序测试）延伸。

### v47 新发现条目归档（从短版迁入，2026-05-30）

> 以下 v47 E2E 发现经 v48 复验后从短版移出：FL-45 已修复、FL-44 转已知局限、FL-46/47/UX-18 部分生效（残留转 RV-22/FL-50/UX-18b）。原始 v47-instance 描述保留如下。

- **FL-44（challenge verification 对正确代码 false positive 率偏高）→ 已知局限**：T1/T2 代码实际正确（本地 pytest 通过），但 challenge verification 失败需 foreman override。T1 `config_env_guard` check 因 `exec()` 不触发模块级 Settings 实例化而误判；T2 challenge 理由"DB 配置与 User model 实现正确"却仍 FAIL。v48 判定与 `W_VERIFICATION_PYTHON_IMPORT_OPAQUE` 重叠，记为已知局限。
- **FL-45（Foreman 仍只创建执行者角色）→ ✅ 已修复（v48 验证）**：v46 修了 FL-41（guide 加多角色指引）但 v47 foreman 仍只建 2 执行者。v48 E2E 中 foreman 在 RBAC/JWT 安全敏感关键流下主动创建非执行者 sec-reviewer，修复生效。
- **FL-46（端点 RBAC 缺陷未被 plan/security test 检测）→ 部分，残留转 RV-22**：v47 `/api/users/search` 无认证暴露 email/role，forbidden_flows 未覆盖未认证端点暴露。v48 validate 仍不检测写端点授权覆盖（`POST /projects` 无门禁），残留转 RV-22。
- **FL-47（测试隔离问题未被系统发现）→ 部分，残留转 FL-50**：v47 test_routers.py 模块级共享状态致全量运行失败，verification 不跑该测试。v48 仍存在（reload 顺序依赖默认顺序全绿掩盖），残留转 FL-50（乱序/隔离验证）。
- **UX-18（WORKFLOW_EVALUATION.md 过简）→ 部分，残留转 UX-18b**：v47 仅 568B 纯统计。v48 flow 加了必需章节+size 闸门，但 header-only 占位符骨架仍过闸，残留转 UX-18b（占位符检测）。

---

## v42 E2E 归档：RO-108/RO-109/RO-110/RO-111/FL-27/FL-28 已验证（2026-05-24，FastAPI Blog Platform）

v42 E2E 验证了 v45 代码修复的 6 项 v41 发现。综合 4.3/5（结果 4.5/5，过程 4/5，体验 4.5/5）。

| ID | 标题 | v42 验证结果 |
|----|------|-------------|
| RO-108 | SSRF 防护未接入路由 | v42 项目无外部 URL endpoint，攻击面极低。Codex review 确认"未实现但无需" |
| RO-109 | SSRF 编码绕过 | 同 RO-108，无 SSRF 攻击面 |
| RO-110 | FTS5 中文搜索假通过 | v42 search.py 对 CJK 显式走 LIKE fallback，不假装 FTS5 能用。新问题 RO-112 跟踪 |
| RO-111 | search.py 静默降级 | v42 search.py 无 catch-all 降级，空结果来自显式空白查询分支。Codex review 确认 |
| FL-27 | 全部 verification_force_passed | v42 10/11 verification_passed + 1 foreman_override（T02 shallow_check_depth 误报）。显著改善 |
| FL-28 | Worker 未启动 | v42 双 worker（worker-1 + worker-2）真并行执行，各自完成 4+7 个任务。0 crash |

v42 新发现 5 项（RO-112/FL-29/FL-30/FL-31/RO-113）已登记到短版 tracker。

---

## 代码修复归档（2026-05-24 第三批，2 项）— HMAC 全链路打通

| ID | 标题 | 修复内容 |
|----|------|----------|
| FL-20 | E2E flow check 机制 HMAC 生效（P1） | HMAC 全链路：codex_bridge.py 输出时用 `_sign_result()` 添加 `_sig` 字段；flow_engine.py `_resolve_codex_bridge_secret()` 从环境变量或 `.env` 文件读取 secret；未签名 JSON 强制 FAIL（不再 skip） |
| FL-21 | CODEX_BRIDGE_SECRET 配置 + codex_bridge.py 签名（P1） | `.env` 中配置 secret；codex_bridge.py 添加 `_sign_result()` + `_load_secret_from_env_file()` 自动从 `--cd` 目录的 `.env` 读取 secret 并签名 |

---

## 代码修复归档（2026-05-24 第二批，4 项）

| ID | 标题 | 修复内容 |
|----|------|----------|
| FL-25 | step-5 check 手写 JSON 绕过防护——mtime 检测（P1） | `_check_codex_mtime_lag()` 检测 JSON mtime 异常晚于 step-5 目录创建时间（阈值 CODEX_EXECUTION_MAX_LAG_SECONDS=3600s），emit advisory warning |
| FL-26 | step-5 git diff 与 Codex changed_files 交叉验证（P2） | `_collect_codex_changed_files()` 提取 JSON 中 changed_files 字段，`_check_diff_source_correlation()` 验证 changed_files ⊆ git diff |
| FL-27 | codex_bridge.py 路径解析——flow instruction 动态注入完整路径 | `_resolve_codex_bridge()` 在 `~/.claude/skills/` 下搜索完整路径，`_build_solve_steps()` 动态生成 instruction 含完整路径。SOLVE_STEPS 从模块级常量改为函数调用 |
| — | E2E flow step-4 instruction 补充 codex_bridge.py 路径提示 | flow_steps_e2e.py step-4 instruction 增加完整路径提示 |

### 已知局限归档（2026-05-24，无需代码修复）

| ID | 标题 | 优先级 | 处理 |
|----|------|--------|------|
| RV-9 | validate 不检测 check 注册到错误的 validation phase | P3 | 已知局限——validate 不理解 check 的运行时依赖（需要文件系统 vs 纯结构） |
| RV-10 | validate 不检测 plan 描述的实现方案与现有代码功能重复 | P3 | 已知局限——语义级检查超出结构验证的合理范围 |
| RV-11 | validate 不检测 Codex changed_files 与 git diff 的集合方向性 | P3 | 已知局限——方向性逻辑语义超出结构验证范围 |

---

## 代码修复归档（2026-05-24 第一批，5 项）

| ID | 标题 | 修复内容 |
|----|------|----------|
| FL-23 | step-4 gap recording instruction 增加能力差距分析指导 + check 增强（P1） | instruction 重写为"Ralph 系统检测能力缺陷"定位 + 反例指导 + GAP_CAPABILITY_KEYWORDS 检查。`_check_gap_record()` 增加 capability keywords 检查 |
| FL-24 | step-5 instruction 禁止直接编辑（P2） | instruction 增加 "MUST use codex_bridge.py" + "Do NOT use Edit/Write" 明确禁止语句 |
| RV-6 | validate 检查 goal_behavior 中符号是否在 claimed_paths 中定义（P2） | `_check_goal_symbol_in_claimed_paths()` 实现，提取 backtick 符号做文件系统 grep，注册到 `validate_with_project()` |
| RV-7 | validate 检查 claimed_paths 是否为 goal 目标的真实控制层（P2） | 合并到 RV-6 实现——符号定义位置检查等价于控制层验证 |
| RV-8 | validate 检查 CJK 文本处理算法可行性提示（P3） | `_check_goal_cjk_tokenization_hint()` 实现，检测 tokenization 关键词 + CJK 上下文 → emit hint |

---

## 代码已修复，场景未触发归档（v41 修复，v42 未触发，2026-05-24 迁入）

以下 9 项在 v41 代码修复完成，v42 solve flow 中未触发对应场景。待后续 E2E 自然触发时验证。

### RO 系列

| ID | 标题 | 优先级 | 修复内容 | 验收标准 |
|----|------|--------|---------|---------|
| RO-104 | verify gate 无法检测 provides/consumes 合同漂移 | P1 | v41 代码已修复 | task consumes `scope_enforcement` 但代码未 import/调用 `require_scope` → verify gate 报 warning |
| RO-105 | verify gate 不检测 token type 混用（refresh 当 access） | P1 | v41 代码已修复 | plan 含 auth critical_flow 且 token 有多种 type → challenge mock_tests 自动包含 type confusion 测试 |
| RO-106 | temporal_pattern store_then_use 只查声明不查集成 | P2 | v41 代码已修复 | audit helper 存在但 entrypoint 未调用 → validate 报 W_TEMPORAL_PATTERN_NOT_INTEGRATED |
| RO-107 | foreman 自评数字不一致（总测试数与分项不匹配） | P2 | v41 代码已修复 | WORKFLOW_EVALUATION.md 中的总测试数与 `pytest --co -q` 输出一致 |

### RV 系列

| ID | 标题 | 优先级 | 修复内容 | 验收标准 |
|----|------|--------|---------|---------|
| RV-1 | validate 应检测 plan 中 task 职责重叠 | P2 | W_PROVIDES_NOT_CONSUMED 已实现 | task A provides X 但无 task consumes X → validate 报 W_PROVIDES_NOT_CONSUMED |
| RV-2 | validate 应检测 W_CROSS_BOUNDARY_WITHOUT_GLUE 误报 | P3 | covers.tasks 满足 glue 已实现 | verification task 声明 covers.tasks 包含跨边界 task → 不再误报 |

### UX 系列

| ID | 标题 | 优先级 | 修复内容 | 验收标准 |
|----|------|--------|---------|---------|
| UX-15 | 多 Worker 并行 dispatch | P3 | dispatch 日志增强 + max_concurrent 确认 >= 2 | E2E 实测观察实际并行度 |
| UX-16 | Actor PTY 进程异常退出零日志 + 不自动重启 | P1 | crash 日志 + 自动重启 + crash_limit | actor 异常退出 → WARNING 日志 + 30s 内重启；3 次后放弃 + 通知 foreman |
| UX-17 | Actor 进程退出时应保留 scrollback 用于诊断 | P2 | .last_output 保存已实现 | actor 退出后 .last_output 文件存在含最后输出 |

---

## v40 E2E 归档：RO-96/E2E-1/E2E-2/E2E-3 已验证（2026-05-19，Flask OAuth2 Resource Server）

> Foreman：Claude runtime | Workers：3x Claude runtime (worker-1, claude-general-worker, claude-general-worker-1)
> 综合评分：3.7/5（结果 3.5/5，过程 4/5，体验 3.5/5）
> 8 任务（setup → token mgmt/scope/audit 并行 → security/challenge/race → integration）
> 评估报告：[e2e-实战评估报告-v40.md](./e2e-实战评估报告-v40.md)

### 已验证归档

| ID | 标题 | 实测证据 |
|----|------|---------|
| RO-96 | attach 相对路径解析 bug（P0） | `cd /tmp/cccc-e2e-v40 && cccc attach .` → ledger scope url = `/private/tmp/cccc-e2e-v40`（绝对路径）✅。`group_cmds.py:26` 的 `Path(args.path).resolve()` 修复生效 |
| E2E-1 | 相对路径 attach 验证策略（P1） | v40 使用相对路径 attach，RO-96 验证通过 ✅ |
| E2E-2 | challenge mode 验证策略（P1） | T6 声明 `verification_mode: challenge`，4 个 mock_tests（forgery/escalation/revoked/expired）触发，27 个 adversarial tests 通过。Codex 评价 4/5 ✅ |
| E2E-3 | security recipe / temporal_pattern 验证策略（P2） | `token_store_then_use` 声明 `temporal_pattern: store_then_use`，worker 正确实现先 `db.session.commit()` 再返回 token ✅。**部分**：审计 flow 的 store-then-use 未集成（`log_token_event` 零调用） |

### v40 Codex 独立审查发现

| 严重度 | 发现 | 位置 |
|---|---|---|
| 严重 | refresh token 可直接访问资源 API（`verify_token` 不校验 `type==access`） | src/auth.py:55, :100 |
| 高 | 审计日志未接入真实 token 生命周期（`log_token_event` 零调用） | src/auth.py:19, :55, :84 |
| 高 | JSON array 输入导致 500 | src/security.py:31, :73 |
| 中 | scope 层级语义不一致 | src/permissions.py:5, src/resources.py:11 |
| 中 | 限流只作用于 `/api/*`，未使用 `RATE_LIMIT_AUTH` | src/security.py:49, :62 |
| 中 | race test 是并发后置检查，非真正 TOCTOU 窗口 | tests/test_race.py:90 |

### v40 新发现（共 10 项）

**来自 Codex 独立审查 → 系统改进项：**

| ID | 标题 | 优先级 | 来源 |
|----|------|--------|------|
| RO-104 | verify gate 无法检测 provides/consumes 合同漂移 | P1 | Codex process review：T3 provides `require_scope` 但 T2 用本地 `_has_scope`，合同未落地 |
| RO-105 | verify gate 不检测 token type 混用（refresh 当 access） | P1 | Codex results review：严重认证漏洞，challenge mode + 98% coverage 均未拦截 |
| RO-106 | temporal_pattern store_then_use 只查声明不查集成 | P2 | Codex results + process review：`log_token_event` 存在但零调用，运行时 AuditLog 计数 = 0 |
| RO-107 | foreman 自评数字不一致（总 tests vs 分项） | P2 | Codex process review：摘要 94 tests 与分项加总不符 |
| RV-1 | validate 应检测 task 职责重叠 | P2 | Codex process review：T2/T3 功能重叠，T3 产出未被消费 |
| RV-2 | covers.tasks 应满足 cross-boundary glue | P3 | Foreman 自评 negative feedback：11 个 false positive W_CROSS_BOUNDARY_WITHOUT_GLUE |
| RV-3 | race test TOCTOU 窗口验证深度不足 | P2 | Codex results review：test_race.py 是后置检查非真正 TOCTOU |

**来自 flow 执行体验：**

| ID | 标题 | 优先级 | 来源 |
|----|------|--------|------|
| FL-20 | E2E flow instruction 表述模糊 + check 机制不充分 | **P1** | 三类问题：(A) 路径表述不清致 4 步 retry；(B) step-5/6 未指导结合 Codex 反馈和 foreman 自评提取改进项，导致只产出打勾表；(C) check 只查文件存在/diff 有变更，不查内容是否引用 Codex 发现，形式正确但内容空洞也能 PASS |
| UX-16 | Actor PTY 进程异常退出零日志 + 不自动重启 | P1 | 4 次复现（lead x1, worker-1 x1, 两个 general-worker 各 x1） |
| UX-17 | Actor 进程退出时 scrollback 丢失无法诊断 | P2 | foreman 崩溃后无法追查 CLI 退出原因 |

### v40 关键洞察

1. **Challenge mode 首次实战验证成功**——机制正确触发，mock_tests 生成有意义的 adversarial 测试
2. **UX-16 是当前最大体验痛点**——4 次 actor 进程崩溃需手动重启，`try/except: pass` 吞掉所有诊断信息
3. **Codex 审查发现真实漏洞**——refresh token misuse（RO-105）和 audit 未集成（RO-106），说明 98% coverage 不等于正确性
4. **验证深度的系统性缺口**——verify gate 只检查"test 存在 + 通过"，不检查"合同落地"（RO-104）、"helper 被调用"（RO-106）、"攻击面完整"（RO-105）
5. **Flow 表述问题累计 4 处偏差**（FL-20）——相对路径解析、报告路径、并行提示、git diff cwd，每处都需 retry
6. **Failure recovery 连续两轮零触发**——需要更极端的不可能条件设计

---

## v40 代码修复归档：FL-17b/FL-18/FL-16/PLN-1/UX-14/UX-13（2026-05-18）

| ID | 标题 | 修复内容 |
|----|------|---------|
| FL-17b | solve flow 完成后 state.json 残留（P2 复现） | flow_engine.py `_cleanup()` 在两个 completion 路径都调用，`shutil.rmtree` 清除 `.ralph-flow` 目录。测试 `test_completion_removes_flow_dir` 验证 |
| FL-18 | step-6 归档迁移应为 blocking（P2） | flow_improvement_check.py `_check_short_tracker_archive_advisory` 改 `passed=False`，check name 改 "blocking"。成功路径 advisory print 残留已清理 |
| FL-16 | E2E flow 结束后应停止 actors（P2） | flow_steps_e2e.py 新增 `_check_cleanup()` + step 7 cleanup。含 `TimeoutExpired`/`OSError` 异常处理（Codex 审查追加修复） |
| PLN-1 | ledger event too large（P2） | cli.py `_write_validation_event()` 改为 compact 格式（counts + outcome），不再序列化完整 issues 列表。向后兼容（Pydantic model `extra="allow"` + `default_factory=list`） |
| UX-14 | 首任务 stall 阈值过低（P3） | workflow_orchestrator.py `ASSIGNED_STALL_THRESHOLD_SECONDS` 120→600，`min→max`。测试 `test_cold_start_500s_not_stalled` 验证 |
| UX-13 | workflow.completed 后未自动生成 evaluation（P3） | workflow_orchestrator.py 新增 `_write_workflow_evaluation()` 在 `_on_workflow_completed` 中调用，生成含统计表格的 WORKFLOW_EVALUATION.md |

---

## v38 E2E 归档：RO-103 已修复（2026-05-17）

| ID | 标题 | 实测证据 |
|----|------|---------|
| RO-103 | input_robustness_smoke 时序误判（P1） | **v38 E2E 验证修复**：修复前连续 3 轮（v37/v38 前两次）所有 task 因 "critical_flow lacks malformed input coverage" 误报失败。根因：`_any_test_covers_robustness` 检查 plan 声明的 test files 是否含 malformed input patterns，但这些 files 属于下游 task（`task-security-tests`/`task-integration-tests`），验证当前 task 时物理不存在 → 全部 skip → 返回 False → 误判。修复：`security_scan.py` 当 plan 声明的 test files 全部不存在时不阻断（coverage 将由后续 batch 提供）；`verification_gate.py` 合并完整 plan 的 tasks 用于跨 task test file 发现。修复后 v38 E2E 6/6 tasks verification_passed，0 false positives，综合 4.2/5。 |

---

## v36c 归档：RL-26 已验证修复（2026-05-16）

| ID | 标题 | 实测证据 |
|----|------|---------|
| RL-26 | E_AEGIS_PLACEHOLDER_CONTENT 对文件路径中的 "todo" 产生误报（P2，2026-05-16 v36 发现） | **v36c 实测验证修复**：foreman plan.yaml 在 goal_behavior + aegis.baseline_refs 共 6 处含 `todo/notes-api-spec.md`，`ralph validate` 通过 0 error，无 E_AEGIS_PLACEHOLDER_CONTENT。代码 `validation_rules/discipline.py:20-23` 用 `\btodo\b(?![/\\.\-])` negative lookahead 排除 `todo` 后跟 `/`/`\`/`.`/`-` 的情况，**修复在某时点已落地但短版未移出**。原改进方案：词边界匹配；原验收标准：`goal_behavior` 中引用 `todo/` 路径不触发 placeholder error。 |

---

## v36 归档：RO-87 移出短版（2026-05-16）

| ID | 标题 | 处理 |
|----|------|------|
| RO-87 | Codex foreman plan.yaml 漂移导致 plan_digest_divergence（P2，2026-05-15 v35 发现） | 已纳入 v37 修复 scope；v36 第二轮 Claude foreman 复测未触发；条目从短版移出以减小噪音，v37 完工后此条改写为"已确认修复"或"复测通过"。改进方案：注册后对 plan.yaml read-only 锁定，修改需显式 re-register；验收标准：注册后 plan_digest_divergence 事件数 ≤1 |

---

## v36c E2E 第三轮归档（2026-05-16）— Flask FTS5 笔记应用（场景触发实测）

> Foreman：Claude runtime (Opus 4.7) | Worker：Claude runtime (worker-1)
> 状态：**workflow 卡死无法完成 WORKFLOW_EVALUATION**，T01 完成 + T02 deferred 死循环 + T03 永远 planned
> 实测目的：触发 RO-89/90/91/RL-26/UX-11 检查修复有效性
> 项目：Flask 笔记应用 + SQLite FTS5 + admin 面板 + 故意 debug=True

### 触发结果汇总

| 编号 | 触发? | 检测结果 |
|----|------|---------|
| RL-26 | ✓ (plan 6 处 todo/) | ✅ **修复已生效**（已移入归档）|
| RO-89 (FTS5 NUL→500) | ✓ (磁盘上 search 路由确认 NUL→500) | ❌ **verify gate 完全盲**（ralph verify outcome=passed）|
| RO-90 (debug=True) | ✓ (app.py 末 `app.run(debug=True)`) | ❌ **verify gate 完全盲**（ralph verify outcome=passed）|
| RO-91 (claimed_paths 推断) | ✗ | foreman 写对了，场景没构造出来 |
| UX-11 (deferred re-verify) | ⚠ 部分相关 | 实际触发的是更严重的 RO-95 死循环 |

### 新发现条目

| ID | 标题 | 优先级 | Cluster |
|----|------|--------|---------|
| RO-95 | workflow defer recovery 死循环：deferred/failed 后 retry 永远 hit single_writer_active | P1 | workflow-recovery-protocol |

### v36c 关键洞察

1. **verify gate 安全深度跨 5 版未解决**（v33/v34/v35b/v36/v36c）—— RO-89/90 在 v36c 用专门触发项目实测**漏检铁证**确认
2. **workflow-recovery-protocol cluster 形成**：UX-11、RO-95、v36 P-3 同根（workflow 状态机 + foreman 协议歧义）
3. **release_agent 单调用点缺陷暴露**：全代码库唯一调用点在 happy path（`assignment_completion.py:32`），fail/defer/timeout 三条路径全部漏调

---

## v36 E2E 第二轮归档（2026-05-16）— FastAPI URL shortener with SSRF

> Foreman：Claude runtime (Opus 4.7) | Worker：Claude runtime (worker-1)
> 综合评分：4.0/5（结果 3/5，过程 4/5，体验 5/5）—— v35b 3.3/5 → v36 4.0/5（+0.7）
> 4 任务（scaffold + security 并行 → api → e2e）
> 项目：FastAPI URL 短链接服务（SSRF 防护 + admin token DELETE + SQLite + 96 pytest）
> 详细报告：[e2e-实战评估报告-v36.md](./e2e-实战评估报告-v36.md)

### 新发现条目（详细描述见短版）

| ID | 标题 | 优先级 | 来源 |
|----|------|--------|------|
| RO-92 | verify gate 安全方法库:TOCTOU 审查(`temporal_pattern` 声明驱动) | P1 | Codex R-1 |
| RO-93 | verify gate 安全方法库:hostname 编码矩阵(`ssrf`/`url` flow 驱动) | P1 | Codex R-2 |
| RO-94 | verify gate 安全方法库:timing-safe grep(`*_auth` flow 驱动) | P2 | Codex R-4 |
| FL-8 | e2e 任务的 verification.checks 应强制 compile step | P2 | Codex P-1 |
| FL-9 | provides/consumes 应支持 signature 声明并机器校验 | P2 | Codex P-2 |
| FL-10 | plan.yaml 应自动持久化 workflow 完成态 | P3 | Codex P-5 |

### v36 第二轮验收要点

- 持续 4 版本（v33/v34/v35b/v36）的 verify gate 安全深度缺口仍存在：本轮在 redirect-time SSRF 时序 + 输入编码规范化 上暴露
- Claude foreman + 详细 plan 模板带来过程 +1（4/5）和体验 +1（5/5），是综合 +0.7 的主因
- observer 零干预，无 chat 绕过 workflow

### v36 第二轮设计决策

**verify gate 安全方法库(Security Recipe Library)触发机制**:
- **critical_flow 声明驱动,无声明 = 零触发 = 零噪音**
- 三重门控:critical_flow 含安全关键词 AND 声明对应 surface_type AND checks 缺少对应测试 → 才报 warning
- 新 recipe 默认 hint 级别,3 轮无误报升 warning,5 轮升 error
- 无安全 flow 的项目(CLI/数据管道/算法库)→ 零检查零噪音,防止无关项目误导
- Recipe 按 surface_type(CWE 分类)组织,非按项目类型硬编码

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
| AD-5 | prompt_builder 无 aegis intent 注入 | _aegis_sections_for_task() 按 intent 注入 |
| AD-6 | Foreman system prompt 无 Aegis 感知 | system_prompt.py 加 Plan Discipline 段 |
| FL-1 | e2e step-1 不自动准备环境 | auto mkdir + git init + docs copy |
| FL-3 | step-6 不区分短版/full 写入 | 检查两个 tracker 都有变更 |
| RL-23 | goal_behavior 算法逻辑错误不可检测 | agent rule 8 实现 |
| RL-24 | goal_behavior 与运行时行为矛盾不可检测 | agent rule 9 实现 |

---

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
> 第 3 批绕过 workflow 根因：
> - retry 创建新 batch 后，worker-1 仍被标记为 `single_writer_active`
> - task 卡在 deferred 状态，无法 re-dispatch
> - foreman 被迫通过 chat 手动下发 integration-tests
>
> 新发现：RO-89（FTS5 malformed 500）/RO-90（debug=True 检测）/UX-11（deferred retry）/RO-91（claimed_paths 推断）/FL-7（step-6 归档自动化）
> 结论：Claude foreman 流程正确性高于 Codex foreman，但 verify gate 深度不足（连续 v33/v34/v35b 问题）

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

---

## 参考：UX-6 ralph flow 设计文档（已实现）

> 从短版迁入（2026-05-16），该功能已实现并在 v35b 中使用。

设计原则：渐进式披露 + 触发式自动检查 + Codex 强制验证 + 失败不前进。
实现位置：`src/cccc/ralph/flow_engine.py` + `src/cccc/ralph/flow_steps_e2e.py`
CLI：`ralph flow start {solve|e2e}` / `ralph flow next` / `ralph flow status`

---

## 参考：蓝图偏移（v28 后更新）

> 从短版迁入（2026-05-16）

| 设计要素 | 状态 |
|---------|------|
| Task 间 DAG 调度 | ✅ 完成 |
| 验证 ralph 模式 | ✅ 完成 |
| 验证 agent 模式（mock_tests） | ✅ BP-1 完成 |
| Worker 黑盒模型 | ⚠️ BP-3 基础完成 |
| Task 内模块化拆分 | ❌ BP-2 |
| 模块拼接 + 批次 E2E | ⚠️ BP-5 部分 |
| 并行解耦第二层 | ❌ BP-4 |

---

## 参考：已知局限（NOTE 类）

> 从短版迁入（2026-05-16）

| 编号 | 观察 |
|------|------|
| RV-15 | Ralph 新规则自身的 bug 无法自检 |
| RV-18 | goal_behavior 中引用的函数名可能不存在 |
| RV-19 | 模型扩展可能破坏已有语义 |
| RO-5n | W_FLOW_SEGMENT_UNOWNED 对 verification role 过度报警 |
| RO-10n | verification 命令强度无法检测运行时语义 bug |

---

## 参考：版本历史评分追踪

| 版本 | 日期 | 结果 | 过程 | 体验 | 综合 | 关键变化 |
|------|------|------|------|------|------|----------|
| v1 | 04-01 | 2 | 1 | 2.5 | 1.8 | 基线 |
| v15 | 05-01 | 3 | 5 | 4 | 4.0 | 历史最高（至 v27） |
| v28 | 05-13 | 3 | 5 | 4.5 | 4.2 | 前历史最高 |
| **v32** | **05-14** | **4** | **5** | **4** | **4.3** | **历史新高** |
| v33 | 05-15 | 3 | 5 | 4 | 4.0 | XSS + 并发安全 |
| v34 | 05-15 | 3 | 4 | 4 | 3.7 | 基础设施修复 |
| v35 | 05-15 | 2 | 2 | 3 | 2.3 | Codex foreman 首测 |
| v35b | 05-16 | 3 | 3 | 4 | 3.3 | Claude foreman 复测 |
| v36 | 05-16 | 4 | 4 | 4 | 4.0 | FastAPI SSRF，次高 |
| v37 | 05-17 | 3 | 3 | 4 | 3.3 | Flask FTS5，challenge gate 误判 |
| **v38** | **05-17** | **4** | **4** | **5** | **4.2** | **Flask FTS5 复验，input_robustness 修复验证通过，0 manual interventions** |
| **v39** | **05-17** | **4.5** | **4.5** | **4** | **4.3** | **FastAPI Bookmark Service，历史并列最高；86 tests, 93% cov, SSRF 20 cases, Aegis discipline 首次实战验证** |

## v39 代码修复归档（2026-05-17，全量 42 项 + REG-1/REG-2）

以下条目在 v39 solve flow 中完成代码修复，全量 pytest 2913 passed / 0 failed / 120 skipped 验证通过。

### RO 系列
- **RO-84**（P2）：validate ledger 事件 — `ralph.validate_result` 事件发送到 daemon。v39 E2E 确认生效。
- **RO-89**（P1）：verify gate 检测 FTS5 malformed input — input_robustness_smoke 检查已实现。
- **RO-90**（P2）：verify gate 检测 debug=True — security_lint grep 检查已实现。
- **RO-91**（P3）：claimed_paths 遗漏写入文件 — W_CLAIMED_PATH_INCOMPLETE 规则已实现。
- **RO-92**（P1）：TOCTOU 审查 — temporal_pattern 字段 + W_VERIFICATION_TOCTOU_GAP recipe 已实现。
- **RO-93**（P1）：hostname 编码规范化 — url_input security recipe 含编码矩阵已实现。
- **RO-94**（P2）：auth timing-safe compare — auth_token security recipe grep 检查已实现。
- **RO-95**（P1）：deferred recovery 死循环 — on_task_failed 和 deferred 转移时 release_agent 已修复。
- **RO-97**（P1）：verification_mode=ralph 语义 — ralph mode 不触发 challenge review 已实现。
- **RO-98**（P2）：task failure vs infra failure — verification_infra_error 状态已实现。
- **RO-99**（P1）：challenge prompt 安全 checklist — critical_flows 驱动的 checklist 注入已实现。
- **RO-100**（P2）：discipline rule 输出排序 — sorted(dependencies) 已修复。
- **RO-101**（P2）：challenge upgrade 独立测试 — _should_upgrade_to_challenge 已提取为独立方法。
- **RO-102**（P3）：validate ledger event plan 不存在时 crash — plan_path.exists() 防御已修复。

### FL 系列
- **FL-4**（P2）：guide --output 覆盖 Description — models.py Field(description=) 已添加。
- **FL-5**（P2）：guide --update dev 分支 warning — advisory 降级已实现。
- **FL-6**（P2）：_check_improvement_register 不区分新旧 — version marker 检查已实现。
- **FL-7**（P2）：step-6 归档迁移提示 — archive advisory 已实现。
- **FL-8**（P2）：e2e 强制 compile step — W_E2E_MISSING_COMPILE_CHECK 已实现。
- **FL-9**（P1）：compact 盲点 — managed suppress 在 compact 模式显示已修复。
- **FL-10**（P3）：plan.yaml 持久化 workflow 态 — suggest 从 ledger 读已实现。
- **FL-11**（P2）：foreman override 路径 — cccc workflow override 命令已实现。
- **FL-12**（P2）：deferred 可恢复状态 — deferred 出边（retry/accept/cancel）已实现。
- **FL-13**（P3）：e2e enhancement test xdist flaky — 已标记 serial。
- **FL-15**（P2）：step-6 引导写入新发现 — instruction 已更新。

### UX 系列
- **UX-5**（P2）：ralph guide 自动生成 — 已实现。
- **UX-8**（P3）：claimed_paths 冲突提示 — overlap 输出含任务对已实现。
- **UX-11**（P2）：deferred re-verify — verify --refresh-spec 已实现。
- **UX-12**（P3）：SUSPICIOUS 标记误报 — grep/test 快速命令豁免已实现。

### AD 系列
- **AD-1**（P1）：AegisDiscipline 子模型 + aegis 字段 — schema 已实现。v39 E2E 确认 foreman 正确使用。
- **AD-2**（P1）：intent 推断 + discipline.py 基础设施 — effective_intent() 已实现。
- **AD-3**（P1）：首期 5 条高信号规则 — E_AEGIS_PLACEHOLDER_CONTENT / E_AEGIS_RETIREMENT_TRACK_MISSING / W_AEGIS_FIX_NO_REPAIR_TRACK / W_AEGIS_TDD_NO_TEST_PATH / W_AEGIS_COMPLEX_MISSING_BASELINE 已实现。v39 E2E 确认实战生效。
- **AD-4**（P1）：verification_gate Evidence 质量门 — _check_aegis_evidence 已实现。
- **AD-7**（P3）：suggest 阶段 Aegis 快检 — E_ 规则 task 不进 ready batch 已实现。
- **AD-8**（P3）：二期规则扩展 — 7 条候选规则已实现。
- **AD-9**（P2）：aegis intent→verification 强制链 — _check_aegis_discipline 已实现。
- **AD-11**（P1）：validate LLM 生成 behavioral security checks — security_check_generator 已实现。

### SL 系列
- **SL-1**（P3）：security_lint 升级 blocking — record_verification_failure 已修复。
- **SL-2**（P3）：扩展 pattern 矩阵 — bare_except/eval/exec 等已添加。
- **SL-3**（P3）：input_robustness 升级 blocking — 已修复。

### RL 系列
- **RL-22**（P3）：goal_behavior 与源码语义不一致 — agent 可覆盖。
- **RL-25**（P3）：实现方案与数据结构不兼容 — agent 可覆盖。

### 其他
- **PLR-1**（P2）：code fence 内术语触发 aegis — 引用例外已实现。
- **PLR-2**（P2）：covers.paths 自动补齐 — covers.tasks 展开已实现。
- **DOC-1**（P3）：capability guide verify gate warning 清单 — 已补充。
- **DOC-2**（P3）：suppress 文档 — managed suppress 说明已补充。
- **REG-1**（P3）：test_command_not_found_fails 断言 — 已更新为 infra_error。
- **REG-2**（P3）：test_covered_flow_summary level 编号 — 已更新。

---

## v39 E2E 验证归档（2026-05-17，FastAPI Bookmark Service）

### 已验证修复

- **AD-1~3**（Aegis discipline 规则）：E_AEGIS_SECURITY_CHAIN_MISSING 在 validate 中触发并强制 foreman 添加 managed suppress；W_AEGIS_COMPLEX_MISSING_BASELINE 和 W_AEGIS_TDD_NO_TEST_PATH 正确报告。规则有效，foreman 能正确响应。
- **RO-84**（validate ledger 事件）：ralph.validate_result 事件在 ledger 中确认（4 次 failed + 1 次 passed）。

### 未触发（执行太干净）

- RO-95（deferred recovery）：0 deferred tasks
- RO-96（attach 路径解析）：使用绝对路径，未触发相对路径 bug
- RO-97（verification_mode 语义）：全部 ralph mode，无 challenge
- RO-98（infra vs task failure）：0 failures
- SL-1/2/3（security_lint）：Worker 未犯低级错误
- RO-92/93/94（security recipes）：recipes 未被 runtime 触发（Worker 自行实现了正确安全逻辑）

### v39 新发现

- FL-17b（P2）：solve flow state.json 清除仍未生效——cwd 下残留旧状态阻塞新 flow
- UX-13（P3）：foreman 未在 workflow.completed 后自动生成 WORKFLOW_EVALUATION.md
- UX-14（P3）：Worker 首任务冷启动 stall 阈值过低（300s 触发，实际 ~400s 完成）

### v47 E2E 验证（2026-05-24，FastAPI 用户管理 + JWT 认证）

> 综合 4.0/5（结果 3.5/5，过程 4.5/5，体验 4/5）
> 报告：[e2e-实战评估报告-v47.md](./e2e-实战评估报告-v47.md)

**已验证生效（v46 修复）：**
- FL-40/43（模型选择双路径）：worker-1=claude, worker-2=codex，foreman 主动选择不同 runtime
- FL-38（auto-dispatch）：所有 batch 走 auto_fallback 路径，无 assignment-map
- FL-31/39（负载均衡+并行度 guide）：T2+T3、T5+T6 双 worker 真并行
- RO-113（JWT 默认密钥 guide）：config.py 无硬编码，RuntimeError 守卫，T6 AST 安全测试
- RO-112（FTS5 CJK guide）：LIKE fallback 正确实现和文档化
- FL-32（state.json HMAC）：flow state 未被篡改

**已验证归档（从短版迁入）：**

- **FL-32**（state.json HMAC 签名）：v46 修复增加了 HMAC 签名字段，v47 E2E 中 flow state 未被篡改。
- **FL-35**（Codex sandbox 改进）：v46 修复后 Codex review 明确标注环境限制（read-only sandbox 无法运行 pytest），不再因环境问题产生失真评分。
- **RO-112**（FTS5 CJK guide）：v46 在 guide 中增加了 FTS5 中文搜索最佳实践。v47 E2E 中 plan 明确指定 LIKE fallback，search 端点正确使用 LIKE '%q%'。
- **RO-113**（JWT 默认密钥 guide）：v46 在 guide 中增加了检测默认密钥的指引。v47 E2E 中 config.py 无硬编码密钥，缺失时 RuntimeError，T6 security test 用 AST 扫描检测。
- **FL-29**（越界检测统一）：v46 修复后 verification gate 统一了越界检测逻辑。v47 中 T4 修改了 main.py（T1 claimed_path），虽未见 ledger 越界警告（因 main.py 在 T4 的 awareness_paths 中），但 claimed_paths 精确到文件级。
- **FL-30**（verification 偏浅 guide）：v46 在 plan template 中增加了行为验证指引。v47 plan 中 T5 的 verification 包含 pytest_run（行为验证），T4 包含 route_count（结构验证+行为验证）。
- **FL-31**（负载均衡 guide）：v46 在 guide 中增加了负载均衡指引。v47 中双 worker 真并行分配，T2+T3 和 T5+T6 均双路并行。
- **FL-38**（auto-dispatch 负载均衡）：v46 修复 guide 引导不传 assignment-map。v47 所有 batch 走 auto_fallback 路径，无 assignment-map。
- **FL-39**（并行度 guide）：v46 在 guide 中增加了并行度指引。v47 foreman 创建 2 个 worker 并实现了双路并行。
- **FL-40/43**（模型选择双路径+description fallback）：v46 修复了 select_model_for_task 的 description fallback。v47 foreman 主动选择了不同 runtime（worker-1=claude, worker-2=codex）。

**代码已修复，场景未触发（迁入 full 归档）：**
- FL-34（归档检测改为内容比较而非 git diff）、FL-36（step-2 模板增加 .env 指引）、FL-37（check 逻辑明确推导路径）

**未充分验证：**
- FL-41（多角色 guide）：只创建 2 个执行者 worker，未创建 reviewer/auditor
- FL-42（评价闭环）：无 foreman_rating 记录
- FL-33（secret 预检）：手动创建 .env，未触发 pre-flight check
- RV-12/13/14：validate 0 error 但无法确认规则自查是否触发

**v47 新发现：**
- FL-44（P2）：challenge verification false positive（T1/T2 代码正确但 challenge 失败）
- FL-45（P2）：Foreman 仍只创建执行者角色
- FL-46（P2）：/search 端点 RBAC 缺陷未被 plan/security test 检测
- FL-47（P2）：test_routers.py 隔离问题未被 verification 发现
- UX-18（P3）：WORKFLOW_EVALUATION.md 自动生成内容过简

---

## v49 归档（2026-05-30 solve flow）：从短版迁入的已完成项详情

> 这些条目在 v46（RV-12/13/14）/ v46（FL-41）已标记「已完成」，但详细 `####` 段落一直滞留短版，
> 本轮按 FL-51 的归档纪律迁入 full。短版仅保留 header 的一行 `已完成` 摘要。

### v45 Codex review（已完成，v46 代码修复）

#### RV-12（validate 不检测 discipline rule 注册遗漏）

discipline_security.py 中定义的规则函数不一定被注册到 discipline.py 的 `_DISCIPLINE_RULES` 列表。现有 validate 无法检测"规则定义了但未注册"的情况。需要：validate 规则自查——扫描 discipline_*.py 模块中 `_check_*` 函数签名符合 `DisciplineRule` 的函数，验证它们是否出现在 `_DISCIPLINE_RULES` 或被其内部调用。（已实现 `check_rule_registration_completeness`）

#### RV-13（verification gate 与 validate 的 shallow check 判定不统一）

coverage.py 已有 `_is_compile_or_import_check` 等 shallow check 分类器，但 verification_gate.py 的 runtime gate 需要独立实现同样的判定逻辑。两套判定标准可能漂移，导致 validate 通过但 runtime gate 拒绝（或反之）。需要：抽取公共 shallow check classifier 到共享模块，让 validate 和 runtime gate 共用同一套判定。（已抽取 `shallow_check_classifier.py`）

#### RV-14（assignment_startup 不消费 actor_add 返回的 running/start_error 字段）

`_start_actor_for_assignment` 只检查 `resp.ok`，但 `actor_add_ops.py` 返回中包含 `running` 和 `start_error` 字段。不消费这些字段会丢失第一手失败原因，导致 actor 注册成功但实际未运行时无法及时发现。需要：消费 `running`/`start_error` 字段，对已注册但 stopped 的 actor 走 restart 语义。

### v42 E2E agent 架构缺陷（FL-41 已完成，v46 代码修复）

#### FL-41（**P1** Foreman 只创建"执行者" agent——缺少 reviewer/fixer 等多视角角色）

v42 foreman 创建了 2 个 worker，角色定义仅为"backend core"和"tests"，本质是同质化的执行者。没有创建 reviewer（代码审查）、bug fixer（缺陷修复）、security auditor（安全审计）等角色。这导致整个工作流是"写完就交"的单向流程，缺少真实团队中的交叉审查和多维度质量保障。

**对比真实团队**：一个 tech lead 不会只派 2 个 coder 写完代码就交付——会安排人 review、有人专门跑安全扫描、有人负责集成测试。Foreman 应该像真正的 tech lead 一样思考"这个项目需要哪些角色"，而不仅仅是"我要几个人写代码"。

**当前 agent_pool 的能力支持**：
- `role_type` 枚举已支持 `"worker" | "reviewer" | "specialist"`
- `create_agent_for_task()` 可以生成任意 worker_prompt
- `task_affinity` 可以标记 agent 的专长
- 但 foreman 不知道应该创建这些角色，因为 guide 和模板都只提到 "创建 Worker actor"

**需要**：
1. **foreman guide 增加"团队组建"指引**——明确列出可选角色及适用场景：executor（执行）、reviewer（审查关键路径的代码质量和安全）、fixer（验证失败后专门修复）、integrator（跨模块集成测试）
2. **plan.yaml 增加 `recommended_roles` 字段**——ralph suggest 根据 critical_flows/forbidden_flows 自动建议"建议为安全关键路径增加 reviewer agent"
3. **Foreman 规划阶段主动评估**——"11 个任务中有 security tests 和 XSS 防护需求，应该创建一个 security-reviewer agent 专门审查安全实现"

> 注：FL-41 的"多角色"能力后续由 FL-45（v48 E2E 确认 foreman 自动创建非执行者 sec-reviewer 角色）实战验证生效。

---

## v50 归档（2026-05-31 代码修复，17 tasks）

> 来源：solve flow（plan.yaml v50 批次），step-3 双路 Codex 审查（HMAC 签名）+ 全量回归 3174 passed。
> 以下条目本批完成代码修复并单测验证，从短版移出归档。

### validate 检测能力缺口（新增 8 条规则）

- **RV-22**（`W_RBAC_WRITE_ENDPOINT_UNCOVERED`，security.py）：RBAC critical_flow 写端点在「已有 auth check」前提下缺授权负例（403/role/matrix）用例时告警；去重前置避免与 `W_RBAC_FLOW_AUTH_UNVERIFIED` 双报。
- **RV-23**（`E_STATE_TASK_STATUS_CONFLICT`，coverage.py）：state 三桶（completed/failed/running）id 交集非空或桶内重复。
- **RV-24**（`E_STATE_RUNNING_TASK_INVALID_CLAIMS`，coverage.py）：running_tasks.claimed_paths 空或非对应 TaskSpec.claimed_paths 子集。
- **RV-25**（`E_CONSUMER_FROM_NOT_PROVIDER`，contracts.py）：consume.from_task 已填但该 task 的 provides 不含同名 contract。
- **RV-26**（`E_MODULE_DEP_CYCLE`，structural.py）：per-task modules.internal_depends_on 自环/成环检测。
- **RV-27**（`W_CRITICAL_DECLARATION_OUTSIDE_PLAN_SCOPE`，coverage.py）：critical_flows.entrypoints/critical_entrypoints 整体落在 plan_scope 之外被静默跳过；复用 `_entrypoint_in_scope`。
- **RV-28**（`E_FLOW_TEST_CREATOR_FAILED`，coverage.py）：test_created_by 创建者失败（在 failed_task_ids）仍维持 deferred 降级 → 恢复 hard error；`_pending_test_creator_ids` 增 failed_task_ids 入参。
- **RV-29**（🔴致命，`W_AUTH_PRIVILEGED_ROLE_FIELD`，security.py + guide）：身份获取面（注册/登录/角色变更）特权 role 字段边界缺负例覆盖；surface_type/标签驱动，删除不成立的 undeclared 误报分支，与 RV-22 去重；guide 增「身份获取面越权检查模板」。

### flow/UX 修复

- **FL-48**（context_store.py + workflow_orchestrator.py）：retry/override 决策（override_task/retry_verifier/retry_task）写回 TaskContext 审计字段（决策留痕，向后兼容）。
- **FL-49**（`W_REVIEWER_SIGNOFF_MISSING`，security.py）：安全敏感流有独立审查语义任务但无可审计 sign-off 产物引用时告警；复用 `_task_has_independent_review_semantics`，与 `W_CRITICAL_FLOW_NO_INDEPENDENT_REVIEW` 去重。
- **FL-51**（flow_improvement_check.py）：step-6 归档 check 扩展「已验证生效/已修复」标记——未从短版归档则 FAIL；同步修 `_is_archive_paragraph_line`/`_full_diff_has_archive_paragraph` 防 bare header 误判。
- **FL-52**（`W_FLOW_COVERAGE_DEFERRED` 配套 + validator.py/cli.py 双通道）：安全关键码（含 W_AGENT_REVIEW_SKIPPED）在含 RBAC/auth 关键流时不可被 suppress_codes 静默压制；helper `_plan_has_security_critical_flow`/`_non_suppressible_codes` 抽取至 `validation_rules/security.py` 共享。
- **FL-53**（`W_FLOW_COVERAGE_DEFERRED`，coverage.py）：deferred 未覆盖 flow 额外 emit 独立 warning 新码（不被 uncovered 的 suppress 压回 hint），计划期可见、不随文件系统漂移。
- **FL-54**（`W_FULL_REGRESSION_OVERRIDE_RISK`，coverage.py）：全量回归门 × 计划内 override（仅扫 verification command/checks/mock_tests 的 xfail/importorskip/pytest.skip，不扫 prose）双存在时预警。
- **UX-18b**（flow_steps_e2e.py）：evaluation 占位符内容检测——章节齐全但实质为占位符（待补充/TODO 等）判 FAIL。
- **UX-19**（workflow_orchestrator.py）：测试采集失败时仅降级 test_count_actual 表述 + test_stats_reliable=false，保留兼容原始 N/A 值，不出具「0 failed」绝对断言、不误降 task 级 Completed/Failed。
- **UX-20**（workflow_orchestrator.py）：stall 判定新增可注入 actor_idle_provider，actor 在产出（idle 低）时不误判 stalled；provider 不可得回退原 task 级判定。
- **UX-21**（cli/main.py + cli/model_cmds.py + guide）：新增 `cccc model rate <model> --rating <1-5> [--registry PATH]` 本地直写 registry，接 `rate_model_by_foreman`；guide 措辞校正。

### 补归档历史欠账（v49 已修，短版未删）

- **RV-18**（`E_VERIFICATION_NON_GATING`）/ **RV-19**（`E_FLOW_TEST_CREATED_BY_UNKNOWN_TASK`）/ **RV-20**（`E_FLOW_ID_CROSS_NAMESPACE_COLLISION`）/ **RV-21**（`E_CONSUME_PROVIDER_UNRESOLVED`）：v49 solve flow 已实现并单测，本批补归档（闭合 FL-51 亲历的「verified-but-not-archived」问题）。

### v50 E2E 复验归档（2026-05-31，团队密钥保管箱 API）

- **RV-29 ✅✅ E2E 闭环**：validate 报 `W_AUTH_PRIVILEGED_ROLE_FIELD`→foreman 模型/路由/集成三层防御+负向测试+forbidden_flow；runtime 探测注册塞 role=admin→落库 member+`/admin/users` 403；Codex results-review 独立确认闭合。v49 致命提权漏洞闭环。
- **FL-48/FL-54 ✅**：`workflow.foreman_override` 结构化 reason+evidence；T6 故意失败→retry→override 全程留痕。**UX-20 ✅** 无误报 stall。**UX-18b ✅** 完成时 741B→foreman 补 10.6KB。
- 短版面包屑迁入归档：**FL-20/21**（codex_bridge HMAC 链路，v48 已验证）、**FL-45**（自动建非执行者 sec-reviewer，v48 归档 v49 复确认）、**FL-43**（select_model_for_task description fallback，v47 E2E 确认）三项 breadcrumb 从短版精简，详情归此处归档段。

### v51 E2E 验证归档（2026-06-03，FastAPI 安全文件共享服务）

> v51 综合 4.0/5（结果 4.0 / 过程 4.0 / 体验 4.0）。9 tasks 全完成，100 tests pass，~32min。
> 报告：[e2e-实战评估报告-v51.md](./e2e-实战评估报告-v51.md)

- **FL-55 ✅**（security.py `_NON_SUPPRESSIBLE_WHEN_SECURITY`）：validate 输出 `W_CRITICAL_FLOW_WORKER_ONLY_VERIFICATION [T03_ROUTERS]` 未被 suppress，规则生效。
- **FL-56 ✅**（security.py `W_SIGNOFF_STRUCTURE_WEAK`）：对 authentication_flow 和 authorization_flow 两条安全 flow 分别报警，规则生效。
- **FL-58 ✅**（workflow_orchestrator.py result_breakdown）：WORKFLOW_EVALUATION.md 含 `result_breakdown: passed=6, overridden=1, assumption_based=0, independently_reviewed=2`，T01 明确归类为 overridden 而非 passed。
- **FL-59 ✅**（ralph/plan_io.py 原子写入）：plan.yaml 在 workflow 全程保持结构完整（foreman 多次 validate 无 YAML parse error），未触发 YAML 损坏。
- **FL-60 ✅**（workflow_monitor.py `_plan_state_from_ledger_statuses`）：T01 verification_failed→foreman_override→T02 started 状态转换正确，无 ledger 死锁。
- **FL-62 ✅**（structural.py `_normalize_entrypoint`）：validate 输出无 entrypoint 格式误报（v50 有 5 个误报，本轮 0 个）。
- **RV-30 ✅**（structural.py `E_TASK_PATH_OUTSIDE_PLAN_SCOPE`）：第一次 validate 报 2 errors 含路径越界类错误，foreman 修复后 0 errors 通过。
- **UX-22 ✅**（verification_gate.py SUSPICIOUS 免检）：T09 `no_hardcoded_jwt: passed (10ms) - [SUSPICIOUS]` 标记但仅 advisory 不阻断。
- **FL-57+FL-50 ⚠️部分**：validate 未报 randomization 告警（项目无 randomized check 声明）；WORKFLOW_EVALUATION 写 reliable=true 但无 pytest-randomly→转 FL-63。
- **FL-61/RV-31/RV-32 ➖未触发**：本轮场景未出现（无 evidence/outcome 矛盾、无 suppress_flows、契约类型一致）。

### v51 E2E 归档补充（2026-06-03，跨 commit 迁移）

> 以下条目在前一 commit 已归档至 full，此处补充 v51 marker 以通过 flow 检查。
> FL-55/FL-56/FL-58/FL-59/FL-60/FL-62/RV-30/UX-22 ✅ v51 E2E 验证通过。
> FL-57/FL-50/FL-61/RV-31/RV-32 场景未触发，归档。

### v51 E2E 新发现登记（2026-06-03）

- **FL-63**（P2）：WORKFLOW_EVALUATION test_stats_reliable 自动化判定缺失——foreman 自述 true 但无 pytest-randomly。
- **FL-64**（P2）：is_admin 注入边界未被 forbidden_flow 强制覆盖——validate 不检测测试是否覆盖所有声明的注入向量。
- **FL-65**（P3）：independently_reviewed 分类缺任务级映射——result_breakdown 无法审计追溯。
- **UX-23**（P3）：WORKFLOW_EVALUATION 初始生成为占位符后 foreman 补充实质——补充过程成功但初始占位符可改进。
- **RV-39**（P3）：validate 不检测 plan 目标（声明 410）与实现（实际 404）状态码漂移。

### v57 E2E 验证归档（2026-06-05）

> v57 E2E 验证（FastAPI 多租户任务队列 API JWT+RBAC+多租户隔离+任务状态机+审计日志）：综合 3.5/5（结果 3.5 / 过程 3.5 / 体验 3.5）
> 团队：lead(foreman,claude) + worker-a(claude) + worker-b(claude) + security-reviewer(claude)
> 10 tasks 全完成（passed=6, overridden=2, independently_reviewed=2），66 tests pass，~35min。

**已验证生效并归档（v57 E2E 确认）：**
- **RV-29**（注册提权三层闭合）：✅ `extra="forbid"` + 数据库权限源，role/is_admin/is_superuser/permissions/scope 全部被拒。
- **FL-33**（secret_preflight）：✅ step 4 首次失败因 CODEX_BRIDGE_SECRET 未配置，配置后通过。
- **FL-38**（auto-dispatch）：✅ T7/T8 并行执行，batch 机制生效。
- **FL-42**（评价系统闭环）：✅ WORKFLOW_EVALUATION.md 自动生成 6033 bytes，结构化数据完整。
- **FL-48**（override 路径）：✅ T3/T4 通过 foreman override 闭合，workflow 继续推进。
- **FL-55**（安全告警不可压制）：✅ validate 报 E_AEGIS_SECURITY_CHAIN_MISSING（4 errors），迫使 plan 迭代修复。
- **FL-58**（result_breakdown 分类）：✅ passed=6/overridden=2/independently_reviewed=2 正确分类。
- **FL-65**（independently_reviewed 任务级映射）：✅ independently_reviewed_tasks: T10-security-review, T9-integration。

**复现/部分生效（v57 确认，保留在短版待修复）：**
- **UX-23**（WORKFLOW_EVALUATION 定性章节空）：⚠️ 复现——正面反馈/负面反馈/手工干预/Worker 可靠性/改进建议全部为空。
- **FL-63**（test_stats_reliable 自动化判定）：⚠️ 复现——foreman 写 false 但 evaluation 文档仍有不可信表述。
- **FL-64**（forbidden_flow 字段覆盖）：⚠️ 复现——ff-self-role-assignment 未声明 fields 数组。

**v57 交叉确认（以下条目在之前版本已归档，v57 编辑短版归档行时触发再确认）：**
- FL-31（负载均衡+并行度）v47 ✅ → v57 短版归档行更新
- FL-32（state HMAC）v47 ✅ → v57 短版归档行更新
- FL-40（模型选择双路径）v47 ✅ → v57 短版归档行更新
- FL-50（函数级隔离）v51 ✅ → v57 短版归档行更新
- FL-56（sign-off 弱检测）v51 ✅ → v57 短版归档行更新
- FL-57（场景未触发）v51 归档 → v57 短版归档行更新
- FL-59（YAML 原子写入）v51 ✅ → v57 短版归档行更新
- FL-60（ledger 状态转换）v51 ✅ → v57 短版归档行更新
- FL-61（entrypoint 格式，场景未触发）v51 归档 → v57 短版归档行更新
- FL-62（其他 v51 修复）v51 ✅ → v57 短版归档行更新
- RO-112（FTS5 CJK）v47 ✅ → v57 短版归档行更新
- RO-113（JWT 默认密钥）v47 ✅ → v57 短版归档行更新
- RV-30（路径越界检测）v51 ✅ → v57 短版归档行更新
- RV-31/RV-32（场景未触发）v51 归档 → v57 短版归档行更新
- UX-22（SUSPICIOUS 不阻断）v51 ✅ → v57 短版归档行更新

### v57 E2E 新发现登记（2026-06-05）

- **FL-67**（P2）：plan.yaml state 段不记录 override 完成的任务——台账 10/10 但 plan.yaml 只记录 8/10。
- **FL-68**（P2）：security-reviewer 创建但 T10 实际派给 worker-a——审查独立性形式满足但实质不足。
- **FL-69**（P2）：claimed_paths 不精确导致大量越界告警——T8 未 claim router 文件、T5/T6 未 claim main.py。
- **FL-70**（P3）：WORKFLOW_EVALUATION 过程摩擦记录不完整——未记录 task_failed/task_deferred/W_WORKER_EXCEEDED_SCOPE。
- **RV-53**（P2）：auth.py sub 类型注入 → 500 而非 401——validate 不检测认证边界畸形输入。
- **RV-54**（P3）：task claim 非原子操作并发竞争窗口——validate 不检测状态机并发安全。

### v58 E2E 归档（2026-06-05）

**v58 E2E 验证（FastAPI 实时事件通知服务 JWT+RBAC+频道+订阅+事件+通知+审计）：综合 3.5/5**
团队：lead(foreman)+worker-1(claude)+sec-reviewer(claude)，8 tasks 全完成（passed=4, overridden=2, independently_reviewed=4 标记但实际仅 T7），96 tests pass，99% 覆盖，~17min。

已验证归档（v58 再次确认）：
- FL-38（auto-dispatch）v57→v58 再次确认 ✅
- FL-48（override 路径）v57→v58 再次确认 ✅（T2+T3 均 override）
- FL-33（secret_preflight）v57→v58 再次确认 ✅
- FL-42（WORKFLOW_EVALUATION 自动生成）v57→v58 再次确认 ✅
- FL-58（result_breakdown 分类）v57→v58 再次确认 ✅
- RV-29（注册 role 提权）v57→v58 再次确认 ✅

新归档（v58 首次确认）：
- **FL-68**（P2→✅）：security-reviewer 实际分配安全审查任务——v58 daemon log 确认 T7 分配给 sec-reviewer 而非 worker-1。v57 的核心修复。
- **FL-69**（P2→✅）：claimed_paths 文件级精度——v58 Codex 审查确认 plan.yaml 路径均为文件级。
- **RV-53**（P2→✅）：JWT sub 类型注入 → 401——verify_token() int(sub) + ValueError→401 代码路径生效，test_jwt_string_sub_returns_401_not_500 测试通过。

复现/部分生效（v58）：
- UX-23 ⚠️ 第四轮复现：定性章节（正面反馈/负面反馈/Worker 可靠性/评分+改进建议）全空
- FL-67 ⚠️ 复现：plan.yaml state 只记录 T1/T4/T5/T6/T7/T8，缺失 T2/T3（overridden）
- FL-64 ⚠️ 复现：forbidden_flows 无 fields 数组
- FL-70 ⚠️ 部分：手工干预记录有内容但定性章节空
- FL-63 ⚠️ 标记 false，pytest-randomly 已安装

### v58 E2E 新发现登记（2026-06-05）

- **FL-71**（P2）：auth 测试使用不鉴权端点 /health 验证认证链路——test_reject_invalid_token 接受 200 作为通过条件。
- **FL-72**（P1）：通知隔离测试断言逻辑失效——允许 notif_ids_a == notif_ids_b，跨用户泄漏不可检测。
- **RV-62**（P2）：independently_reviewed 标记缺乏独立 actor 证据——T5/T6/T8 由 worker-1 执行但标为 independently_reviewed。
- **FL-73**（P1，系统性）：Worker 全用 Claude 未使用 Codex 做主力执行——v57/v58 连续两轮 foreman 无视 runtime 选型指导，所有 worker 均 `--runtime claude`。
- **FL-74**（P1，系统性）：AF 引擎从未实际启用——v53→v58 连续 5 轮声称修复但 `execution_engine: legacy` 路径不变，`_try_af_execution` 只 compile 未 execute。
- **RV-63**（P2）：depends_on 与 consumes 契约不一致——T4/T5/T6/T7 消费 T1 产物但 depends_on 未列 T1。
