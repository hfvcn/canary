# CCCC 问题清单 v5 — Ralph 改进专项（Full 版，v36 起）

> 历史归档（v1-v35）：[问题清单-v5-ralph-full-v1.md](./问题清单-v5-ralph-full-v1.md)
> 短版（仅未解决）：[问题清单-v5-ralph.md](./问题清单-v5-ralph.md)

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
