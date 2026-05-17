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
> 验证轮次（2026-05-17 v39 修复后）：全量 pytest 2913 passed / 0 failed / 120 skipped
> E2E v28 验证：综合 4.2/5（结果 3/5，过程 5/5，体验 4.5/5）
> E2E v29 验证：综合 3.3/5（结果 2/5，过程 4/5，体验 4/5）
> **E2E v32 验证：综合 4.3/5（结果 4/5，过程 5/5，体验 4/5）——历史新高**
> E2E v33 验证：综合 4.0/5 | E2E v34 验证：综合 3.7/5 | E2E v35 验证：综合 2.3/5 | E2E v35b 验证：综合 3.3/5
> E2E v36 验证：综合 4.0/5 | E2E v37 验证：综合 3.3/5 | **E2E v38 验证：综合 4.2/5**
> **E2E v39 验证（2026-05-17，FastAPI Bookmark Service）：综合 4.3/5（结果 4.5/5，过程 4.5/5，体验 4/5）——历史并列最高**
> 全量版本：[问题清单-v5-ralph-full.md](./问题清单-v5-ralph-full.md)
> 评估报告：[e2e-实战评估报告-v39.md](./e2e-实战评估报告-v39.md)（最新）
>
> **本文档只保留未解决的改进项和已知局限。已完成条目与历史实现记录保存在 full 版本中。**

---

## 未解决改进项

### RO 系列（运行时/验证）

#### RO-96 Challenge reviewer 读不到源代码——attach 路径解析 bug（P0）

> **来源**：2026-05-17 E2E v37 实测
- **严重度**：P0 — challenge reviewer 100% 误判率，一行修复解锁全部 agent 审查能力
- **现象**：`cccc attach .` 通过 daemon 执行时，CLI 传相对路径 `"."` 给 daemon → scope url 指向 daemon cwd 而非实际 workspace
- **修复方案（一行）**：`group_cmds.py:26` 传 `str(Path(args.path).resolve())`
- **验收标准**：`cccc attach .` 后 scope.url 指向正确目录；challenge reviewer 能读到源代码
- **v39 状态**：代码已修复，但 v39 E2E 使用绝对路径 attach 未直接触发验证

#### RO-99 Challenge reviewer prompt 注入安全 checklist（P1）

> **来源**：2026-05-17 v37 复盘（C 路径设计）
- **严重度**：P1 — 让 Gemini 做实质安全审查而非仅"完成判定"
- **改进方案**：从 plan.critical_flows 提取安全关键词，注入 verification prompt
- **验收标准**：plan 含 security critical_flow → Gemini prompt 含安全 checklist
- **v39 状态**：代码已修复，但 v39 E2E 未使用 challenge mode，未触发

#### AD-11 validate 时 LLM 生成 behavioral security checks（P1）

> **来源**：2026-05-17 v37 复盘（B 路径设计）
- **严重度**：P1 — 让安全检测在 shell 层可执行
- **改进方案**：`ralph validate --generate-security-checks` 调用 LLM 生成 behavioral test 命令
- **验收标准**：对含安全 critical_flow 的 plan 生成 ≥3 个 behavioral check
- **v39 状态**：代码已修复，但 v39 E2E 未使用此功能

---

### FL 系列（Flow 改进）

#### FL-17 / FL-17b solve flow 完成后应自动清除 .ralph-flow/state.json（P2 — 复现）

> **来源**：2026-05-17 E2E v38 + v39 复现
- **严重度**：P2 — 残留状态阻塞新 flow 启动
- **现象**：solve flow 完成后 `.ralph-flow/state.json` 残留。v39 E2E 启动时读到旧状态报 "Flow solve completed"
- **根因**：FL-17 修复可能只覆盖 workspace 目录的清理，未覆盖 cwd 下残留
- **验收标准**：solve flow 完成后 `.ralph-flow/state.json` 不存在

#### FL-16 E2E flow 结束后应停止 cccc 残留进程（P2）

> **来源**：2026-05-17 E2E v38/v39 流程体验
- **严重度**：P2 — 资源泄漏
- **现象**：E2E flow 完成后 actors 仍在运行
- **改进方案**：flow 最终步骤自动执行 `cccc group stop`
- **验收标准**：E2E flow 完成后 actors 进程已停止
- **v39 状态**：代码已添加 step 7 cleanup，但未自动执行（flow 在 step 6 后报 completed）

#### FL-14 flow Codex 步骤未引导使用 skill 且未提示并行执行（P2）

> **来源**：2026-05-17 E2E v38 + solve flow 流程体验
- **严重度**：P2 — flow 引导缺失
- **改进方案**：所有 Codex flow step instruction 补充 skill 引导和并行执行提示
- **验收标准**：agent 在 Codex 步骤时自动选择 skill 且多任务并行
- **v39 状态**：代码已修复（instruction 更新），v39 E2E step-4 格式要求已生效

---

### UX 系列（体验）

#### UX-13 Foreman 未在 workflow.completed 后自动生成 WORKFLOW_EVALUATION.md（P3）

> **来源**：2026-05-17 E2E v39 step 4
- **严重度**：P3 — 体验改进
- **现象**：workflow 完成后 foreman 未主动生成评估文档，需 observer 显式要求
- **改进方案**：foreman system prompt 或 completion handler 加入自动生成 evaluation 指令
- **验收标准**：workflow 完成后 foreman 自动生成 WORKFLOW_EVALUATION.md

#### UX-14 Worker 首任务冷启动 stall 阈值过低（P3）

> **来源**：2026-05-17 E2E v39 T1 执行
- **严重度**：P3 — stall 警告噪音
- **现象**：Worker-1 首个任务 300s 时触发 stall warning，实际 ~400s 完成
- **改进方案**：首任务 stall 阈值放宽至 600s
- **验收标准**：首任务 400s 内完成时不触发 stall warning

---

### 未分类

#### FL-18 flow step-6 归档迁移应为 blocking 而非 advisory（P2）

> **来源**：2026-05-17 E2E v39 step 6
- **严重度**：P2 — 已解决条目在短版中残留，每次都要用户手动提醒清理
- **现象**：step-6 检测到 "completed-but-not-archived: ['AD-1', 'FL-4', 'RO-84', 'SL-1']" 但仅输出 advisory，不阻塞。agent 看到 advisory 也未主动执行归档迁移，直到用户显式要求
- **根因**：`_check_improvement_register` 将归档检测设为 advisory 而非 blocking；flow instruction 也未明确要求 "先完成归档再 next"
- **改进方案**：
  1. step-6 检测到 completed-but-not-archived 时设为 FAIL（不是 advisory），强制 agent 执行归档后才能通过
  2. 或：提供 `ralph tracker archive --version v39` 自动执行迁移（从短版删除已完成条目详情、写入 full 版归档段落）
- **验收标准**：step-6 有 unarchived 条目时 flow next 不通过；归档完成后才能前进到 step 7

#### PLN-1 ledger event too large 导致 validate 事件写入失败（P2）

> **来源**：2026-05-17 v39 ralph validate 输出
- **严重度**：P2 — 审计可追溯性断裂
- **现象**：大型 plan（29 tasks）validate 时超过 256KB ledger 限制
- **改进方案**：validate 事件 payload 改为 compact 格式（digest + counts）
- **验收标准**：29-task plan validate 时 ledger 事件成功写入

---

## 后续方向

### Modal 集成（待调研）

将 Modal 集成到 CCCC 系统中。具体集成方案和优先级待后续讨论确定。
