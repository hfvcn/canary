# CCCC 问题清单 v5 (未解决) — Ralph 改进专项

> 日期：2026-04-03（v4 E2E 实战后更新）
> 状态：3 项待改进（2 项 validate 噪音 + 1 项 v4 实战新发现）
> 全量版本：[问题清单-v5-ralph-full.md](./问题清单-v5-ralph-full.md)
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


---

## 二、已知局限（NOTE 类，无代码改进空间）

| 编号 | 观察 | 说明 |
|------|------|------|
| RV-15 | Ralph 新规则自身的 bug 无法自检 | 印证 findings #13：结构校验和代码审查互补 |
| RV-18 | goal_behavior 中引用的函数名可能不存在 | 超出结构校验范围，需 Codex 审查 |
| RV-19 | 模型扩展可能破坏已有语义（awareness_paths 案例） | Codex 审查发现，已在实施中正确处理 |
| RV-20 | monitor wiring 调用位置可行性无法静态验证 | TaskEvent 类型受限，已改为公共 API 方案 |
| RV-21 | accumulator 重构易引入分类回归（conftest 案例） | Wave 6 手动修复，提示需完整回归测试 |
| RV-22 | W_UNCLAIMED_TEST_FOR_SOURCE 对高 import 文件产生大量警告 | RV-10 indirect→hint 已缓解 |
| RO-5n | W_FLOW_SEGMENT_UNOWNED 对 verification role 的 T-int 类任务过度报警 | T-int 天然覆盖所有 flow 但不 claim 入口，应考虑 verification role 豁免 |
| RO-6n | 同一 entrypoint 被多个 flow 使用时 W_FLOW_OWNER_NO_VERIFICATION 噪音大 | T3/T4/T5 共享 validator.py 但各自只验证自己的 flow，触发大量 NO_VERIFICATION |
| RO-10n | verification 命令强度无法检测连接级/运行时语义 bug | v4 pytest 全过但 SQLite FK 未启用；印证 findings #13 结构校验和代码审查互补 |
