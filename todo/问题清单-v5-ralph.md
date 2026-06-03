# CCCC 问题清单 v5 (未解决) — Ralph 改进专项

> 日期：2026-04-04（v5.2 蓝图对齐更新）
> 已完成（E2E 验证通过）：RO-7n/12/13n/14n/15/16/17/18/19/20/21/22/23/24/25/26/27/28/29/30/32/33/34/35/37/38/39/40/41/42/43/44/47/48/49/50/51/52/54/55/72、RA-1/2/3/4、RF-1/2/3/4/5、RL-3/5
> 已完成（v24 确认）：RO-61（structural digest）
> 已完成（v26 确认）：RO-62（force-complete→verification_skipped）/RO-69（CORS 验收标准+集成测试双重拦截）
> 已完成（v28 确认）：RO-51（scope 目录匹配）/RO-52（Gemini JSON）/RO-70（prompt 引导零命令变形）/RO-73（claude runtime 零 stall）
> 已完成（v29 计划审查确认）：RO-57（resubmit reject, 12 tests）/RO-65（challenge degradation, 4 tests）/RO-67（--compact, 14 tests）/RO-68（cleanup_patterns, 5 tests）/RO-71（completer_mismatch verification, 4 tests）
> 已完成（v30 代码修复）：RO-74/RO-75/RO-76、RL-21、BP-1/BP-3
> 已完成（v31 代码修复）：RO-77/RO-78/RO-79、BP-2/BP-4/BP-5
> 已完成（v32 E2E 验证）：RO-77 ✅/RO-78 ✅/BP-2 ✅/BP-4 ✅
> v34 计划分析确认已修复：RO-80/RO-81/UX-2
> 代码已修复，场景未触发（迁入 full 归档）：RO-45/46/53/56/58/59/60/63/64、RL-11
> 已完成（v36 代码修复）：RO-82/83/85/86、UX-1/4/7/9、AD-5/6、FL-1/3、RL-23/24
> 已完成（v38 E2E 验证）：RO-103
> 已完成（v39 代码修复，全量 42 项）：RO-84/89/90/91/92/93/94/95/97/98/99/100/101/102、FL-4/5/6/7/8/9/10/11/12/13/15、UX-5/8/11/12、AD-1/2/3/4/7/8/9/11、SL-1/2/3、RL-22/25、PLR-1/2、DOC-1/2、REG-1/REG-2
> 已验证（v39 E2E 确认）：AD-1~3（Aegis discipline 规则实战生效）、RO-84（validate ledger 事件确认）
> v39 新发现：FL-17b（solve flow state.json 清除仍未生效）/FL-18（step-6 归档迁移应为 blocking 非 advisory）/UX-13（foreman 未在 workflow.completed 后自动生成 evaluation）/UX-14（T1 冷启动 stall 300s+ 需放宽首任务阈值）
> 已完成（v40 代码修复）：FL-17b/FL-18/FL-16/PLN-1/UX-14/UX-13 + Codex 审查追加修复 _check_cleanup TimeoutExpired + advisory print 残留清理
> 已验证（v40 E2E 确认，归档至 full）：RO-96/E2E-1/E2E-2/E2E-3（相对路径 attach + challenge mode + temporal_pattern）
> v40 新发现（共 10 项）：RO-104（合同漂移检测）/RO-105（token type 混用漏检）/RO-106（temporal_pattern 只查声明不查集成）/RO-107（foreman 自评不一致）/FL-20（**P1** flow 表述+内容指导+check 机制三重缺陷）/RV-1（task 职责重叠）/RV-2（covers.tasks 满足 glue）/RV-3（race TOCTOU 深度）/UX-16（**P1** actor 崩溃 4 次）/UX-17（scrollback 丢失）
> v41 新发现（共 4 项）：FL-21（**P1** Codex check 伪造 JSON 蒙混）/FL-22（**P1** solve step-4 gap check 只查形式）/RV-4（validate 不检测 goal 引用文件未 claim）/RV-5（validate 不比对 acceptance 与 issue 覆盖度）
> v41 代码修复（12 项）：FL-20/FL-21/FL-22/FL-14/UX-16/UX-17/RO-104/RO-105/RO-106/RO-107/RV-1/RV-2
> 已验证（v42 solve flow 确认，归档至 full）：FL-14（并行 dispatch + skill 引导生效）/FL-22（step-4 gap check 要求 #### 标题+关键词匹配）/RV-3/RV-4/RV-5/RO-99/AD-11/FL-19/E2E-4
> v42 未生效：FL-21（HMAC 签名——CODEX_BRIDGE_SECRET 未配置，所有 JSON 验证回退到 UUID 格式检查）
> 代码已修复，场景未触发（迁入 full 归档）：RO-104/105/106/107、RV-1/2、UX-15/16/17
> v42 新发现（共 5 项）：FL-23（**P1** step-4 gap recording 指导不足，agent 记录无价值内容）/FL-24（step-5 未禁止直接编辑）/RV-6（validate 不检查 plan 前提与代码一致性）/RV-7（validate 不检查 claimed_paths 是否为真实控制层）/RV-8（validate 不检查算法对目标数据可行性）
> 已完成（2026-05-24 代码修复，5 项）：FL-23/FL-24/RV-6/RV-7/RV-8
> Codex review 发现（共 2 项）：RV-9（validate 不检测 check 注册到错误 phase）/RV-10（validate 不检测 plan 中描述的实现方案与现有代码重复）
> flow 执行漏洞发现（共 2 项）：FL-25（**P1** step-5 check 可被手写 JSON 绕过）/FL-26（step-5 不验证 git diff 与 Codex session 对应关系）
> 已完成（2026-05-24 代码修复，4 项）：FL-25/FL-26 + codex_bridge 路径解析 + instruction 动态注入完整路径
> 已完成（2026-05-24 代码修复）：FL-20/FL-21 — HMAC 签名全链路打通（codex_bridge.py 签名 + .env secret 配置 + flow_engine 从 .env 读取 + 未签名 JSON 强制 FAIL）
> 已知局限（归档至 full）：RV-9/RV-10/RV-11（语义级检查超出结构验证范围）
> 验证轮次（2026-05-24 修复后）：全量 pytest 2992 passed / 0 failed / 120 skipped
> 验证轮次（2026-05-20 v42 修复后）：全量 pytest 2978 passed / 0 failed / 120 skipped（+24 新测试）
> 验证轮次（2026-05-20 v41 修复后）：全量 pytest 2954 passed / 0 failed / 120 skipped
> 验证轮次（2026-05-17 v39 修复后）：全量 pytest 2913 passed / 0 failed / 120 skipped
> E2E v28 验证：综合 4.2/5（结果 3/5，过程 5/5，体验 4.5/5）
> E2E v29 验证：综合 3.3/5（结果 2/5，过程 4/5，体验 4/5）
> **E2E v32 验证：综合 4.3/5（结果 4/5，过程 5/5，体验 4/5）——历史新高**
> E2E v33 验证：综合 4.0/5 | E2E v34 验证：综合 3.7/5 | E2E v35 验证：综合 2.3/5 | E2E v35b 验证：综合 3.3/5
> E2E v36 验证：综合 4.0/5 | E2E v37 验证：综合 3.3/5 | **E2E v38 验证：综合 4.2/5**
> **E2E v39 验证（2026-05-17，FastAPI Bookmark Service）：综合 4.3/5（结果 4.5/5，过程 4.5/5，体验 4/5）——历史并列最高**
> E2E v40 验证（2026-05-19，Flask OAuth2 Resource Server）：综合 3.7/5（结果 3.5/5，过程 4/5，体验 3.5/5）
> **E2E v41 验证（2026-05-24，FastAPI Notes Service）：综合 3.8/5（结果 4/5，过程 3.5/5，体验 4/5）**
> v41 新发现（共 6 项，已全部归档至 full）
> **E2E v42 验证（2026-05-24，FastAPI Blog Platform）：综合 4.3/5（结果 4.5/5，过程 4/5，体验 4.5/5）——历史并列最高**
> v42 E2E 新发现（共 5+6+3+3 项）：RO-112/FL-29/FL-30/FL-31/RO-113 + 会话回顾：FL-32/FL-33/FL-34/FL-35/FL-36/FL-37 + 并行度/runtime 分析：FL-38/FL-39/FL-40 + agent 架构：FL-41/FL-42/FL-43
> 全量版本：[问题清单-v5-ralph-full.md](./问题清单-v5-ralph-full.md)
> **E2E v47 验证（2026-05-24，FastAPI 用户管理 + JWT 认证）：综合 4.0/5（结果 3.5/5，过程 4.5/5，体验 4/5）**
> v47 已验证生效：FL-40/43（模型选择双路径）、FL-38（auto-dispatch）、FL-31/39（负载均衡+并行度）、RO-113（JWT 默认密钥）、RO-112（FTS5 CJK）、FL-32（state HMAC）
> v47 新发现（共 5 项）：FL-44/FL-45/FL-46/FL-47/UX-18
> 评估报告：[e2e-实战评估报告-v51.md](./e2e-实战评估报告-v51.md)（最新）| [v50](./e2e-实战评估报告-v50.md) | [v48](./e2e-实战评估报告-v48.md) | [v47](./e2e-实战评估报告-v47.md) | [v42](./e2e-实战评估报告-v42.md) | [v41](./e2e-实战评估报告-v41.md) | [v40](./e2e-实战评估报告-v40.md) | [v39](./e2e-实战评估报告-v39.md)
> 已完成（2026-05-24 v46 代码修复，10 tasks）：FL-32/FL-33/FL-35/FL-36/FL-34/FL-37/FL-29/FL-40/FL-43/RV-12/RV-13/RV-14/FL-30/FL-31/FL-38/FL-39/FL-41/RO-112/RO-113
> 部分完成（guide-only，flow 步骤未实现）：FL-42（评价闭环——guide 已加，retrospective step 已补入 v47）
> 验证轮次（2026-05-24 v46 修复后）：全量 pytest 3042 passed / 0 failed / 120 skipped（+50 新测试）
> v46 Codex review（6 轮，2→2→3→3→4→4，明确批准实现）发现（共 3 项）：RV-15/RV-16/RV-17
> **v48 solve flow（2026-05-30）**：本批修复 FL-46/FL-45/FL-47/FL-33/UX-18（5 项，6 tasks，validate 规则 + flow check 强化）。
> v48 Codex review（plan-correctness + capability-gaps 双路）修订：删 RV-15（已实现 `_check_goal_symbol_in_claimed_paths`）、RV-16（guide 640-659 已说明 assignment-map 绕过，确认已解决）、FL-44（与 `W_VERIFICATION_PYTHON_IMPORT_OPAQUE` 重叠，记为已知局限）。
> v48 capability-gaps review 新发现 4 项 validate 检测能力缺口（见下）。
> **E2E v48 验证（2026-05-30，FastAPI RBAC 任务协作平台）：综合 3.5/5（结果 3.5/5，过程 3.0/5，体验 4.0/5）** —— 报告：[e2e-实战评估报告-v48.md](./e2e-实战评估报告-v48.md)
> v48 E2E 已验证生效（详情已删短版、归档至 full）：**FL-33**（step-4 secret_preflight + 应用无 JWT 默认密钥）。codex_bridge HMAC 签名链路与安全敏感流自动创建非执行者 sec-reviewer 角色亦已 v48 归档、v49 复确认（详见 full 归档段落）。
> v48 E2E 部分生效（结构闸门已建但实质可绕过，残留转 RV-22/FL-50/UX-18b）：**FL-46**（validate 0 error 但运行代码 `POST /projects` 无角色门禁）、**FL-47**（默认顺序测试全绿但 `test_config` reload 致 `test_auth` 反序 2 failed）、**UX-18**（必需章节齐全但全为"待补充"占位符仍通过闸门）
> v48 E2E 新发现（共 7 项）：UX-18b/FL-48/FL-49/RV-22/FL-50/UX-19/**FL-51**（flow step-6 不强制把确认修复的条目从短版归档——本轮亲历）（见下）
> **v49 solve flow（2026-05-30）**：本批修复 RV-18/RV-19/RV-20/RV-21（4 项 validate 检测能力缺口 → 5 tasks）。step-3 双路 Codex 审查（plan-correctness + capability-gaps，均 HMAC 签名）：plan-correctness 修订 RV-18 谓词（删「required check 命令须非空」误判，runtime 空命令 check outcome=error+required 仍 gate）、RV-21 provider 去重（按 task_id）；capability-gaps 新发现 6 项 validate 漏检（RV-23~28，见下）。
> **E2E v49 验证（2026-05-30，FastAPI 文档管理平台 RBAC+分享）：综合 3.0/5（结果 2.5/5，过程 3.5/5，体验 3.0/5）** —— 报告：[e2e-实战评估报告-v49.md](./e2e-实战评估报告-v49.md)
> v49 E2E 复验 v48 衍生项：**FL-45** ✅仍生效（建 codex sec-reviewer 非执行者）；**RV-22** 文档/分享写端点三重校验正确+IDOR 404 掩蔽（但 validate 仍漏「身份获取面」→ RV-29）；**UX-18b** ⚠️改善（完成时 698B 占位符，foreman 5min 后补成 8125B 实质内容，但结构闸门仍不查占位符）；**FL-49** ⚠️部分（reviewer 实质参与但 plan.yaml 无 reviewer 节点/`W_AGENT_REVIEW_SKIPPED` 被压制/git 零提交，且漏检致命 bug）；**FL-50** ⚠️部分（函数级隔离好，但集成测试复用全局 app+限流中间件有隐藏共享态）；**FL-48** ⚠️未闭合（T7 override 仅自由文本笔记，plan 最终状态漏记 T7、state.json 无 override 记录）；**UX-19** 本轮未触发（测试采集正常 122 条）。
> v49 E2E 新发现（共 6 项）：**RV-29**（🔴致命，注册自带 role 提权击穿 RBAC，validate/verify/审查/全量回归全放行）/**FL-52**（`W_AGENT_REVIEW_SKIPPED` 可被 suppress_codes 静默压制）/**FL-53**（validate 判定随文件系统状态漂移）/**FL-54**（全量回归门×计划内 override 用例=死结无预警）/**UX-20**（stall 心跳误报，task 级不随产出刷新）/**UX-21**（指南 `cccc model rate` 不存在，CLI 仅 `cccc model review`）（见下）。
> **v50 solve flow（2026-05-31）**：本批全量修复 tracker open 项 18 项 → 17 tasks（RV-22~29 八条 validate 规则 + FL-48/49/51/52/53/54 + UX-18b/19/20/21）。step-3 双路 Codex 审查（plan-correctness + capability-gaps，均 HMAC 签名）：plan-correctness（verdict=revise，conf 4/5）修订 13 个 task 的规格错误（scope helper 复用 `_entrypoint_in_scope`、FL-53 改新码 `W_FLOW_COVERAGE_DEFERRED` 避开 suppress、RV-22/29 去重 `W_RBAC_FLOW_AUTH_UNVERIFIED`、FL-49 复用 `_task_has_independent_review_semantics`、FL-52 W_AGENT_REVIEW_SKIPPED 实际在 cli.py 分流、UX-19 区分 task 计数 vs 测试统计、UX-20 actor idle 源在 serve_ops、UX-21 handler 在 model_cmds.py、FL-48 决策点在 orchestrator）；capability-gaps（conf 4/5）新发现 3 项 validate 漏检（RV-30~32，见下）。
> 已完成（2026-05-31 v50 代码修复，17 tasks，归档至 full）：**RV-22/23/24/25/26/27/28/29、FL-48/49/51/52/53/54、UX-18b/19/20/21**。验证：全量 pytest 3174 passed / 0 failed / 120 skipped（+44 新测试），module-size 守卫复绿（validator.py 946<950、orchestrator 2495<2500，FL-52 helper 抽取至 `validation_rules/security.py` 共享）。
> 同批归档历史欠账（v49 已修但短版未删）：**RV-18/19/20/21**（v49 代码修复，本批补归档至 full，闭合 FL-51 亲历问题）。
> **E2E v50 验证（2026-05-31，团队密钥保管箱 API RBAC+注册登录+资源归属）：综合 3.5/5（结果 3.5 / 过程 3.0 / 体验 4.0）** —— 报告：[e2e-实战评估报告-v50.md](./e2e-实战评估报告-v50.md)
> v50 E2E 复验详情已归档至 full（RV-29 三层闭合、FL-48/54/UX-20/UX-18b 等）。
> v50 E2E 新发现 10 项已全部修复并归档（FL-55/FL-56/FL-57/FL-58/FL-59/FL-60/FL-61/FL-62/RV-33/UX-22→v51 修复→v51 E2E 验证→归档至 full）。
> v51 solve flow + 代码修复详情已归档至 full（13 tasks：RV-30/31/32 + FL-55/56/57/58/59/60/61/62 + FL-50 + UX-22）。
> 已归档至 full（已实现/已知局限）：RV-15/RV-16/RV-17/RV-33。
> 已验证并归档至 full（v51 E2E）：FL-55/FL-56/FL-58/FL-59/FL-60/FL-62/RV-30/UX-22 ✅；FL-57+FL-50/FL-61/RV-31/RV-32 场景未触发归档。
> **E2E v51 验证（2026-06-03，FastAPI 安全文件共享服务 JWT+RBAC+文件上传+分享链接+审计日志）：综合 4.0/5（结果 4.0 / 过程 4.0 / 体验 4.0）** —— 报告：[e2e-实战评估报告-v51.md](./e2e-实战评估报告-v51.md)
> v51 E2E 新发现（共 5 项）：FL-63/FL-64/FL-65/UX-23/RV-39（见下）
> **v52 solve flow（2026-05-31）**：本批修复 RV-34（1 项，3 tasks：非压制集+路径引用+集成验证）。step-3 双路 Codex 审查（plan-correctness + capability-gaps，均 HMAC 签名）：plan-correctness（verdict=revise，conf 5/5）修订 T2 coverage 旁路矛盾（删除 coverage token bypass、所有 structured check 须引用 signoff path）、T1 test 文件明确创建、AC2 用 _non_suppressible_codes 单元测试；capability-gaps（verdict=revise，conf 5/5）新发现 RV-38（已知局限：non-required check 可满足规则）、修订 RV-37 path source（从 claimed_paths+verification.command 双源提取）、修订 RV-35 grep 排除（grep 命令含 structured tokens 仍报 weak-check）。
> 已完成（2026-05-31 v52 代码修复，3 tasks）：**RV-34**（signoff 校验强化：不可压制集 + 路径引用 + grep 排除 + 集成验证，20 tests）+ RV-35/RV-37（v52 内修复）。
> v53 solve flow（2026-05-31）：本批全量实现 FL-42 + MSE-1~6 + AgentFlow M0~M6（22 tasks）。step-3 双路 Codex 审查（plan-correctness + capability-gaps，均 HMAC 签名）：PC 修订 16 项、CG 新发现 RV-41/RV-43b/RV-47（已知局限，3 项）+ 6 项一次性 plan 修正已合入。
> **本文档只保留未解决的改进项和已知局限。已完成条目与历史实现记录保存在 full 版本中。**

---

## 未解决改进项

### ~~RV-34~~（v52 代码修复：signoff 引用满足后实质校验缺失，3 tasks + 20 tests 通过）
> v52 T1（W_SIGNOFF_STRUCTURE_WEAK 加入不可压制集）+ T2（signoff check 须引用 signoff 路径 + grep 排除 + basename fallback）+ T3（集成验证）。

### ~~RV-33~~（已知局限，v51 归档至 full：弱加密语义不可结构检测）
> 归档：validate/test 无法区分 Base64 混淆与真实加密——语义级检查超出结构验证范围。

### v52 Codex review 新发现

#### RV-38（validate 不检测 non-required signoff check 满足规则）

`_signoff_checks` 不检查 `CheckSpec.required` 字段。task 可包含 `required: false` 的 structured signoff check，
该 check 不实际 gate 任务完成，但 `_has_structured_signoff_fields` 会认为结构化校验已满足。
已知局限：required=false 仍声明了校验意图，且实际 foreman workflow 中 required=false check
失败不阻塞但会在 evaluation 记录——风险较低。

> ~~RV-35~~（v52 代码修复，归档至 full）：`_has_structured_signoff_fields` 排除 grep/egrep/fgrep 开头的命令。
> ~~RV-37~~（v52 代码修复，归档至 full）：`_signoff_paths_from_task` 同时从 claimed_paths 和 verification.command 提取。

### v53 Codex review 新发现

> v53 双路 Codex 审查（plan-correctness + capability-gaps，均 HMAC 签名）：plan-correctness（verdict=revise，conf 4/5）修订 16 项 task 规格错误（T2 prompt 直写→候选生成、T8 lease 索引+explicit 验证、T9 claim workflow.py、T11 AttemptLink 需 node_id+prompt_version、T12 需 duration/outcome 指标、T5 复杂任务判定信号、T22 covers 扩展）；capability-gaps（verdict=revise，conf 4/5）新发现 9 项系统检测缺口（RV-39~47）。

#### RV-41（validate 不检测 AF node completion 绕过 VerificationGate）

AF `node_completed` 仅表示执行完成，但 CCCC 任务完成需要 VerificationGate 验证通过。
当前 validate 不检测 plan 中 AF engine 路径是否在 node_raw_completed → verification_requested →
VerificationGate → node_completed 之间有正确的 gating 声明。缺少此检测时，AF 成功和 CCCC
任务成功可能分歧——AF 认为 node 完成但 CCCC 验证未通过。
已知局限：需要 AF 引擎实际集成后才能进行结构化检测，当前阶段标记为待实现。

#### RV-43b（validate 不检测 agent prompt 直接变更绕过 promotion）

T2 原设计直接写入 `.cccc/agents/*.yaml` 的 prompt 字段，绕过 T14 的 TunedAgentVersion
promotion 安全机制。validate 应检测 plan 中是否有 task 直接 claim agent YAML 写入
而未声明对应的 promotion 流程依赖。此检测可防止未来 plan 回归到"直接变更 active prompt"模式。
已知局限：promotion 机制尚未实现（T13/T14），检测规则需在机制建立后添加。

#### RV-47（validate 缺少 AgentFlow/评价闭环新不变量检测）

v53 引入 AgentFlow 引擎切换、acquire/release 协议、评价闭环等新架构。
validate 目前没有检测以下不变量的规则：
1. AF/legacy 引擎不可静默回退
2. AF 补丁覆盖完整性
3. VerificationGate 权威性（node_completed 不可绕过）
4. explicit assignment 必须经过 acquire()
5. prompt 变更只能通过 promotion
6. trace parser 失败必须暴露为错误事件
7. lease 释放覆盖所有终态路径
已知局限：这些不变量需要在代码实现后逐步添加对应的 validate 规则。

---

## v51 E2E 新发现

#### FL-63（WORKFLOW_EVALUATION test_stats_reliable 自动化判定缺失，P2）

foreman 写 `test_stats_reliable: true` 但实际未使用 pytest-randomly。CCCC 系统应自动检测
是否有 randomized 插件标志，而非依赖 foreman 自述。FL-57 规则在 validate 阶段对 plan 检查，
但 WORKFLOW_EVALUATION.md 的 test_stats_reliable 字段缺乏 runtime 校验。

#### FL-64（is_admin 注入边界未被 forbidden_flow 强制覆盖，P2）

plan forbidden_flows 声明 "MUST NOT accept role=admin or is_admin fields"，但 validate 和
verification gate 均未检测实际测试是否覆盖了所有声明的注入向量。RV-29 的 validate 规则
`W_AUTH_PRIVILEGED_ROLE_FIELD` 检测到了 identity surface，但不检查测试是否覆盖了所有声明的字段名。

#### FL-65（independently_reviewed 分类缺任务级映射，P3）

WORKFLOW_EVALUATION.md result_breakdown 声明 independently_reviewed=2 但未标明具体哪两个任务。
审计追溯困难。

#### UX-23（WORKFLOW_EVALUATION 初始占位符后补充实质，P3）

WORKFLOW_EVALUATION.md 第一次生成时大部分章节为"待 foreman 补充"占位符（926B），foreman 后续
补充为完整内容（5007B）。与 v50 UX-18b 类似但方向不同——补充过程成功了。

#### RV-39（validate 不检测 plan 目标与实现状态码漂移，P3）

T08 plan 目标声明 revoke 后返回 410 Gone，但实现为 404。validate 和 verification 均未检测
此类规格与实现的漂移。（注：v53 Codex review 中 RV-39 编号已被使用，本条为 E2E 发现复验）

---

## 下一批任务

### ~~FL-42~~（v53 代码实现完成：评价系统闭环）
> v53 solve flow（2026-05-31）已实现：T1-T3（自动触发评分 + prompt 候选生成 + 集成测试）。
> v51 E2E 确认 WORKFLOW_EVALUATION.md 自动生成 ✅。**待 AF 引擎启用后实战验证完整闭环。**

### ~~MSE-1~6~~（v53 代码实现完成：模型选型与评价闭环重构，22 tasks）

> v53 solve flow（2026-05-31）已实现全部 22 tasks：MSE-1/2（T4-T6 注册如实化+cost_tier）、
> MSE-3（T7-T9 acquire/release）、MSE-4/5（T10-T12 trace+评分）、MSE-6（T13-T14 进化闭环）。
> v51 E2E 确认未回归破坏现有功能（100 tests pass）。**待 AF 引擎启用后实战验证。**

### ~~AgentFlow 整合~~（v53 代码实现完成：M0-M6）

> v53 solve flow（2026-05-31）已实现：M0（T15-T16 ExecutionBundle+PlanCompiler）、M2（T17 LegacyExecutionEngine）、
> M4/M5（T18-T20 AF patches+AFExecutionEngine+CCCCActorRunner）、全链路集成（T21-T22）。
> v51 E2E 确认走 legacy 引擎路径正常。**待配置启用 AF 引擎后实战验证。**

---

## 后续改进

### Modal 集成（待调研）

将 Modal 集成到 CCCC 系统中。具体集成方案和优先级待后续讨论确定。
