# CCCC 问题清单 v5 — Ralph 改进专项（Full 版，v36 起）

> 历史归档（v1-v35）：[问题清单-v5-ralph-full-v1.md](./问题清单-v5-ralph-full-v1.md)
> 短版（仅未解决）：[问题清单-v5-ralph.md](./问题清单-v5-ralph.md)

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
