# CCCC 问题清单 v5 (未解决) — Ralph 改进专项

> 日期：2026-04-04（v5.2 蓝图对齐更新）
> 状态：7 项原有待改进 + 4 项蓝图新增（Ralph Agent 层 + 超出范围清单 + verification_mode + 两阶段拆分对齐）
> 更新：2026-04-06 Batch A+C 实践新增 RO-13n/RO-14n（验证噪音）+ RO-11n/RO-12n（已知局限）
> 全量版本：[问题清单-v5-ralph-full.md](./问题清单-v5-ralph-full.md)
> 审查依据：[v5-综合审查报告.md](./v5-综合审查报告.md)
> 蓝图对齐：[工作流蓝图.md](./工作流蓝图.md) v0.3（两阶段拆分 + Ralph Agent）
>
> **本文档只保留未解决的改进项和已知局限。已完成的 43 条规则 + 3 运行时增强等历史条目保存在 full 版本中。**

## 一、待实施改进

### RO-7n W_FLOW_SEGMENT_UNOWNED 不支持 Python 符号路径（P2）
- **严重度**：Low — 产生噪音 warning 但不阻塞
- **现象**：critical_flows.entrypoints 写成 `workflow_orchestrator._start_assigned_agents` 或 `agent_pool.AgentPoolManager.evaluate_for_task`（Python 模块.类.方法 格式），Ralph 报 W_FLOW_SEGMENT_UNOWNED 因为它只匹配文件路径
- **根因**：entrypoint 匹配逻辑只做 claimed_paths 的路径前缀匹配，不解析 Python 模块路径到文件
- **改进方案**：在 flow segment 检查中，对非路径格式的 entrypoint（不含 `/`），尝试将 `module.Class.method` 解析为 `src/module.py` 并匹配 claimed_paths
- **验收标准**：entrypoints 写成 Python 符号路径时，claimed 了对应源文件的 task 不再报 W_FLOW_SEGMENT_UNOWNED
- **触发实例**：fix-v3-remaining.yaml 的 3 个 critical_flow entrypoints 全部触发此 warning

### RO-8n W_VERIFICATION_PYTEST_K_NO_MATCH 对尚未创建的测试报警（P2）
- **严重度**：Low — 计划中"该任务将创建此测试"场景的假阳性
- **现象**：T1 的 verification 用 `-k 'daemon_send or status_rollback'`，Ralph 在验证阶段扫描 test 文件发现无匹配，报 W_VERIFICATION_PYTEST_K_NO_MATCH
- **根因**：Ralph validate 在计划执行前运行，此时测试函数尚未创建。当前无法声明"此测试将由本任务创建"
- **改进方案**：（a）当 task claimed_paths 包含该测试文件时，降级为 hint（任务 claim 了测试文件说明会修改它）；或（b）新增 `creates_tests: true` 声明让规划 AI 显式声明
- **验收标准**：task 的 claimed_paths 包含测试文件时，-k 未匹配不再报 warning（降级为 hint）
- **触发实例**：fix-v3-remaining.yaml T1 和 T3 的 verification -k pattern 触发

### RO-9n verification.checks 为空时 Ralph 不报警（P1）
- **严重度**：Medium — 计划中 verification 只有 command 无 checks[]，Ralph 放行，但 engine 运行时只执行 command 不拆分步骤
- **现象**：v4 plan.yaml 中 T1-T4 的 `verification.checks` 全为 `[]`，Ralph validate 通过（0 error）。但这意味着 engine 只跑单条 command，无法区分 compile/test/lint 各步骤的独立通过/失败
- **根因**：Ralph 的 `W_VERIFICATION_BEHAVIOR_MISMATCH` 只检查 command 存在性和 level 匹配，不检查 checks 是否为空
- **改进方案**：新增规则 `W_VERIFICATION_NO_CHECKS`：当 verification.command 存在但 checks 为空时报 warning，建议拆分为至少 compile + test 两个 check
- **验收标准**：plan 中 verification.checks=[] 时 Ralph 报 warning 并给出拆分建议
- **触发实例**：v4 plan.yaml T1-T4 全部 checks=[]，task_registered 事件中 checks 也为空


### RO-11 W_NO_FAILURE_PATH 规则尚未实现（P1）
- **严重度**：Medium — v5 方案根因分析认定"失败暴露通道缺失"是核心问题，但对应的 Ralph 规则完全不存在
- **现象**：对抗审查文档将此规则描述为"warning 级别应升为 error"，但代码核实确认 `ralph/validator.py` 中没有 `W_NO_FAILURE_PATH` 或任何同义规则——它既不是 warning 也不是 error，而是尚未实现
- **根因**：规则设计时从未落地，v5 方案文档中的引用是超前描述
- **代码位置**：`ralph/validator.py`（无此规则）
- **改进方案**：新增规则 `E_NO_FAILURE_PATH`（或先以 W 起步）：对"涉及 assignment / external actor / async decision"的任务，如果没有声明失败时的处理方式（如 failure_path、failure_escalation 字段），报 warning 或 error；如果有例外，要求显式 `accepted-risk` 注记，不能默认放行
- **验收标准**：缺少 failure_path 声明的 assignment 类任务，Ralph validate 产生对应警告

---

### RO-12 计划 YAML 缺 finding_refs 字段的 Ralph 校验（P2）
- **严重度**：Low — 对抗审查识别出 Findings 仅靠提示词注入容易产生"仪式化引用"而非真正受约束
- **现象**：当前计划 YAML 无 `finding_refs` 结构化字段；Findings 检查仅在 prompt 中注入，AI 可以生成格式合规的承诺而不真正受约束（Finding #12/19 已证明此风险）
- **改进方案**：
  - 在计划 YAML schema 中新增可选的 `finding_refs` 字段：
    ```yaml
    finding_refs:
      - id: F16
        mitigation: "declare negative invariants"
        enforced_by: ["ralph:E_NO_NEGATIVE_INVARIANTS", "monitor:NO_SILENT_APPROVAL"]
    ```
  - Ralph 新增规则：如果 `finding_refs` 字段存在，校验每条 finding 是否有 `mitigation` 声明，mitigation 是否绑定到可枚举的规则/monitor/状态机 ID
  - finding_refs 初期为可选；后续可升级为"高风险任务必填"
- **验收标准**：plan 中的 `finding_refs` 有格式错误或 mitigation 未绑定到已知规则时，Ralph 报 warning

### RO-13n 全局 critical entrypoint/flow 对聚焦 batch plan 假阳性（P2）
- **严重度**：Low — 每个聚焦 plan 都需要 suppress_codes 绕过，降低信噪比
- **现象**：Batch A 和 Batch C 计划只改 3-5 个文件，但 Ralph 报 E_CRITICAL_ENTRYPOINT_UNOWNED 对全局 entrypoints（如 daemon/server.py、cli/main.py、ralph/validator.py）。当前只能用 `suppress_codes: ["E_CRITICAL_ENTRYPOINT_UNOWNED"]` 整类抑制，会同时抑制该 plan 真正遗漏的 entrypoint
- **根因**：Ralph 没有"plan scope"概念，_check_critical_coverage 对所有 critical entrypoints 一视同仁，只用"是否 touch 该 subsystem"做 hint 降级，但粒度不够
- **改进方案**：（a）引入 `plan_scope: ["src/cccc/daemon/foreman/", "src/cccc/contracts/"]` 声明，Ralph 只检查 scope 内的 critical entrypoints；或（b）改用 per-instance suppress：`suppress: [{code: "E_CRITICAL_ENTRYPOINT_UNOWNED", path: "src/cccc/daemon/server.py"}]`
- **验收标准**：聚焦 plan 无需整类 suppress 即可通过 validate；scope 内遗漏的 entrypoint 仍报 error
- **触发实例**：batch-a-monitor-foundation.yaml 和 batch-c-assignment-protocol.yaml 都需要 suppress 3 个 code

### RO-14n W_FLOW_OWNER_NO_VERIFICATION 对 leaf 角色噪音过大（P2）
- **严重度**：Low — 每个 leaf × flow 组合产生一条 warning，两个 plan 共 15+ 条
- **现象**：T1(leaf) claim 了 workflow_monitor.py（flow entrypoint），Ralph 报"T1 claims entrypoint but doesn't verify the flow"。但 flow 验证是 T3(integration) 或 T5(verification) 的职责，leaf 任务不应被要求验证 flow
- **根因**：_check_flow_segment_ownership 不区分任务 role，对所有 claimed entrypoint 的任务一律检查 flow 验证
- **改进方案**：当任务 role=leaf 且存在 role=integration/verification 的任务覆盖该 flow 时，降级为 hint
- **验收标准**：leaf 任务不再因"不验证 flow"产生 warning（前提是有 integration/verification 任务覆盖）
- **触发实例**：Batch A 的 T1/T4（leaf）和 Batch C 的 T1/T2（leaf）均触发多条 W_FLOW_OWNER_NO_VERIFICATION

---

## 一-B、蓝图 v0.3 新增改进（Phase 5）

> 来源：2026-04-04 工作流蓝图 v0.3 对齐讨论
> 定位：架构偏移修复完成后落地蓝图新增能力，对应优化路径方案 v5.2 Phase 5

### RA-1 Ralph Agent 层实现（P5，蓝图 §3.1/3.4）
- **严重度**：Medium — 蓝图核心新增能力，补强 Ralph 已知的语义校验局限
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

## 二、已知局限（NOTE 类，无代码改进空间）

> 📋 蓝图 v0.3 新增：标注"🤖 Agent 可覆盖"的条目将作为 Ralph Agent 的首批审查目标（RA-1/RA-2），
> 纳入"超出范围检查项清单"（蓝图 §3.5）。

| 编号 | 观察 | 说明 | Agent |
|------|------|------|-------|
| RV-15 | Ralph 新规则自身的 bug 无法自检 | 印证 findings #13：结构校验和代码审查互补 | 🤖 可覆盖 |
| RV-18 | goal_behavior 中引用的函数名可能不存在 | 超出结构校验范围，需 Codex 审查 | 🤖 可覆盖 |
| RV-19 | 模型扩展可能破坏已有语义（awareness_paths 案例） | Codex 审查发现，已在实施中正确处理 | 🤖 可覆盖 |
| RV-20 | monitor wiring 调用位置可行性无法静态验证 | TaskEvent 类型受限，已改为公共 API 方案 | 🤖 可覆盖 |
| RV-21 | accumulator 重构易引入分类回归（conftest 案例） | Wave 6 手动修复，提示需完整回归测试 | — |
| RV-22 | W_UNCLAIMED_TEST_FOR_SOURCE 对高 import 文件产生大量警告 | RV-10 indirect→hint 已缓解 | — |
| RO-5n | W_FLOW_SEGMENT_UNOWNED 对 verification role 的 T-int 类任务过度报警 | T-int 天然覆盖所有 flow 但不 claim 入口，应考虑 verification role 豁免 | — |
| RO-6n | 同一 entrypoint 被多个 flow 使用时 W_FLOW_OWNER_NO_VERIFICATION 噪音大 | T3/T4/T5 共享 validator.py 但各自只验证自己的 flow，触发大量 NO_VERIFICATION | — |
| RO-10n | verification 命令强度无法检测连接级/运行时语义 bug | v4 pytest 全过但 SQLite FK 未启用；印证 findings #13 结构校验和代码审查互补 | 🤖 可覆盖 |
| RO-11n | 计划中"删除函数"的副作用链无法静态检测 | Batch C Codex 审查发现：删除 _fallback_to_group_actors 后 rejected batch 仍走 on_batch_started 等副作用，Ralph 无法建模函数内控制流 | 🤖 可覆盖 |
| RO-12n | 同一文件多入口只覆盖部分时 Ralph 不报警 | Batch C Codex 发现：plan 修改了 process_batch_suggestion 但遗漏了 register_and_suggest 这条绕过入口，Ralph 的 claimed_paths 是文件级不是函数级 | 🤖 可覆盖 |
