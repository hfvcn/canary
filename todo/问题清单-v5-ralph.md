# CCCC 问题清单 v5 (未解决) — Ralph 改进专项

> 日期：2026-04-04（v5.2 蓝图对齐更新）
> 已完成（E2E 验证通过）：RO-7n/12/13n/14n/15/16/17/18/19/20/21/22/23/24/25/26/27/28/29/30/32/33/34/35/37/38/39/40/41/42/43/44/47/48/49/50/51/52/54/55/72、RA-1/2/3/4、RF-1/2/3/4/5、RL-3/5
> 已完成（v24 确认）：RO-61（structural digest）
> 已完成（v26 确认）：RO-62（force-complete→verification_skipped）/RO-69（CORS 验收标准+集成测试双重拦截）
> 已完成（v28 确认）：RO-51（scope 目录匹配）/RO-52（Gemini JSON）/RO-70（prompt 引导零命令变形）/RO-73（claude runtime 零 stall）
> 已完成（v29 计划审查确认）：RO-57（resubmit reject, 12 tests）/RO-65（challenge degradation, 4 tests）/RO-67（--compact, 14 tests）/RO-68（cleanup_patterns, 5 tests）/RO-71（completer_mismatch verification, 4 tests）
> 已完成（v30 代码修复）：RO-74（prompt 首尾重复 cccc task complete）/RO-75（workflow 全部完成后自动转终态）/RO-76（validate 错误附带字段建议+示例+--show-schema）、RL-21（W_SHARED_PATH_NO_DEPENDENCY 升级为 warning）、BP-1（mock_tests 已集成 agent 验证）/BP-3（expected_input/output 渲染到 worker prompt）
> E2E v29 确认（v30 新能力验证）：BP-1 首次实战拦截（T1 mock_test）/BP-3 渲染确认/RO-76 validate 报错质量确认/RO-75 状态机生效但缺 ledger 事件（→RO-77）
> 代码已修复，场景未触发（迁入 full 归档）：RO-45/46/53/56/58/59/60/63/64、RL-11
> 已完成（v31 代码修复）：RO-77（workflow 终态 ledger 事件）/RO-78（retry workflow_id 解析）/RO-79（python -c 语法检查接入 validate）、BP-2（ModuleSpec 模型+prompt 渲染+验证规则）/BP-4（W_CROSS_TASK_IO_MISMATCH 静态验证+运行时 output contract check）/BP-5（batch_e2e_command schema+verify_batch_e2e()+batch completion 触发）
> 已完成（v32 E2E 验证）：RO-77 ✅（workflow.completed 事件确认）/RO-78 ✅（零 retry 零 mismatch）/BP-2 ✅（module_spec 传递确认）/BP-4 ✅（provides/consumes 契约验证确认）；RO-79 未触发/BP-5 未使用
> v34 计划分析确认已修复：RO-80（_failed_agent_verification 已返回 failed + test_challenge_infrastructure_failure_is_fail_closed 测试覆盖）/RO-81（upstream_keys.update 已实现 N:1 union）/UX-2（_group_repeated_issues 已实现分组 + (x10) 输出格式）
> **结果分瓶颈（v32 更新）**：结果分首次达到 4/5（0 CRITICAL）。瓶颈从"实现 bug"转向"plan 编写体验"（validate 迭代成本、warning 噪音）。BP-2 运行时模块调度 + BP-5 E2E 阻塞模式仍待实现
> 验证轮次（2026-05-14 v31 修复后）：全量 pytest 2628 passed / 0 failed / 120 skipped
> E2E v28 验证：综合 4.2/5（结果 3/5，过程 5/5，体验 4.5/5）
> E2E v29 验证：综合 3.3/5（结果 2/5，过程 4/5，体验 4/5）——v30 新能力全部实战验证通过
> **E2E v32 验证：综合 4.3/5（结果 4/5，过程 5/5，体验 4/5）——历史新高**
> E2E v33 验证：综合 4.0/5（结果 3/5，过程 5/5，体验 4/5）——结果降分因 XSS + 并发安全
> E2E v34 验证：综合 3.7/5（结果 3/5，过程 4/5，体验 4/5）——基础设施修复（task 验证门禁 + flow 模板 + plan.yaml 强制要求）
> E2E v35 验证：综合 2.3/5（结果 2/5，过程 2/5，体验 3/5）——Codex foreman 首测，force-complete 跳过全部 verification，plan 漂移
> E2E v35b 验证（Claude foreman 复测）：综合 3.3/5（结果 3/5，过程 3/5，体验 4/5）——验证门禁有效但 FTS5/debug 未拦截，workflow recovery 绕过
> 已完成（v36 代码修复）：RO-82（failure_path/awareness_paths 透传确认）/RO-83（capability guide + template 补全 aegis/mock_tests/challenge）/RO-85（KIND_FORCE_COMPLETED ledger 事件）/RO-86（notification_outcome 区分 force_passed）/UX-1（provides/consumes 文档格式）/UX-4（template 全字段）/UX-7（serial chain W_FLOW_OWNER_NO_VERIFICATION 降级扩展）/UX-9（wanted_fragments 8 行注入 foreman prompt）/AD-5（prompt_builder aegis intent 注入）/AD-6（foreman system prompt Aegis 纪律）/FL-1（e2e step-1 auto mkdir+git init+docs）/FL-3（e2e step-6 短版+全量版 tracker）/RL-23（agent rule 8 goal_behavior 逻辑验证）/RL-24（agent rule 9 goal_behavior 假设验证）
> 验证轮次（2026-05-16 v36 修复后）：全量 pytest 2696 passed / 0 failed / 120 skipped
> v36 新发现：RL-26（placeholder 路径误报）/FL-4（guide --output 覆盖手动描述）/FL-5（guide --update dev 分支 warning 阻塞 flow）/FL-6（_check_verify 强制 xdist）
> **E2E v37 验证（2026-05-17，Flask FTS5 搜索服务）：综合 3.3/5（结果 3/5，过程 3/5，体验 4/5）**——challenge verification evidence 格式导致全部误判，foreman 自主 override 恢复；22/22 tests pass，安全深度 2/5
> **E2E v38 验证（2026-05-17，Flask FTS5 搜索服务复验）：综合 4.2/5（结果 4/5，过程 4/5，体验 5/5）**——input_robustness gate 修复后首次全流程无误报完成；6/6 tasks verified, 111 tests, 92% coverage, 1 retry (真实问题), 0 manual interventions
> 已完成（v38 E2E 验证）：RO-103（input_robustness_smoke 时序误判——test files 属下游 task 不存在时不阻断）
> v37 新发现：RO-96（evidence 格式不匹配）/RO-97（verification_mode 语义未尊重）/RO-98（task failure vs infra failure 未区分）/FL-11（foreman override 路径）/FL-12（deferred 可恢复状态）
> v38 修复计划（2026-05-17，全量修复 P0-P3）：plan.yaml = plans/fix-v38-all-issues.yaml，29 leaf tasks + 1 integration，覆盖 RO-96/97/95/89/92/93/94/98/99 + AD-1~11 + SL-1~3 + FL-4~12 + UX-5/8/11 + RL-22/25/27
> 验证轮次（2026-05-17 v38 修复后）：全量 pytest 2852 passed / 0 failed / 120 skipped
> v38 新发现：RO-100（discipline rule 输出非确定性排序）/PLR-1 复现（code fence 内术语触发 aegis 检查）/RO-101（challenge upgrade 逻辑无独立测试保护）/RO-102（validate ledger event plan 不存在时 crash）/FL-13（e2e enhancement test xdist 下 flaky）
> v38 E2E 新发现：RO-103（input_robustness_smoke 时序误判，已修复）/FL-14（flow step-4 未引导使用 collaborating-with-codex skill）/FL-15（flow step-6 未引导写入新发现+归档已修复）/FL-16（E2E flow 结束后应清理 cccc 进程）/UX-12（SUSPICIOUS 标记对 grep 检查误报）
> **v37 复盘结论**：
>   - RO-96 根因已定位：`cccc attach` 的 CLI→daemon 路径传递 bug（CLI 传 `"."` 相对路径，daemon 在自己 cwd 解析 → scope url 指向 `/Users/vfch/.cccc` 而非实际 workspace）。**一行修复**：`group_cmds.py:26` 传 `str(Path(args.path).resolve())` 即可
>   - 修好路径后 challenge reviewer (Gemini) 能通过 `_read_claimed_paths()` 读到源代码 → 恢复 agent-level 代码审查能力
>   - security_lint (grep-based) 对 Claude worker 几乎无效——Claude 不犯 debug=True/eval/裸 except 等低级错误。v37 Codex 标的 4 个 MEDIUM 全是设计层问题（FTS5 语法操控、分页 DoS、XSS 上下文、错误静默），grep 抓不到
>   - 真正能检测设计层安全问题的只有两个路径：(B) validate 时用 LLM 从 plan metadata 生成 behavioral test；(C) challenge reviewer 读代码做深层审查
> **v38 改进计划（B+C 策略，按 ROI 排序）**：
>   1. **RO-96 路径修复（P0，一行）**：`group_cmds.py:26` resolve 绝对路径 → 解锁 challenge reviewer 全部能力（Gemini 能看到源代码）
>   2. **RO-99 challenge prompt 注入安全 checklist（P1）**：修好路径后，在 `_build_verification_prompt` 中注入 security checklist（从 plan.critical_flows 提取安全关注点 → 指导 Gemini 做对抗性审查而非仅判断"完成没有"）。这是 C 路径的核心
>   3. **AD-11 validate 时 LLM 生成 behavioral security checks（P1）**：`ralph validate --generate-security-checks` 从 plan metadata（goal_behavior/acceptance_criteria/provides.schema_hint/critical_flows）生成 behavioral test 命令 → 注入 verification.checks[]。这是 B 路径的核心，不依赖 Gemini runtime
>   4. **RO-97 verification_mode 语义（P2）**：mode=ralph 时不触发 Gemini challenge（省 API 调用）；mode=challenge 时才走 B+C 双重检查
>   5. **FL-11/12（P2）**：foreman override + deferred 恢复（workflow 可用性）
>   6. **SL-1/SL-2/SL-3（P3 保险网）**：security_lint grep pattern 升级 blocking + 扩展——仅作为非 Claude worker 或未来退化的兜底，对当前评分无实际帮助
> **策略说明**：
>   - B 路径（AD-11）：在 validate 阶段用 LLM 一次性从 plan metadata 生成 behavioral check 命令（如 `python -c "c.get('/search?q=title:secret'); assert r.status_code==400"`），注入 verification.checks[]，worker 完成后 shell 自动执行。优点：确定性、无运行时 API 调用、可人工审核
>   - C 路径（RO-96+RO-99）：challenge reviewer (Gemini) 拿到源代码 + security checklist 后做深层对抗审查。优点：能发现设计层问题（FTS5 语法暴露、分页策略、XSS 上下文）
>   - B+C 互补：B 拦住已知 surface 的可执行测试，C 发现未预见的设计缺陷
> **预期提分**：RO-96 一行修复 → challenge reviewer 恢复 → 过程分回 4-5/5；AD-11 behavioral checks → 结果分达 4/5；综合目标 **4.3+/5**
> v37 进行中（2026-05-16 计划已 ralph validate PASSED + Codex 二轮审查通过）：
> - 范围：FL-6/RL-26/RO-89/RO-90/UX-11/RO-87/FL-5/FL-7/RO-84（P1+P2，9 项）
> - 实际需代码修改：T1(FL-6)/T2(RO-89)/T3(RO-90)；已实现仅补测试：T4(UX-11)/T5(FL-5)/T6(FL-7)/T7(RO-84)/T8(RO-87)
> - 关键纠正（二轮审查）：T2 RO-89 critical_flows 是 plan-level 字段需从 plan.yaml 读取（非 TaskRef）；T3 RO-90 复用现有 _DEBUG_TRUE_RE 扩展入口白名单；T4 UX-11 已实现（handle_ralph_task_verify 重读 plan），T7 RO-84 canonical kind 是 workflow.plan_validated；T8 RO-87 保留 PreTransitionVetoed
> - 排除（P3 暂缓）：RO-91、UX-8、RL-22/25、AD-7/8
> - 新发现（Codex 计划审查 + v37 落地复盘，2026-05-16）：
>   - PLR-1（plan 编写体验）：plan 中含 `placeholder` 字面量会让自身触发 E_AEGIS_PLACEHOLDER_CONTENT，目前需要绕开拼写；后续应在 aegis 规则增加 "代码 fence/反引号包围的术语视作引用" 的例外
>   - DOC-1：foreman-capability-guide.md 缺少 "verify gate 的非阻塞 warning 类型清单"（contract_violation/security_lint/aegis_evidence_card），影响 foreman 自检
>   - FL-8：flow step-2 ralph validate 在 dev 分支有大量未提交 plan 时也会执行 auto-detect group，多个 group 时输出噪音明显，应允许 --no-auto-detect-group
>   - FL-9（P1 — compact 盲点）：`_compact_filter_issues` 一刀切隐藏所有 hint，包括 `suppress_codes` 转化的 hint。现实情况：plan 作者只要把不想看的 warning 写进 suppress_codes，compact 视图就完全看不到 → review 也无法发现。应让 "裸 suppress（无 SuppressInstance lease）" 在 compact 模式自动显示为 warning，强制改用带 owner/expiry 的 managed suppress 形式
>   - RL-27（P1 — 写冲突应升级）：W_SHARED_PATH_NO_DEPENDENCY 当前是 warning，但两个 task 都修改同一源文件就是真实写冲突（v37 本轮 T1/T7 同改 flow_steps_e2e.py，validate 只产生 warning，必须靠人发现）；建议升级为 error，或仅当 explicit suppress_instance 才降级
>   - PLR-2（P2 — covers.paths 自动补齐）：integration task 写 covers.tasks 但忘了 covers.paths 几乎是规律性遗漏；ralph 可由 covers.tasks 自动展开 task 的 claimed_paths 补到 covers.paths，并把现在 W_COVERS_NOT_EXERCISED 改为 hint
>   - DOC-2（P3 — suppress 文档）：plans/_template.yaml suppress_codes 段落只示范了 "需要时取消注释"，未说明 "裸 suppress 应该是 last resort、managed suppress 是首选"，让新 plan 容易像本轮一样塞一堆裸 suppress
> 全量版本：[问题清单-v5-ralph-full.md](./问题清单-v5-ralph-full.md)
> 审查依据：[v5-综合审查报告.md](./v5-综合审查报告.md)
> 蓝图对齐：[工作流蓝图.md](./工作流蓝图.md) v0.3（两阶段拆分 + Ralph Agent）
> 评估报告：[e2e-实战评估报告-v29.md](./e2e-实战评估报告-v29.md)（最新） | [e2e-实战评估报告-v28.md](./e2e-实战评估报告-v28.md) | [e2e-实战评估报告-v27.md](./e2e-实战评估报告-v27.md) | [e2e-实战评估报告-v26.md](./e2e-实战评估报告-v26.md) | [e2e-实战评估报告-v25.md](./e2e-实战评估报告-v25.md) | [e2e-实战评估报告-v24.md](./e2e-实战评估报告-v24.md) | [e2e-实战评估报告-v23.md](./e2e-实战评估报告-v23.md) | [e2e-实战评估报告-v22.md](./e2e-实战评估报告-v22.md) | [e2e-实战评估报告-v21.md](./e2e-实战评估报告-v21.md) | [e2e-实战评估报告-v20.md](./e2e-实战评估报告-v20.md) | [e2e-实战评估报告-v19.md](./e2e-实战评估报告-v19.md) | [e2e-实战评估报告-v18.md](./e2e-实战评估报告-v18.md) | [e2e-实战评估报告-v17.md](./e2e-实战评估报告-v17.md) | [e2e-实战评估报告-v16.md](./e2e-实战评估报告-v16.md) | [e2e-实战评估报告-v15.md](./e2e-实战评估报告-v15.md) | [e2e-实战评估报告-v14.md](./e2e-实战评估报告-v14.md)
>
> **本文档只保留未解决的改进项和已知局限。已完成条目与历史实现记录保存在 full 版本中。**

---

## 未解决改进项

### RO 系列（运行时/验证）

#### RO-84 ralph validate 应产生 ledger 事件（P2）

> **来源**：2026-05-15 E2E v34 过程审查 #1
- **严重度**：P2 — 审计可追溯性
- **改进方案**：validate 成功/失败时向 daemon 发送 `ralph.validate_result` 事件（含 error/warning 计数 + plan digest）
- **验收标准**：下一轮 E2E ledger 中有 validate 事件

### v36 第二轮新发现（FastAPI URL shortener，2026-05-16）

#### RO-92 ~ RO-94: verify gate 安全方法库（Security Recipe Library）

> **来源**：2026-05-16 E2E v36 结果审查（Codex review R-1/R-2/R-4，FastAPI URL shortener 实例）
> **设计原则**：**critical_flow 声明驱动,无声明 = 零触发 = 零噪音**

##### 触发机制设计（三重门控,防止无关项目误导）

```
触发条件 = critical_flow 含安全关键词
         AND plan 声明了对应 surface_type（或 temporal_pattern）
         AND verification.checks 缺少该 surface 的测试
→ 三者同时成立才报 warning
```

- **无安全 critical_flow 的项目**（CLI 工具/数据管道/算法库）→ 零检查零噪音
- **有安全 flow 但已自行覆盖测试的项目** → 零误报（checks 已含对应测试=跳过）
- **有安全 flow 且缺测试** → 报 warning（foreman 主动声明了安全关注=自愿接受检查）

##### 分级升级策略

| 级别 | 条件 | 行为 |
|------|------|------|
| hint（新 recipe 默认） | 首次引入 | 仅 `--verbose` 显示,不影响 validate 结果 |
| warning | 累计 3+ 轮 E2E 验证无误报 | 显示但不阻塞 |
| error | 累计 5+ 轮 + 极高信号（如 `debug=True`） | 阻塞 |

##### Recipe 按 surface_type 组织（非按项目类型）

```python
SECURITY_RECIPES = {
    "url_input":        [...],  # SSRF 类
    "auth_token":       [...],  # 认证类
    "file_path":        [...],  # 路径遍历类
    "temporal:store_then_use": [...],  # TOCTOU 类
    # 后续按 E2E 实战增量添加
}
```

新 surface_type 按 CWE 分类添加,不为特定测试项目硬编码。

##### Advisory hint（无声明时的唯一输出）

plan 声明了 `flask`/`fastapi`/`requests` 相关依赖但 critical_flows 无安全关键词 → `ralph validate` 输出单条 advisory hint:
> "H_SECURITY_SURFACE_UNDECLARED: project uses web framework but declares no security-related critical_flow — consider adding if externally accessible"

不阻塞、不升级、不影响 validate 通过。

---

#### RO-92 verify gate 缺 TOCTOU 审查能力（P1）

> **来源**：2026-05-16 E2E v36 结果审查（Codex review R-1）
- **严重度**：P1 — 时序敏感安全问题跨任务全部逃过 verify gate
- **触发条件**：critical_flow 声明 `temporal_pattern: store_then_use | check_then_act | reserve_then_consume`
- **现象（v36 实例）**：plan 声明 critical_flow=ssrf_protection 但未声明 temporal_pattern → recipe 不触发 → DNS rebinding 漏过
- **根因**：verify gate 不识别"存储与消费分离"的时序模式
- **改进方案**：
  1. critical_flow schema 增加 `temporal_pattern` 可选字段
  2. 含该字段时,verify gate 注入"两阶段"测试模板（store 合法 → mock 状态变化 → use 断言）
  3. 未覆盖时报 `W_VERIFICATION_TOCTOU_GAP`(hint 级别,3 轮后升 warning)
  4. 未声明 temporal_pattern 的 critical_flow → **不触发,零噪音**
- **验收标准**：v36 plan 加 `temporal_pattern: store_then_use` 后,validate 报 hint;不加时零输出
- **Recipe 示例**：DNS rebinding mock(URL surface)、文件 rename mock(file surface)、permission revoke(auth surface)

#### RO-93 verify gate 缺 hostname 编码规范化 smoke test（P1）

> **来源**：2026-05-16 E2E v36 结果审查（Codex review R-2）
- **严重度**：P1 — SSRF 黑名单可被编码旁路
- **触发条件**：critical_flow 名称含 `ssrf` / `url_validation` / `url_input` 关键词 **AND** verification.checks 无编码矩阵测试
- **现象（v36 实例）**：critical_flow=ssrf_protection 但 checks 只测 `127.0.0.1` 文字 → 八进制/十进制/IPv6-mapped 全漏
- **根因**：verify gate 无 surface-specific fuzz 注入
- **改进方案**：
  1. security recipe `url_input` 包含编码矩阵:`[0177.0.0.1, 2130706433, 0x7f000001, [::ffff:127.0.0.1], [::1]]`
  2. verify gate 检测到含 `ssrf`/`url` 关键词的 critical_flow → 检查 pytest 是否覆盖矩阵 → 未覆盖报 `W_SSRF_ENCODING_UNCOVERED`(hint 级别)
  3. **不含这类关键词的 critical_flow → 静默跳过**
- **验收标准**：v36 plan critical_flow=ssrf_protection → hint;改名为 `data_pipeline` → 零输出
- **矩阵扩展**：后续可按 E2E 实战增加 userinfo(`user@host`)、DNS rebinding(`rebind.network`)、IPv4-in-IPv6 等

#### RO-94 verify gate 应对 auth 字段做 timing-safe compare 检查（P2）

> **来源**：2026-05-16 E2E v36 结果审查（Codex review R-4）
- **严重度**：P2 — timing attack 风险
- **触发条件**：critical_flow 名称含 `*_auth` / `*_token` / `*_key` 关键词 **AND** claimed_paths 中的源文件含 token/key 比较但无 `secrets.compare_digest`
- **现象（v36 实例）**：critical_flow=admin_delete_auth,app/main.py 用 `!=` 比较 token
- **根因**：verify gate 无密码学模式 grep
- **改进方案**：
  1. security recipe `auth_token` 含 grep 模式:Python 查 `secrets.compare_digest`/`hmac.compare_digest`,Go 查 `subtle.ConstantTimeCompare`,Node 查 `crypto.timingSafeEqual`
  2. verify gate 检测到含 `auth`/`token`/`key` 关键词的 critical_flow → grep claimed_paths 源文件 → 无 timing-safe 函数报 `W_AUTH_TIMING_UNSAFE`(hint 级别)
  3. **不含这类关键词的 flow → 静默跳过**
- **验收标准**：v36 plan + admin_delete_auth → hint;无 auth flow 项目 → 零输出
- **语言扩展**：按需加语言模式,每语言 1 行 grep pattern

### v37 E2E 新发现（Flask FTS5 搜索服务，2026-05-17）

#### RO-96 Challenge reviewer 读不到源代码——attach 路径解析 bug（P0）

> **来源**：2026-05-17 E2E v37 实测（T1-scaffold 两次 challenge failure）+ 根因追踪
- **严重度**：P0 — challenge reviewer 100% 误判率，一行修复解锁全部 agent 审查能力
- **现象**：Gemini challenge reviewer 报 "source code not found in evidence"，task 全部 failed
- **根因已定位**：`cccc attach .` 通过 daemon 执行时，CLI (`group_cmds.py:26`) 传相对路径 `"."` 给 daemon → daemon handler (`group_bootstrap_ops.py:20`) 在自己 cwd 下 `Path(".")` 解析 → `detect_scope` 得到 daemon cwd（`/Users/vfch/.cccc`）而非用户的实际 workspace（`/tmp/cccc-e2e-v37`）→ scope url 错误 → `RalphService.project_root` 指向错误目录 → `_read_claimed_paths()` 找不到文件 → `source_context` 为空 → Gemini 无代码可审
- **调用链**：
  ```
  CLI: cccc attach .
    → call_daemon({"path": "."})          # ← 未 resolve
    → daemon: handle_attach(args)
    → Path(args["path"])                   # = Path(".") 在 daemon cwd
    → detect_scope(daemon_cwd)
    → git_root(daemon_cwd) or daemon_cwd  # = /Users/vfch/.cccc
    → scope.url = "/Users/vfch/.cccc"     # ← 错
  ```
- **修复方案（一行）**：
  ```python
  # src/cccc/cli/group_cmds.py line 26
  # Before:
  {"op": "attach", "args": {"path": args.path, ...}}
  # After:
  {"op": "attach", "args": {"path": str(Path(args.path).resolve()), ...}}
  ```
- **验收标准**：`cccc attach .` 在任意目录执行后，`group show` 的 scope.url 和 project_root 指向该目录；challenge reviewer 能读到 claimed_paths 文件内容
- **连带修复**：RO-97 的 "verification_mode 未尊重" 可能是 challenge reviewer 因无代码而 fail-closed 的表现，路径修好后需复测确认是否还存在

#### RO-97 verification_mode=ralph 时 challenge review 仍运行并阻断（P1）

> **来源**：2026-05-17 E2E v37 实测（plan.yaml 声明 verification_mode: ralph）
- **严重度**：P1 — mode 语义被忽略导致无效阻断
- **现象**：plan.yaml 中 verification_mode 为 ralph（shell exit code），但系统仍执行 agent/challenge review 且其失败阻断了任务
- **根因**：verification_gate.py 在 ralph mode 下仍执行 challenge review 且结果为 blocking
- **改进方案**：
  1. verification_mode=ralph 时，只运行 shell checks，不触发 agent/challenge review
  2. 或：agent/challenge review 结果在 ralph mode 下降级为 advisory（不阻断）
  3. 文档明确三种 mode 语义：`ralph`(shell only), `agent`(shell + agent review), `challenge`(shell + adversarial review)
- **验收标准**：verification_mode=ralph 的 task，shell checks 通过即 passed，不触发 challenge

#### RO-98 Task failure 与 verifier infra failure 未区分（P2）

> **来源**：2026-05-17 E2E v37 实测 + Codex process review
- **严重度**：P2 — infra 问题被错误归咎于 worker
- **现象**：challenge reviewer 因自身无法读取文件（infra 问题）而报 failure，系统将其记录为 task_failed，扣减 worker retry 次数
- **根因**：verification_gate 不区分 "task 实质不合格" 和 "verifier 自身出错"
- **改进方案**：
  1. 新增 `verification_infra_error` 状态，不计入 retry count
  2. Verifier 返回结构需包含 `failure_type: task_quality | infra_error | timeout`
  3. infra_error 时自动 retry verifier（不 retry worker），超限后升级为 foreman decision
- **验收标准**：challenge reviewer 因文件不可读失败时，task 状态为 verification_infra_error 而非 failed

#### FL-11 Foreman 缺少正式 override 路径（P2）

> **来源**：2026-05-17 E2E v37 实测（foreman 被迫用 out-of-band 方式绕行）
- **严重度**：P2 — foreman 判断正确但无正式机制执行
- **现象**：foreman 识别 challenge gate 误报，但只能通过 `cccc send` + 手动 `ralph complete` 绕行，workflow engine 状态未更新
- **改进方案**：
  1. 新增 `cccc workflow override --task TASK_ID --reason "..." --evidence "ralph verify passed"`
  2. 产生 `workflow.foreman_override` ledger 事件（含原因、证据、时间戳）
  3. Override 后 task 状态变为 `completed_by_override`，downstream dependency gate 识别
- **验收标准**：foreman override 后，downstream tasks 可正常 submit

#### FL-12 deferred 应为可恢复状态（P2）

> **来源**：2026-05-17 E2E v37 实测 + v36c RO-95 cluster
- **严重度**：P2 — deferred 变 terminal state 迫使 workflow 绕行
- **现象**：task 因 challenge failure 进入 failed → retry → deferred，之后无法再 retry/force-complete/submit downstream
- **根因**：deferred 状态在 workflow_state_engine 中无出边（无 retry/accept/override 转移）
- **改进方案**：
  1. deferred 状态增加转移：`retry_worker`, `retry_verifier`, `foreman_accept`, `cancel`
  2. Foreman 可通过 `cccc workflow retry --task TASK_ID` 或 override 从 deferred 恢复
  3. 最大 deferred 时间后自动升级为需要 human decision
- **验收标准**：deferred task 可被 foreman retry 或 override 恢复，downstream 正常流转
- **关联**：RO-95 cluster（v36c）、UX-11

### v38 改进项：Security Lint 升级 + Aegis 安全链

#### RO-99 Challenge reviewer prompt 注入安全 checklist（P1）

> **来源**：2026-05-17 v37 复盘（C 路径设计）
- **严重度**：P1 — 修好 RO-96 后，让 Gemini 做实质安全审查而非仅"完成判定"
- **前置**：RO-96 修复（Gemini 能读到源代码）
- **现状**：`_build_verification_prompt` 只传 task 定义 + 源代码 + response_schema（passed/failed），Gemini 仅判断"worker 是否完成了 goal_behavior"，不主动做安全审查
- **改进方案**：
  1. 从 plan.critical_flows 提取安全关键词（input-validation, ssrf, auth 等）
  2. 将安全 checklist 注入 verification prompt：`"Additionally, verify these security properties based on declared critical_flows: [...]"`
  3. Checklist 由 critical_flow 类型驱动：
     - `input-validation-flow` → "Are all user inputs validated? Can FTS5/SQL operators be injected via MATCH syntax? Are there resource limits (pagination, body size)?"
     - `ssrf-protection` → "Does URL validation handle encoded IPs, DNS rebinding, redirect chains?"
     - `*-auth` → "Is token comparison timing-safe? Are secrets hardcoded?"
  4. 无安全 critical_flow 的项目 → 不注入 checklist → Gemini 仅做功能审查
- **改动范围**：`ralph/agent.py` `_build_verification_prompt` ~30 行
- **验收标准**：plan 含 input-validation critical_flow → Gemini prompt 含对应安全 checklist → 能检出 FTS5 语法操控、分页 DoS 等设计层问题
- **预期效果**：结果分从 3/5 → 4/5（Gemini 检出设计层安全问题 → task failed → worker 修复后重试）

#### AD-11 validate 时 LLM 生成 behavioral security checks（P1）

> **来源**：2026-05-17 v37 复盘（B 路径设计）
- **严重度**：P1 — 让安全检测在 shell 层可执行，不依赖 Gemini runtime
- **设计原则**：plan.yaml 已包含端点/格式/预期行为信息（goal_behavior + acceptance_criteria + provides.schema_hint + critical_flows），LLM 可从中生成 behavioral test 命令
- **改进方案**：
  1. `ralph validate --generate-security-checks plan.yaml`：调用 LLM（可配置 provider），输入 plan metadata，输出 behavioral check 命令列表
  2. LLM prompt 示例输入：
     ```
     critical_flow: input-validation-flow ("Malicious inputs rejected safely")
     goal_behavior: "POST /docs accepts JSON {title, body}... GET /search?q=xxx"
     acceptance_criteria: "POST /docs rejects NUL bytes with 400"
     provides.schema_hint: "POST /docs, GET /search?q=xxx with pagination"
     ```
  3. LLM 输出（结构化 JSON）：
     ```json
     [
       {"name": "security-fts5-operator-injection",
        "command": "python -c \"from app import create_app; c=create_app().test_client(); r=c.get('/search?q=title:secret'); assert r.status_code==400, f'FTS5 operator accepted: {r.status_code}'\""},
       {"name": "security-pagination-upper-bound",
        "command": "python -c \"from app import create_app; c=create_app().test_client(); r=c.get('/search?q=test&per_page=999999'); import json; d=json.loads(r.data); assert d.get('per_page',0)<=100\""},
       {"name": "security-highlight-xss",
        "command": "python -c \"from app import create_app; c=create_app().test_client(); c.post('/docs',json={'title':'<script>','body':'x'}); r=c.get('/search?q=script'); assert '<script>' not in r.data.decode()\""}
     ]
     ```
  4. 生成的 checks 标记 `auto_generated: true`，foreman 可审核/修改/删除后再提交 plan
  5. 无安全 critical_flow → 不生成 → 零噪音
- **改动范围**：`ralph/cli.py` 新子命令 + `ralph/security_check_generator.py` ~100 行
- **验收标准**：对 v37 plan.yaml 执行后生成 ≥3 个 behavioral check，能检出 FTS5 语法操控和分页 DoS
- **与 C 路径的互补**：B 生成的 checks 在 shell 层拦住已知 surface（确定性、可复现）；C (Gemini) 发现未预见的设计缺陷（灵活性）
- **关联**：取代 AD-10 的 grep-based recipe 注入方案（behavioral test > grep pattern）

#### SL-1 security_lint 命中时升级为 blocking failure（P3 保险网）

> **来源**：2026-05-17 v37 复盘（verify gate 代码分析）
- **严重度**：P3 — 对 Claude worker 几乎无效，仅防退化/非 Claude runtime
- **现状**：`_check_security_lint` 命中 debug_true/fts_raw_input 后只记录 warning
- **现实**：Claude worker 不犯这类低级错误；v37 实测零命中。真正的安全问题是设计层面的（FTS5 语法操控、分页 DoS、XSS 上下文），grep 抓不到
- **保留价值**：防止非 Claude runtime（Codex/Gemini/custom worker）犯低级错误；防止未来 Claude 版本退化
- **改进方案**：命中时升级为 blocking（改 `record_verification_warning` → `record_verification_failure`）
- **改动范围**：`verification_gate.py` 约 5 行
- **验收标准**：worker 写了 `debug=True` → verify gate fail task
- **优先级说明**：降为 P3，因为 B+C 路径才能解决真实安全问题；此项仅为兜底

#### SL-2 扩展 security_lint pattern 矩阵（P3 保险网）

> **来源**：2026-05-17 v37 Codex results review
- **严重度**：P3 — 同 SL-1，对 Claude worker 几乎无效，仅防退化
- **现有 pattern**：`_DEBUG_TRUE_RE`（debug=True）、`_MATCH_RAW_RE`（FTS/SQL 拼接）
- **可选新增**：`bare_except`、`eval()`、`exec()`、`app.run(debug=True)`、`hardcoded_secret`
- **优先级说明**：降为 P3。真实安全问题（FTS5 语法操控、DoS、XSS 上下文）需要 behavioral test（AD-11）或 Gemini 审查（RO-99），不是 grep 能解决的

#### SL-3 input_robustness_gap 升级为 conditional blocking（P3 保险网）

> **来源**：2026-05-17 v37 复盘
- **严重度**：P3 — 同上
- **现状**：`_check_input_robustness` 已检测 critical_flow 含 input 关键词 + 测试无 NUL pattern → 记 warning
- **改进方案**：升级为 blocking
- **优先级说明**：v37 中 worker 的测试确实包含 `\x00` pattern，此检查通过了。真正的缺失是 FTS5 操作符限制等设计层问题，需 AD-11 解决

#### AD-9 aegis intent→verification 强制链（P2，被 AD-11 部分取代）

> **来源**：2026-05-17 v37 复盘
- **严重度**：P2 — 在 validate 阶段阻止"声明了安全关注但 checks 为空"的 plan
- **现状**：aegis.intent=feature 只注入 prompt hint，不检查 checks 内容
- **改进方案**：`_check_aegis_discipline` 新增规则：intent=feature + security critical_flow + checks 无安全测试 → error
- **与 AD-11 关系**：AD-11 解决"生成什么 check"，AD-9 解决"必须有 check"。AD-11 落地后 AD-9 变为冗余检查（因为 AD-11 会自动生成 checks），但作为 fail-safe 仍有价值

#### AD-10 grep-based security recipe 注入（P3，被 AD-11 取代）

> **来源**：2026-05-17 v37 复盘
- **严重度**：P3 — **已被 AD-11 取代**
- **取代原因**：AD-10 用 grep 规则生成静态 check（如 `grep debug=True`），但 Claude worker 不犯这类错误。AD-11 用 LLM 从 plan metadata 生成 behavioral test（如 `python -c "c.get('/search?q=title:secret'); assert status==400"`），能检出设计层问题。前者是子集，后者严格优于前者
- **保留方式**：AD-11 的 LLM 生成结果中自然会包含 grep 类静态检查（如需要），无需单独维护 recipe 规则库

---

#### FL-8 e2e 任务的 verification.checks 应强制 compile step（P2）

> **来源**：2026-05-16 E2E v36 过程审查（Codex review P-1）
- **严重度**：P2 — verification gate 一致性破坏
- **现象**：plan.yaml v36 e2e 任务 checks 只有 `pytest tests/ -q` + README grep，缺独立 compile step（如 `python -c "from app.main import app; assert app"`）。声称 compile+test 双重 gate，但 e2e 跳过 compile
- **根因**：ralph validate 对 verification_mode=ralph 的非 unit-level task 未强制 compile check
- **改进方案**：ralph validate 对 verification.level in (api, e2e, integration) 的 task，若 checks[] 不含 import/compile 项，报 W_E2E_MISSING_COMPILE_CHECK
- **验收标准**：v36 plan.yaml e2e 任务在 validate 时报此 WARNING

#### FL-9 provides/consumes 应支持 signature 声明并机器校验（P2）

> **来源**：2026-05-16 E2E v36 过程审查（Codex review P-2）
- **严重度**：P2 — 跨任务契约只是元数据
- **现象**：plan.yaml v36 provides/consumes 全部是文字标签（如 `db_module`、`security_validators`），无 signature 信息。下游任务消费时无机器校验，只能通过 import / pytest 间接暴露契约违反
- **根因**：Plan schema 中 provides/consumes 缺 signature 字段
- **改进方案**：扩展 provides schema 允许 `signatures: {fn_name: "(args) -> ret"}`，consumer task 启动前用 `ast.parse` + 类型 hint 校验
- **验收标准**：provides 含 signatures 时，consumer task 启动前若上游模块未导出对应 signature，dispatcher 拒绝启动

#### FL-10 plan.yaml 应自动持久化 workflow 完成态（P3）

> **来源**：2026-05-16 E2E v36 过程审查（Codex review P-5）
- **严重度**：P3 — dual source of truth（plan.yaml vs workflow ledger）
- **现象**：v36 plan.yaml state 字段未含 e2e 完成，但 workflow ledger 显示 4/4 完成。foreman 需手动 `ralph sync-state` 才能让 `ralph suggest` 显示正确状态
- **根因**：workflow 状态转移时不回写 plan.yaml
- **改进方案**：workflow state transition hook 自动回写 plan.yaml task state，或让 `ralph suggest` 默认从 ledger 读
- **验收标准**：workflow 完成 task 后，无需手动 sync-state，`ralph suggest` 立即显示新批次

---

### v36 第一轮新发现（P1/P2 批量修复）

#### FL-4 ralph guide --output 覆盖手动编辑的 Description 字段（P2）

> **来源**：2026-05-16 v36 flow step-7 发现
- **严重度**：P2 — 人工补全的 aegis/mock_tests/verification_mode 描述被覆盖
- **现象**：手动在 foreman-capability-guide.md 中填写 Description 后，运行 `ralph guide --output` 会用 schema introspection 结果覆盖，Description 列回归为空
- **根因**：guide_generator 从 Pydantic model_fields 提取信息，但 model 字段未声明 `description=`
- **改进方案**：在 models.py 的关键字段（verification_mode, aegis, mock_tests, provides, consumes）的 `Field()` 中添加 `description=` 参数，让 guide_generator 自动提取
- **验收标准**：`ralph guide --output` 生成的 guide 中上述 5 个字段 Description 非空

#### FL-5 ralph guide --update 在 dev 分支对未提交变更报 warning 导致 flow step-7 失败（P2）

> **来源**：2026-05-16 v36 flow step-7 连续失败
- **严重度**：P2 — dev 分支有大量未提交变更时 flow 无法完成
- **现象**：`ralph guide --update` 对 `assignment_batches.py`、`ralph_service.py`、`verification_gate.py` 报 "affected by changes — review manually"，flow step-7 检查视任何 warning 为失败
- **根因**：`update_guide()` 用 git diff 检测变更文件，dev 分支有大量 pre-existing 未提交变更
- **改进方案**：step-7 检查改为：warnings 降级为 advisory（不阻塞），或 `update_guide()` 只检测 since flow start 的变更
- **验收标准**：dev 分支有未提交变更时 flow step-7 不被 advisory warnings 阻塞

#### FL-6 flow step-4 _check_improvement_register 只检查 git diff 有 additions，不区分新旧变更（P2）

> **来源**：2026-05-16 v36 flow step-4 通过但实际未记录新发现
- **严重度**：P2 — flow 检测漏洞，操作者可跳过缺陷记录步骤
- **现象**：step-4 检查 `git diff -- tracker` 有 additions 即通过。但如果 tracker 有 pre-existing 未提交变更（如 dev 分支积累的改动），即使操作者未记录本轮新发现，检查也会通过
- **根因**：`_check_improvement_register()` 只检查 diff 有 "+" 行，不区分变更来自本轮还是历史
- **改进方案**：检查 tracker 的 `git diff` 中是否包含当前版本标识（如 "v36"）或检查 diff 时间戳 > flow 启动时间（`state.started_at`）
- **验收标准**：tracker 有 pre-existing additions 但无本轮标识时 step-4 不通过

---

### v35b 新发现（Claude foreman 复测，2026-05-16）

#### RO-89 verify gate 未检测 FTS5 malformed input 导致的 unhandled 500（P1）

> **来源**：2026-05-16 E2E v35b 结果审查（Codex review）
> **v36c 复现确认（2026-05-16）**：12/12 pytest passed + `ralph verify outcome=passed`，但 `client.get('/search', query_string={'q': '\x00'})` 实测 HTTP 500 + `sqlite3.OperationalError: unterminated string` raw 错误暴露。verify gate 当前**完全盲**。
- **严重度**：P1 — 搜索接口可被 NUL/control 字符 crash
- **现象**：app.py 搜索路由 FTS5 MATCH 接收到含 NUL 字符的 query 时触发 `sqlite3.OperationalError: unterminated string`，返回 raw 500。verify gate 的 `run-tests` 只测功能正确性，不测异常输入路径
- **根因**：verify gate 无 fuzzing/异常输入检查，所有测试全部使用良性输入
- **改进方案**：verify gate 增加 security smoke check（critical_flow 含 `search/query/input` 时自动注入 NUL、空字节、极长输入并断言 status_code != 500）
- **验收标准**：v36c 项目 + 此规则后，verify gate 对 search 路由报 WARN "search endpoint not robust to NUL input"

#### RO-90 verify gate 未检测 debug=True 生产风险（P2）

> **来源**：2026-05-16 E2E v35b 结果审查
> **v36c 复现确认（2026-05-16）**：foreman plan 含"开发模式 debug=True"要求，worker 写入 `app.run(debug=True)`，`ralph verify outcome=passed`。verify gate 既无 grep-based lint 也无 agent review pass 提示该风险。
- **严重度**：P2 — 泄露调试信息（生产部署时 stack trace 客户端可见）
- **现象**：app.py 末尾 `app.run(debug=True)` 写死，verify gate 未检测
- **根因**：verify gate 无 security lint 检查
- **改进方案**：verify gate 增加 grep-based 检查（生产入口文件含 `debug=True` / `DEBUG=True` 时报 WARN）
- **验收标准**：v36c 项目 + 此规则后，verify gate 对 app.py 报 WARN "production entry contains debug=True"

#### UX-11 workflow deferred 状态下 retry 应支持 re-verify（P2）

> **来源**：2026-05-16 E2E v35b 过程审查
> **Cluster**: `workflow-recovery-protocol`（与 RO-95、v36 WORKFLOW_EVALUATION P-3 同根）
- **严重度**：P2 — 需手动绕过 workflow 恢复
- **现象**：routes-and-templates 因 GNU timeout exit 127 进入 deferred。foreman 修复 plan.yaml 后无法 re-verify（workflow 仍用 cached command）。最终手动下发第三批绕过 workflow
- **根因**：workflow 在 submit 时缓存 task spec，retry/re-verify 不重读 plan.yaml
- **改进方案**：`cccc workflow verify --task TASK_ID --refresh-spec` 从 plan.yaml 重新加载 verification commands
- **验收标准**：verify --refresh-spec 使用最新 plan.yaml 的检查命令

#### RO-95 workflow defer recovery 死循环：deferred/failed 状态后 retry 永远 hit single_writer_active（P1）

> **来源**：2026-05-16 E2E v36c 实测（T02 deferred → 13 次 retry 全部 deferred → daemon 必须重启）
> **Cluster**: `workflow-recovery-protocol`（与 UX-11、v36 WORKFLOW_EVALUATION P-3 同根）
- **严重度**：P1 — 整个 workflow 不可恢复，磁盘代码完整但状态机污染
- **现象**：T02_app_routes 第一次分发后因 `TasksAlreadyExistError` 进入 deferred；foreman 自动 retry / 手动 force-clear / 移除并重加 worker actor 全部无效，每次 retry 都被 `defer_batch_for_single_writer` 阻止（reason=single_writer_active）
- **根因**：
  1. `release_agent` 全代码库**唯一**调用点是 `assignment_completion.py:32 on_task_completed_inner`（成功完成路径）
  2. `on_task_failed`（workflow_orchestrator.py:891）只改 task status，**不调 release_agent**
  3. 进入 deferred 状态完全不释放
  4. `_active_assignments[worker-1] = "T02"` 永久污染 → `defer_batch_for_single_writer` 看到 worker-1 仍 active → 新 batch 与 running paths 冲突 → 永远 defer
- **副根因（同 cluster）**：14:04:39 `TasksAlreadyExistError` 是 engine auto-dispatch + foreman 主动 register 撞车的产物。engine 返回 fatal 而非 `{"status": "already_dispatched"}`，foreman 无 hook 自动转 retry。
- **改进方案**：
  - 快修（P1）：`on_task_failed` 与 deferred 状态转移时显式调用 `release_agent(agent_id)`
  - 根治（P2，本 cluster 共享）：`workflow submit` 对已 auto-dispatch 任务返回 `{"status": "already_dispatched", "by": "auto-dispatcher"}` 而非 raise TasksAlreadyExistError
- **验收标准**：
  - task 进入 deferred 或 failed 后，`_active_assignments` 中该 agent 的条目被清除
  - foreman 重提同一 batch 不应再 hit single_writer_active（如已没有真实 running task）
  - v36c 场景可复现验证：当 retry 死循环触发时，新 fix 生效后 workflow 应能自然恢复 T02 verification

#### FL-7 flow step-6 完成后应自动将已验证修复条目从短版移至 full 版归档（P2）

> **来��**：2026-05-16 E2E v35b 实测
- **��重度**：P2 — 短版积累已修复条目，降低可读性
- **现象**：v36 修复了 14 项（RO-82/83/85/86, UX-1/4/7/9, AD-5/6, FL-1/3, RL-23/24），header 中标记了"已完成"但详细描述仍留在短版中未移除。操作者需手动清理
- **根因**：flow step-6 只检查 git diff 有 additions，不检查/执行已修复条目的归档迁移
- **改进方案**：flow step-6 增加归档提示或自动化：检测 header 中新增"已完成"条目后提示"请移除短版中对应详细描述"，或提供 `ralph tracker archive --version v36` 命令自动迁移
- **验收标准**：短版中不残留已标记"已完成"的条目详细描述

#### RO-91 claimed_paths 遗漏实���写入文件��� ralph validate 应 WARNING（P3）

> **来源**：2026-05-16 E2E v35b 过程审查
- **严重度**：P3 — 路径所有权不准确
- **现象**：routes-and-templates 的 claimed_paths 为 `templates/`, `static/`，但实际需要修改 `app.py`（只在 awareness_paths）。worker 最终写入 app.py
- **根因**：ralph validate 无法推断 goal_behavior 中描述的写入目标与 claimed_paths 的一致性
- **改进方案**：Agent rule 检查 goal_behavior 中 "Add routes to app.py" 类描述与 claimed_paths 是否匹配
- **验收标准**：goal_behavior 提及 "写入/修改/添加到 X" 但 X 不在 claimed_paths 时报 W_CLAIMED_PATH_INCOMPLETE

---

### v38 修复过程新发现（2026-05-17）

#### RO-100 discipline rule 输出非确定性排序（P2 — 已修复）

> **来源**：2026-05-17 v38 回归测试
- **严重度**：P2 — 验证结果不可复现
- **现象**：`W_AEGIS_PLAN_NO_COMPAT_BOUNDARY` 的 evidence.dependencies 列表顺序随 plan.tasks 迭代顺序变化，导致 test_validator_ordering 失败
- **根因**：`_cross_task_dependencies()` 未对输出排序
- **修复**：已在本轮添加 `sorted(dependencies)` — 已修复

#### RO-101 challenge upgrade 逻辑无独立测试保护（P2）

> **来源**：2026-05-17 v38 回归测试（T2 重构差点丢失）
- **严重度**：P2 — 关键业务逻辑无保护
- **现象**：T2 重构 `_verify_completion_for_mode` mode routing 时，漏掉了"ralph mode task 触碰 critical_flow entrypoint 时自动升级为 challenge"的逻辑。回归测试 `test_critical_flow_challenge_upgrade` 拦住了
- **根因**：升级逻辑之前内联在老函数中，重构时未提取为独立可测函数
- **改进方案**：`_should_upgrade_to_challenge` 已提取为独立方法（本轮修复），但建议增加单元测试直接覆盖该方法
- **验收标准**：`_should_upgrade_to_challenge` 有独立单元测试

#### RO-102 validate ledger event 在 plan 文件不存在时 crash（P3 — 已修复）

> **来源**：2026-05-17 v38 回归测试（test_no_agent_skips_agent）
- **严重度**：P3 — 测试环境健壮性
- **现象**：`_validate_daemon_event_payload` 直接 `plan_path.read_bytes()` 不检查文件是否存在
- **修复**：已在本轮添加 `if plan_path.exists()` 防御 — 已修复

#### FL-13 test_ralph_enhancement_surface_e2e 在 xdist 下偶发失败（P3）

> **来源**：2026-05-17 v38 全量回归（偶发，第二次运行通过）
- **严重度**：P3 — CI 可靠性
- **现象**：E2E 增强测试在并行执行时偶发 fail，单独运行通过
- **根因**：可能是资源竞争或时序依赖
- **改进方案**：标记为 `@pytest.mark.serial` 或排查具体竞争点

---

### v38 E2E 新发现（Flask FTS5 复验，2026-05-17）

#### FL-14 flow step-4 未引导使用 collaborating-with-codex skill（P2）

> **来源**：2026-05-17 E2E v38 流程体验
- **严重度**：P2 — flow 引导缺失导致用户/agent 直接调用 codex CLI 而非使用 `collaborating-with-codex` skill
- **现象**：flow step-4 instruction 说 "Use codex_bridge.py with dedicated review prompts"，但未说明应使用 Claude Code 的 `collaborating-with-codex` skill 来调度 Codex；实际操作者直接用 `codex exec` CLI，绕过了 skill 提供的 session 管理和格式化
- **改进方案**：flow step-4 instruction 应明确引导："使用 /collaborating-with-codex skill 进行 review（或手动使用 codex_bridge.py）"；同时 `codex_bridge.py` 本身应存在于项目中或 flow 应检测到 skill 可用性。此外应提示 Codex review 任务放到后台执行（`run_in_background`），两个 review（results + process）可并行，避免串行等待浪费时间
- **验收标准**：下一轮 E2E agent 使用 skill 且两个 review 并行执行

#### FL-15 flow step-6 未引导写入新发现和归档已修复（P2）

> **来源**：2026-05-17 E2E v38 流程体验
- **严重度**：P2 — flow 引导缺失导致 step-6 只做 "git diff additions" 检查，不告诉 agent 应该做什么
- **现象**：step-6 instruction 只说 "Update the issue tracker (short version). Flow checks git diff for current-session marker additions."，但没有引导 agent：(1) 将 E2E 中发现的新问题写入短版清单 (2) 将本轮已验证解决的问题移入 full 版归档 (3) 添加 version marker
- **改进方案**：step-6 instruction 应明确列出三件事：① 新发现写入短版 ② 已解决移入 full ③ 添加 "v{N}" marker 到 diff 中
- **验收标准**：agent 在 step-6 时无需用户提醒即可完成上述三件事

#### UX-12 SUSPICIOUS 标记对 grep 检查误报（P3）

> **来源**：2026-05-17 E2E v38 Foreman 评估
- **严重度**：P3 — 报告噪音
- **现象**：grep-based security checks（如 `grep -q 'hmac.compare_digest'`）在 <10ms 完成时被标记 `[SUSPICIOUS: completed in 5ms]`
- **根因**：SUSPICIOUS 阈值不区分命令类型；grep 天然快速
- **改进方案**：对 `grep` / `test -f` 等已知快速命令豁免 SUSPICIOUS 标记，或将阈值从 10ms 提高到 50ms
- **验收标准**：grep checks 不再显示 SUSPICIOUS

#### FL-16 E2E flow 结束后应停止 cccc 残留进程（P2）

> **来源**：2026-05-17 E2E v38 流程体验
- **严重度**：P2 — 资源泄漏
- **现象**：E2E flow 完成后 group 的 actors（foreman/worker PTY 进程）仍在运行，占用资源且可能与下一轮冲突
- **改进方案**：在 E2E flow 最后一步（step 6 improvement-register 之后）增加 step 7 cleanup，自动执行 `cccc group stop --group <GID>` 停止所有 actor 进程（保留 group 数据/ledger 不删除）
- **验收标准**：E2E flow 完成后本轮 actors 进程已停止，group 数据仍可查阅

---

### UX 系列（体验）

#### UX-8 claimed_paths 冲突提示应明确指出冲突任务对（P3）

> **来源**��2026-05-15 E2E v33 Foreman 体验反馈
- **严重度**：P3 — 体验改进
- **改进方案**：overlap 规则输出含冲突的两个任务 ID + 具体路径
- **验收标准**：overlap 错误信息包含 "T1 claims 'app/' which contains T2's 'app/routes.py'" 

### UX-5 ralph guide 自动生成能力指南（P2）

- **改进方案**：`ralph guide` 从 Pydantic schema + validation rules + CLI --help 自动生成能力指南
- **验收标准**：`ralph guide` 输出包含所有 Plan schema 字段、所有验证规则代码、所有 CLI 命令

---

### RL 系列（规则盲区）

#### RL-25 Ralph validate 无法检测 goal_behavior 中的实现方案与数据结构不兼容（P3）

> **来源**：2026-05-15 v34 plan Codex 审查
- **严重度**：P3 — 导致实现时才发现不可行
- **改进方向**：Agent 可覆盖（与 RL-22 同类）

### RL-22 goal_behavior 与源码语义不一致时 Ralph 无法检测（v33 Codex 审查���露）

- **改进方向**：Agent 可覆盖。`ralph flow` 的 Codex 审查步骤可系统性拦截此类问题。

---

## 五、Aegis 执行纪律整合（AD 系列）

> **来源**：2026-05-15 Aegis Method Pack 跨项目分析 + Codex 三轮独立审查
> **总体目标**：把 Aegis 方法论约束整合进 Ralph 验证层，形成"事前教育 → 事中拦截 → 事后兜底"三层闭环
> **核心原则**：不搬代码，提取方法论注入 Ralph。Aegis 是 advisory method pack，CCCC Daemon/Ralph/Foreman 是 runtime authority

### AD-1 AegisDiscipline 子模型 + TaskSpec.aegis 字段（P1 — schema 基础设施）

**优先级**：P1（所有 AD 规则的前置依赖）
**影响维度**：结构基础

**改动清单**：
1. `src/cccc/ralph/models.py` — 新增 `AegisDiscipline`（含 intent/repair_track/retirement_track 等嵌套模型）+ `TaskSpec.aegis: Optional[AegisDiscipline] = None`
2. `src/cccc/contracts/v1/ralph_ipc.py` — `TaskRef` 加 `aegis: Optional[Dict[str, Any]] = None`（用 Dict 避免循环 import）
3. `src/cccc/ralph/models.py` — `TaskSpec.to_task_ref()` 同步透传 aegis 字段
4. `src/cccc/ralph/plan_io.py` — strict plan 嵌套字段检查需覆盖 aegis 子模型
5. `src/cccc/ralph/cli.py` — `ralph schema` 输出加 Aegis 子模型
6. `src/cccc/ralph/guide_generator.py` — `MODEL_REFERENCES` 加 Aegis 子模型
7. `plans/_template.yaml` — 加 aegis 字段注释和示例

**兼容性要求**：
- 所有字段 Optional + default None/空，旧 plan 零影响
- `TaskRef.aegis` 用 `Dict[str, Any]` 不用强类型，避免 `contracts → ralph.models` 循环 import
- `AegisDiscipline` 子模型设 `extra="ignore"`，未来加字段不破坏旧 plan

**验收标准**：
- 旧 plan（无 aegis 字段）`ralph validate` 零新增 error/warning
- 带 aegis 的新 plan `ralph validate` 正常解析
- `TaskRef` 能接收并透传 aegis 数据到 prompt_builder 和 verification_gate
- `ralph schema` 输出包含 AegisDiscipline 完整字段

---

### AD-2 intent 推断 helper + discipline.py 规则基础设施（P1）

**优先级**：P1（规则注入的基础）
**影响维度**：结构基础

**改动清单**：
1. 新增 `src/cccc/ralph/aegis.py` — `effective_intent(task) -> str`（优先读 `aegis.intent`，fallback 到 title/goal 关键词推断）+ `has_patch_shape_risk(task) -> bool` 等 helper
2. 新增 `src/cccc/ralph/validation_rules/discipline.py` — 规则文件骨架
3. `src/cccc/ralph/validation_rules/__init__.py` — re-export discipline 模块
4. `src/cccc/ralph/validator.py` — `_collect_structural_issues()` 调用 discipline 规则
5. `src/cccc/ralph/agent.py` — `RULE_DOCS` 加文档、`RULE_VERSION_REGISTRY` 加版本

**intent 推断逻辑**：
- `aegis.intent` 已填 → 直接使用
- title/goal 含 fix/bug/debug/修复 → fix
- 含 add/feature/implement/新增 → feature
- 含 refactor/重构/migrate/迁移/replace/替换 → refactor
- 含 test/测试 → test
- fallback → general（不触发 intent 相关规则）
- 推断结果不写回 aegis.intent，只在 helper 返回

**验收标准**：
- `effective_intent()` 对 TaskSpec 和 TaskRef 两种输入都能工作
- discipline.py 内规则格式与现有 structural/coverage/contracts 一致
- `ralph explain --code AD_xxx` 能输出规则文档

---

### AD-3 首期 5 条高信号规则（P1 — 核心纪律）

**优先级**：P1
**影响维度**：结果 + 过程
**预期分数变化**：结果 4→4.5（减少 worker 乱加补丁和跳过验证的问题）

**来源 Aegis 协议 → 规则映射**：

| # | 规则码 | 级别 | Aegis 来源 | 检查逻辑 |
|---|--------|------|-----------|---------|
| 1 | `E_AEGIS_PLACEHOLDER_CONTENT` | error | writing-plans §No Placeholders | title/goal/acceptance 含 TBD/TODO/placeholder/"fill in"/"implement later" |
| 2 | `E_AEGIS_RETIREMENT_TRACK_MISSING` | error | dual-track governance §4 Hard Constraints | intent=refactor/migration 且新增 fallback/adapter/provider 但无 `aegis.retirement_track` |
| 3 | `W_AEGIS_FIX_NO_REPAIR_TRACK` | warning | systematic-debugging §Quality Gate + dual-track §3.1 Repair Track | intent=fix 但无 `aegis.repair_track`（root_cause、canonical_owner） |
| 4 | `W_AEGIS_TDD_NO_TEST_PATH` | warning | TDD §Verification Checklist | intent=fix/feature 的 claimed_paths 中无 test 文件（`test_`/`_test`/`tests/`） |
| 5 | `W_AEGIS_COMPLEX_MISSING_BASELINE` | warning | writing-plans §Required Outputs #2 | 多 deps（≥3）或有 contracts/critical_flows 的复杂 task 但 `aegis.baseline_refs` 为空 |

**改动文件**：`src/cccc/ralph/validation_rules/discipline.py`（5 个 `_check_xxx` 函数）

**验收标准**：
- 有 TBD 的 plan `ralph validate` 报 E_AEGIS_PLACEHOLDER_CONTENT
- refactor 任务无 retirement_track 报 E_AEGIS_RETIREMENT_TRACK_MISSING
- fix 任务无 repair_track 报 W_AEGIS_FIX_NO_REPAIR_TRACK
- 现有全量 pytest 零 regression

---

### AD-4 verification_gate Evidence 质量门（P1 — 完成时兜底）

**优先级**：P1
**影响维度**：结果
**预期分数变化**：结果 +0.5（防止 worker 交 "done" 了事）

**来源**：Aegis verification-before-completion §Evidence Card

**改动清单**：
1. `src/cccc/daemon/foreman/verification_gate.py` — 在 `process_completed_event()` 的 `verify_completion()` 之后、`record_verification_result` 之前加纯函数 `_check_aegis_evidence(payload, task_ref) -> List[VerificationCheck]`
2. 失败结果通过 `VerificationCheck(name="aegis_evidence_card", outcome="failed", details={...})` 表达（不直接改 VerificationResult 顶层字段，因为它是 `extra="forbid"`）

**检查逻辑**：
- evidence 为空或只含 "done"/"完成"/"已完成" → fail
- intent=fix 且 evidence 无根因关键词（root cause/根因/原因） → warning
- intent=refactor 且 evidence 无退役确认关键词（retire/delete/remove/删除/退役） → warning
- challenge 模式下 evidence 不过关 → verification failed
- ralph 模式下 evidence 不过关 → 附加 warning 但不阻止

**兼容性**：无 aegis 字段的 task → 跳过检查（渐进式生效）

**验收标准**：
- worker 交空 evidence 时 challenge 模式 verification failed
- 有实质 evidence 时正常通过
- 旧 workflow（无 aegis）不受影响

---

---

### AD-7 suggest 阶段 Aegis 快检（P3 — 事中拦截）

**优先级**：P3（可推迟到首期规则跑通后）
**影响维度**：过程

**改动清单**：
1. `src/cccc/daemon/foreman/ralph_service.py` — `suggest_ready_batch()` 加 task-local Aegis E_ 快检
2. `src/cccc/ralph/core.py` — CLI `suggest()` 的 `BatchResult.blocked` 加 Aegis blocked reason（保持 CLI/daemon 行为一致）

**E_ 规则的 task 不进 ready batch**，W_ 规则只追加 rationale 不阻止。

**可观测性**：被拦截的 task 写 logger + rationale 说明原因，避免"所有 task 被过滤但调用方只看到 None"。

**验收标准**：
- 有 E_AEGIS_PLACEHOLDER_CONTENT 的 task 不出现在 suggest 结果中
- blocked reason 在 rationale 或 log 中可见

---

### AD-8 二期规则扩展（P3 — 首期跑通后再加）

**优先级**：P3
**影响维度**：结果 + 过程

**候选规则**（首期验证无误报后分批加入）：

| 规则码 | Aegis 来源 | 检查内容 |
|--------|-----------|---------|
| `W_AEGIS_PATCH_SHAPE_TRIAGE_MISSING` | systematic-debugging §Patch-Shape Triage | 涉及 fallback/adapter/guard 但无 patch_shape_triage |
| `W_AEGIS_RIPPLE_TRIAGE_MISSING` | Ripple Signal Triage | 改了 shared module 但下游不在 awareness_paths |
| `W_AEGIS_DECISION_HYGIENE_MISSING` | first-principles §Decision Hygiene | 出现 duplicate owner/new owner 风险但无 decision review |
| `W_AEGIS_DRIFT_CHECK_MISSING` | long-task-continuation §Drift Check | 多阶段任务缺 drift_check |
| `W_AEGIS_PLAN_NO_COMPAT_BOUNDARY` | writing-plans §Required Outputs #4 | plan 级无兼容性声明 |
| `E_AEGIS_RIPPLE_VERIFICATION_TOO_NARROW` | TDD §Regression Scope | 改了 contract/shared/core 但 verification 只 cover 自己 |
| `W_AEGIS_EVIDENCE_NO_COVERAGE_CLAIM` | verification-before-completion §Evidence Card | evidence 没有 covered/not covered 说明 |

**Gemini semantic review 扩展**（agent/challenge 模式）：
- Patch Shape 分析、Canonical Owner 验证、退役表面变化、Architecture drift、重复 owner 检测

**验收标准**：每条新增规则有对应测试 + 误报率 < 10%

---

## 后续方向

### Modal 集成（待调研）

将 Modal 集成到 CCCC 系统中。具体集成方案和优先级待后续讨论确定。
