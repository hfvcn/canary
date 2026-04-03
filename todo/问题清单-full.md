# CCCC 工作流问题清单 v3

> 日期：2026-03-29，更新：2026-04-03
> 状态：能力扩展（E-1/E-2/E-3/M-2）已完成。两轮 E2E 实战暴露工作流执行闭环缺口。
> 历史版本：问题清单-v2.md → 问题清单-v4.md（已归档）
> 另见：问题清单-v5-ralph.md（Ralph 改进专项）、e2e-实战评估规范.md（实战流程规范）

---

## 当前状态总结

经过 v4 修复、v3 架构优化、能力扩展（E-1/E-2/E-3/M-2）、以及两轮 E2E 实战测试（v1/v2），系统状态：

- **已解决（v4 归档）**：Ralph 闭环跑通、CLI 成为主路径、verify gate 可达、agent pool fallback 可用
- **已解决（v3 架构优化）**：A-1 状态迁移收敛、A-3 Prompt 源收敛、A-2 project_root 元数据化、M-1b 适配层统一、W-1 共享合约、W-2 进度推送
- **已解决（能力扩展，2026-04-01）**：E-1 验证分层、E-2 模型注册表驱动分配、E-3 Context Rollover、M-2 非核心 CLI parity
- **待解决（E2E 实战暴露）**：工作流执行闭环 3 个 P0（plan→engine 元数据传递、自动任务下发、DAG 门控）+ 可观测性/一致性 P1-P2

---

## 一、已解决（v4 归档，不再跟踪）

| 编号 | 问题 | 解决方式 | 验证 |
|--------|------|----------|------|
| R-1 | Ralph 功能对 Foreman 不可达 | system_prompt/help/capability/preamble 全部改为 CLI-first | test5 E2E |
| R-2 | Verify gate 从未触发 | apply_task_event → verify_completion → 状态推进 | test5 E2E |
| R-3 | Daemon 不初始化 RalphService | 所有 IPC handler/HTTP route/ralph_service 补齐 project_root | 6 integration tests |
| M-1a | 核心工作流绑定 MCP（默认路径） | CLI 命令覆盖 + prompt 引导 + MCP 降级为 (MCP) 标记 | 11 prompt tests |
| WF-NEW-1 | Workflow submit 后 task 停在 ready | auto_process 默认 True + READY 拒绝消息 + ASSIGNED 自动迁移 | test5 E2E |
| WF-NEW-4 | Agent pool 匹配失败 | fallback to group actors + peer 角色 30 分 | test5 E2E |
| BUG-01~04 | workflow/progress 数据管线 | resolve_group_runtime_context + kind/snapshot | 第二轮确认 |
| KB-BUG-01~03 | Board/Workspace Tab 不显示 | Tab registry + container | 第二轮确认 |
| WF-01 | 被 stop 的 Actor 自动恢复 | admin_hold + desired_state 三层状态 | 第二轮未复现 |
| WF-03 | 并行 Worker 竞态条件 | Foreman 明确依赖顺序 + 文件范围划定 | 第二轮未复现 |
| A-1 | 状态迁移权威收敛 | WorkflowTaskOps 6 个 canonical 函数，CLI/HTTP/IPC 全部委托 | test6 E2E + 8 集成测试 |
| A-2 | project_root 提升为 group 元数据 | group.doc["project_root"] 在 attach/switch/detach 自动维护 | test6 E2E + 8 集成测试 |
| A-3 | Prompt 源收敛 | workflow_guidance.md 单一权威源，4 文件引用不重复 | 7 集成测试 + 20 prompt 测试 |
| M-1b | 适配层统一 | adapter_helpers.py 共享 helpers，CLI local fallback 已删除 | 6 集成测试 + 28 helpers 测试 |
| W-1 | 共享类型合约 | Contract schema 校验 W_CONTRACT_SCHEMA_MISMATCH | 7 schema 测试 |
| W-2 | Worker 进度推送 | cccc task heartbeat + stall detection + foreman auto-notify | test6 E2E + 8 集成测试 |

---

## 二、已解决 — 能力扩展（2026-04-01 完成）

> 来源：docs/superpowers/specs/2026-03-19-ralph-foreman-workflow-design.md
> 实施：plans/capability-expansion.yaml（8 tasks, 1357 tests passed, 0 new regressions）

| 编号 | 功能 | 实现 | 验证 |
|------|------|------|------|
| E-1 | 验证分层（multi-check） | VerificationCheckSpec + checks[] 执行 + 逐项报告 | 64 tests + E2E ralph verify |
| E-2 | 模型注册表驱动分配 | weaknesses/rating/context_window/best_for 评分 | 9 tests |
| E-3 | Context Rollover | TaskContext 持久化 + _build_task_prompt 注入 | 12 tests |
| M-2 | 非核心 CLI parity | cccc capability/memory/coordination/agent-state | 6 tests |

**E2E 实战发现**：E-1/E-2/E-3 代码层面已实现，但实战中未被触发——根因是 plan→engine 元数据未传递（见第五节 WF-1）。

---

## 三、已解决 — MCP 替代剩余

### M-2 ✅ 非核心 MCP 工具 CLI parity（2026-04-01 完成）
- cccc capability / cccc memory / cccc coordination / cccc agent-state 四个 CLI 命令已实现

### M-3 不同 Runtime 对 MCP 的可靠性差异
- **严重度**：Low（CLI 成为主路径后影响降低）
- **缓解**：CLI 作为主路径已消除对 MCP 的依赖

---

## 四、待解决 — 工作流执行闭环（E2E 实战暴露）

> 来源：e2e-v1-vs-v2-对比报告.md + e2e-实战评估规范.md (FIX-1~FIX-5)
> 评审：2026-04-02 Claude + Codex 讨论，逐项归类

### WF-1 plan→engine 元数据传递（P0）
- **严重度**：Critical — 导致 E-1/E-2/E-3 的实现在实战中全部失效
- **现象**：`cccc workflow submit` 提交的 JSON 不传递 plan.yaml 的 `claimed_paths`（变成 `[]`）、`verification.checks`（verify gate 直接 skipped）、`provides/consumes`、`goal_behavior` 等扩展字段
- **影响**：Foreman 写了合格的 plan.yaml（精确路径、多步验证、契约声明），但 engine 运行时完全不知道这些信息。计划层改善无法在执行层生效
- **实例**：v2 实战 plan.yaml 声明 `claimed_paths: ["backend/"]`，task_registered 事件中变成 `[]`；`verification.checks` 有 compile+test，但 verification_passed 显示 `skipped, checks: []`
- **改进方案**：支持 `cccc workflow submit --plan plan.yaml` 直接读取 plan 文件，或扩展 TaskRef 解析逻辑传递所有 plan 字段

### WF-2 引擎自动下发任务给 Worker（P0）
- **严重度**：Critical — 80% 手工编排的直接原因
- **现象**：batch_approved 后，engine 把任务标记为 running 但不向 worker inbox 发送任何消息。Foreman 被迫手工撰写任务描述并 `cccc send` 给每个 worker
- **影响**：工作流从"自动编排"退化为"手工消息中继"，Foreman 大部分精力花在格式化和转发任务说明上
- **实例**：v1 和 v2 共 11 个任务全部由 Foreman 手工 `cccc send` 转发。v1 Foreman："Workers received no messages in their inbox after workflow submission"
- **改进方案**：`_start_assigned_agents()` 中创建 actor 后自动发送结构化任务 prompt（goal_behavior + acceptance_criteria + claimed_paths + verification 信息）到 worker inbox

### WF-3 改 batch 门控为 DAG 门控（P0）
- **严重度**：High — 导致 ready 任务被无关的 batch 边界阻塞
- **现象**：一个 batch 中任何任务未完成，下一个 batch 的所有任务都被 deferred，即使它们的 depends_on 已满足
- **影响**：当 batch 内某个 worker（如 Codex）卡住时，所有不依赖它的下游任务也被阻塞。Foreman 被迫绕过引擎直接发任务
- **实例**：v2 实战 T3 依赖 T1（已完成），但因为 T2（Codex 卡死）还在 batch 1 中，T3 一直是 deferred。Foreman："The batch gating logic should be dependency-aware, not batch-aware"
- **改进方案**：per-task readiness 检查。任务完成时检查解锁的下游任务（depends_on 全满足 + claimed_paths 无冲突），立即标记 ready 并分配

### WF-4 plan.yaml 与实现语义对齐（P1）
- **严重度**：Medium — 计划描述和代码实现字段名不一致
- **现象**：plan.yaml 写 `target_column_id`，实现用 `column_id`。Ralph validate 无法检测这类语义不匹配（结构上是合法的）
- **实例**：v2 Codex 代码审查发现 plan.yaml:86 的 move endpoint 描述与 schemas.py:52 / types.ts:24 的实现不一致
- **改进方案**：在 Foreman prompt 或工作流指南中强调"plan 中的字段名必须与实现一致"；长期考虑 Ralph 基于 AST 的语义检查

### WF-5 context.sync 编号碰撞（P2）
- **严重度**：Low — 影响可追踪性但不影响功能
- **现象**：不同 batch 的任务被 context.sync 写成相同的 T001/T002 编号
- **实例**：v2 日志分析发现两次 context.sync 事件把不同任务映射到 T001/T002
- **改进方案**：context.sync 使用 workflow task_id 而非自增序号

### WF-6 子 agent 创建与任务归属管控（P1）
- **严重度**：Medium — Foreman 绕过工作流创建临时 worker 和自行完成任务，导致实际执行与计划脱节
- **现象**：Foreman 可自行 `cccc actor add` 创建计划外 worker，可用 `cccc task complete` 直接报告完成（Foreman 角色应该是协调者而非执行者），任务完成者与分配者不匹配
- **影响**：工作流引擎记录的分配关系与实际执行不一致，无法追溯"谁真正做了什么"。Ralph 运行时监控（v5 WF-NEW-3）可以检测这些偏差，但引擎侧也需要策略：是允许但记录，还是拒绝非分配 agent 的完成报告
- **实例**：v2 T2 分配给 frontend-worker，由 planner 完成；T5 分配给 claude-general-worker-1，由 backend-worker 完成。Foreman 创建了 2 个计划外 worker
- **改进方案**：engine 对 `task_reported_completed` 检查 agent_id 是否与分配一致，不一致时发 `verification_warning` 事件（不阻塞，但记录偏差）。Foreman prompt 中增加"不应自行执行任务"的约束

### WF-7 duration_seconds 全零（P2）
- **严重度**：Low — 无性能数据用于分析和估算
- **现象**：所有 completed 事件的 duration_seconds 报 0，与实际执行时间不符
- **实例**：v1 和 v2 共 11 个任务全部 duration_seconds=0，实际墙钟时间 35s~500s
- **改进方案**：task_started 事件记录时间戳，task_completed 时计算差值

---

## 五、Ralph 改进(长期循环迭代)

独立跟踪：**`todo/问题清单-v5-ralph.md`**

包含：
- 5 类 validate 盲区修复（假验收命令、漏 claim 测试、虚假覆盖声明等）
- 运行时 agent 行为监控（WF-NEW-3）— E2E 实战新增证据（FIX-4 stall detection, runtime_state 矛盾）
- **注册不变量检查 RO-5**（v3 E2E 暴露，通用 producer→registry→consumer 三角检查）
- **verification 事件语义修正**（FIX-5）— E2E 实战新增：skipped 不应发 verification_passed
- Flow segment ownership / Schema 契约匹配（v3 已实现基础版）/ Role-based rules / Ready 排序

---

## 六、已归档的设计规格功能

> 来源：docs/superpowers/specs/2026-03-19-ralph-foreman-workflow-design.md
> 评审：2026-04-01 Claude + Codex 讨论

| 功能 | 决定 | 理由 |
|------|------|------|
| Git 提交元数据协议 (2.2) | **归档** | 所有数据已走 IPC + ledger，Git 再承载是第二事实源，状态分叉风险 |
| git_watcher.py (2.1) | **归档** | 比 daemon 事件更慢更间接，旧残留代码不在主链 |
| Reviewer 角色 (3.4) | **推迟** | Ralph verify gate + Foreman 判断已覆盖，插 AI reviewer 增加延迟和成本 |
| ralph_query automation (6.3) | **归档** | 核心用例（stalled → notify）已内建在 orchestrator，automation DSL 绕路无新能力 |

---

## 七、观点与原则

- **静态正确不等于运行时可用** — 验证的最低标准是"路径能走通"
- **正确的并行单元是功能切片** — 不是文件，验收标准是"接口行为正确"
- **验证先行** — 先有 E2E 验证命令，再以通过为标准
- **经验证的工作流程** — 计划生成 → Ralph 验证 → Codex 审查 → Ralph 不足记录 → 并行执行 → 实测（详见 findings.md）

---

## 八、已修复（v4 E2E 验证生效，2026-04-03）

| 编号 | 问题 | 修复方式 | v4 证据 |
|------|------|---------|---------|
| WF-1 | plan→engine 元数据传递 | IPC handler 直接传 raw dict | task_registered 含 goal_behavior/verification/provides/consumes |
| WF-2 | 引擎自动下发 | daemon op=send fallback + 状态回滚 (FIX-8) | Worker 收到 `[Foreman Assignment]`，零手工 cccc send |
| WF-3 | batch→DAG 门控 | atomic register_and_suggest + task_ref 持久化 (FIX-6) | 3 批次 [T1,T2]→[T3]→[T4]，依赖完成后秒级触发 |
| WF-4 | plan.yaml ↔ 实现字段对齐 | TaskSpec.to_task_ref() + type 字段 | --plan 一键提交 |
| WF-5 | context.sync 编号碰撞 | 支持 workflow_task_id | context.sync 使用 workflow_task_id |
| WF-6 | 子 agent 归属管控 | completer_mismatch→ledger | T3/T4 触发 verification_warning |
| WF-7 | duration_seconds 全零 | ev[key]=val 替代 setdefault (FIX-7) | setdefault 已替换 |
| FIX-6 | --plan 全量提交 | atomic ralph_register_and_suggest daemon op | DAG 门控 3 批 |
| FIX-7 | duration_seconds 被覆盖 | ev["duration_seconds"] = computed | setdefault 已替换 |
| FIX-8 | Worker PTY 不消费 inbox | _daemon_request_fn op=send fallback + 状态回滚 | Worker 自动收到任务 prompt |
| FIX-10 | 任务分配不匹配 Worker 能力 | _infer_domain_from_paths + 评分 +25/+10 | T1→backend-worker, T2→frontend-worker |

## 九、架构偏移修正（ARCH 系列，2026-04-03 新增）

> 背景：v4 实战后通过 Codex 代码调查 + 文档对比分析发现的设计偏移。
> 详见：[设计偏移发现记录.md](./设计偏移发现记录.md)

**关闭条目**：
- FIX-14（Batch 1 worker 自动创建）—— 基于对设计的误解关闭。Foreman 自主创建合适 worker 是正确行为。真正的问题是 ARCH-1（submit 无 assignment 字段）和 ARCH-3（re-suggest 绕过 Foreman）。
- FIX-12（SQLite FK）—— 确认为 E2E 实战项目的 bug，非本项目代码缺陷，关闭。

**新增条目**（详细说明见 `问题清单.md` ARCH 系列）：

| 编号 | 问题 | 严重度 | 代码位置 |
|------|------|--------|---------|
| ARCH-1 | workflow submit 无 assignment 字段 | P0 | `ralph_ipc.py:103-188`, `workflow_cmds.py:147` |
| ARCH-2 | _fallback_to_group_actors() 静默覆盖 | P0 | `workflow_orchestrator.py:397-435` |
| ARCH-3 | _resuggest_ready_tasks() 绕过 Foreman | P1 | `workflow_orchestrator.py:1103-1151` |
| ARCH-4 | WorkflowEngine 缺 assignment 存储 | P1 | `workflow_state_types.py:39-50` |
| ARCH-5 | cccc actor add CLI 缺 --worker-prompt | P2 | `actor_cmds.py:92-108` |
| ARCH-6 | assignment_id/actor_run_id 管道中丢失 | P2 | `ralph_ipc_handler.py:871`, `workflow_task_ops.py:109` |
| ARCH-7 | DEFERRED 状态只在影子状态 | P2 | `workflow_orchestrator.py:64/556` |
| ARCH-8 | retry_after_verification() 不清空 agent_id | P2 | `workflow_state_engine.py:153-161` |

## 十、后续优先级

1. **架构偏移 P0** — ARCH-1 submit 加 assignment > ARCH-2 删除静默 fallback
2. **调度层 P1** — FIX-11 daemon 只恢复 active group > ARCH-3 re-suggest 通知 Foreman > ARCH-4 assignment 进 engine > FIX-13 plan.yaml state 回写
3. **基础设施 P2** — ARCH-5 actor add --worker-prompt > ARCH-6 assignment_id 传递 > FIX-15 validate ledger 事件 > ARCH-7/8
4. **Ralph 改进** — 详见 [问题清单-v5-ralph.md](./问题清单-v5-ralph.md)

---

## 十、附录：测试环境

| | 第一轮 (03-28) | 第二轮 (03-29) | 第三轮 (03-30) | 第四轮 (03-31) | 第五轮 (03-31) | 第六轮 (04-01) |
|---|---|---|---|---|---|---|
| 项目 | LinkVault | Kanban | test3 | test4 | test5 | test6 |
| 结果 | Ralph 死代码 | 闭环未接通 | prompt 不稳定 | 状态机通，pool 失败 | **全流程跑通** | **v3 架构优化验证通过** |
| 修复阶段 | — | — | Phase 1 | Phase 2 | Phase 2b | v3 (20 task) |
