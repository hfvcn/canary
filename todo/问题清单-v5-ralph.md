# CCCC 问题清单 v5 (未解决) — Ralph 改进专项

> 日期：2026-04-04（v5.2 蓝图对齐更新）
> 已完成：RO-7n/12/13n/14n/15/16/17/18/19/20/21/22/23/24/25/26/27/28/29/32/33/34/35/37/38/39/40/41/43/44、RA-1/2/3/4、RF-1/2/3/4/5
> E2E v15 验证：综合 4.0/5（结果 3/5，过程 5/5，体验 4/5）——历史最高
> E2E v16 验证：综合 3.0/5（结果 3/5，过程 3/5，体验 3/5）——PTY worker 可靠性 + digest 同步退步
> E2E v17 验证：综合 2.3/5（结果 2/5，过程 2/5，体验 3/5）——challenge mode 首次运行但 verify gate cwd P0 bug 拖垮全局
> E2E v18 验证：综合 2.7/5（结果 3/5，过程 2/5，体验 3/5）——RO-41 cwd 修复生效，0 CRITICAL，challenge 假阳性是唯一瓶颈
> E2E v19 验证：综合 3.0/5（结果 3/5，过程 3/5，体验 3/5）——RO-44 --force 解除死锁，自动化率88.9%，depends_on首次通过
> 全量版本：[问题清单-v5-ralph-full.md](./问题清单-v5-ralph-full.md)
> 审查依据：[v5-综合审查报告.md](./v5-综合审查报告.md)
> 蓝图对齐：[工作流蓝图.md](./工作流蓝图.md) v0.3（两阶段拆分 + Ralph Agent）
> 评估报告：[e2e-实战评估报告-v19.md](./e2e-实战评估报告-v19.md)（最新） | [e2e-实战评估报告-v18.md](./e2e-实战评估报告-v18.md) | [e2e-实战评估报告-v17.md](./e2e-实战评估报告-v17.md) | [e2e-实战评估报告-v16.md](./e2e-实战评估报告-v16.md) | [e2e-实战评估报告-v15.md](./e2e-实战评估报告-v15.md) | [e2e-实战评估报告-v14.md](./e2e-实战评估报告-v14.md)
>
> **本文档只保留未解决的改进项和已知局限。已完成条目与历史实现记录保存在 full 版本中。**

## 一、待实施改进

### RO-42 challenge verification 假阳性（P0，v17 发现，v19 仍存在）
> **来源**：2026-05-02 E2E v17 实战；v18/v19 连续印证
- **严重度**：High — 唯一剩余瓶颈，阻止过程分突破 3/5
- **现象**：challenge verifier（Gemini agent）做纯 LLM 静态分析不执行代码，对实际存在的验证逻辑误判为"未实现"
  - v17 T1："Empty titles not rejected"（实际 field_validator 存在）、"Script tags not sanitized"（实际 re.sub 存在）
  - v18 T2/T3："javascript: URLs not rejected"（实际 regex 存在）、"search not case-insensitive"（实际 .ilike() 存在）
  - v19 T1-T4：全部 4 个任务被假阳性拦截，需 `--force` 绕过
- **根因**：challenge agent 不执行 verification.checks，纯依赖 LLM 代码阅读判断功能是否实现
- **改进方案**：
  1. ✅ challenge agent 必须先看 worker verification.checks 的执行结果（compile+test 全 pass）——**已实现：`_run_verification_pre_check()` 先执行 verification command，结果注入 prompt**
  2. ✅ Agent 审查时传入 checks stdout/stderr 作为上下文，减少"功能未实现"类误判——**已实现：`verification_output` + `source_code` + `git_diff` 三类证据注入**
  3. 考虑让 Agent 可编写并执行反例测试脚本（而非仅静态分析）
- **验收标准**：challenge verifier 不再对已通过 compile+test 的代码产生"功能未实现"假阳性；至少 50% 任务无需 `--force` 即通过 challenge
- **压力测试验证**（2026-05-03）：13 个 live Gemini 测试全部正确判定（改进前 0/5 → 改进后 13/13），幻觉率从 100% 降为 0%
- **workaround**：`cccc task complete --force`（RO-44 已实现）

### RO-30 RalphService 运行时接口与文档设计漂移（P2，部分解决）
> **来源**：2026-04-24 Codex 设计审查
- **严重度**：Medium — 文档承诺的观察能力与当前可执行能力不一致
- **现象**：设计文档仍描述 Ralph 为外部 Python daemon/Git watcher；`merge_worktree()` 恒返回 `False`，`analyze_import_graph()` / `detect_test_impact()` 返回空列表
- **改进方案**：统一目标架构：明确 Ralph 的三种形态（CLI 静态验证、daemon 内 verify gate、可选 Agent 审查）及其边界
- **验收标准**：docs 与代码职责一致；stub 接口要么落地，要么不出现在主能力清单

---

## 一-C、Ralph 本轮不足记录（2026-05-02 fix-v5-remaining 计划轮次）

> 来源：fix-v5-remaining-ro38-40.yaml 计划生成 → Ralph validate → Codex 审查

### 假阴性（验证通过后 Codex 发现的漏洞）

| 编号 | 现象 | Ralph 盲区 | 改进方向 |
|------|------|-----------|---------|
| RL-1 | 计划描述已完成的功能为待实施 | Ralph 无法检测 goal_behavior 与代码实际是否一致 | 🤖 Agent 可覆盖（已确认：git diff 为空 + 源码对比可检测） |
| RL-2 | goal_behavior 中代码路径引用错误 | Ralph 不验证 goal_behavior 中代码位置/函数名 | 🤖 Agent 可覆盖（已确认：T2-wrong-ref 正确检测到 validate_input() 不存在） |
| RL-3 | 含 shell 操作符的验证命令被跳过未检查 | W_VERIFICATION_COMPLEX_SHELL_SKIPPED 跳过后无语义检查 | 考虑基本模式匹配 |
| RL-4 | 同一 bug 的多个症状被当作独立问题 | Ralph 无因果关系检测 | 🤖 Agent 部分覆盖（beyond-scope 批量审查可传多 issue，但 task verification 逐任务无法跨任务推理） |

### 验证阶段困难（假阳性/噪音）

| 编号 | 现象 | 改进方向 |
|------|------|---------|
| RL-5 | W_INDIRECT_TEST_IMPORT 对高 import 文件爆炸（44 条） | 对 ≥10 条折叠为单条摘要 |
| RL-6 | W_COVERS_NOT_EXERCISED 对集成任务误报 | 已知局限（需 import 图分析） |

---

## 二、已知局限（NOTE 类，无代码改进空间）

| 编号 | 观察 | Agent |
|------|------|-------|
| RV-15 | Ralph 新规则自身的 bug 无法自检 | 🤖 部分覆盖（能标记可疑 validate 输出，但无法检查规则实现本身） |
| RV-18 | goal_behavior 中引用的函数名可能不存在 | 🤖 可覆盖（已确认：T3-phantom-func 正确检测到 delete_orphan_nodes() 不存在于源码） |
| RV-19 | 模型扩展可能破坏已有语义 | 🤖 部分覆盖（能读 claimed_paths 源码，但缺跨项目 import graph） |
| RV-20 | monitor wiring 调用位置可行性无法静态验证 | 🤖 部分覆盖（能读源码验证调用存在，但无运行时 trace） |
| RV-21 | accumulator 重构易引入分类回归 | — |
| RV-22 | W_UNCLAIMED_TEST_FOR_SOURCE 对高 import 文件噪音大 | — |
| RO-5n | W_FLOW_SEGMENT_UNOWNED 对 verification role 的 T-int 过度报警 | — |
| RO-6n | 同一 entrypoint 被多个 flow 使用时噪音大 | — |
| RO-10n | verification 命令强度无法检测运行时语义 bug | 🤖 可覆盖（已确认：agent 现有 verification_output 作为 ground truth，T-subtle-1/T-test-fail 正确检测） |
| RO-11n | 计划中"删除函数"的副作用链无法静态检测 | 🤖 部分覆盖（已确认：T4 正确检测到 _run_check 仍被引用，但仅限 claimed_paths 内跨文件） |
| RO-12n | 同一文件多入口只覆盖部分时不报警 | 🤖 部分覆盖（agent 能读源码枚举函数，T-large-file 安全审计确认可扫描文件内容） |
