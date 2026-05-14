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
> **结果分瓶颈（v32 更新）**：结果分首次达到 4/5（0 CRITICAL）。瓶颈从"实现 bug"转向"plan 编写体验"（validate 迭代成本、warning 噪音）。BP-2 运行时模块调度 + BP-5 E2E 阻塞模式仍待实现
> 验证轮次（2026-05-14 v31 修复后）：全量 pytest 2628 passed / 0 failed / 120 skipped
> E2E v28 验证：综合 4.2/5（结果 3/5，过程 5/5，体验 4.5/5）
> E2E v29 验证：综合 3.3/5（结果 2/5，过程 4/5，体验 4/5）——v30 新能力全部实战验证通过
> **E2E v32 验证：综合 4.3/5（结果 4/5，过程 5/5，体验 4/5）——历史新高**
> 全量版本：[问题清单-v5-ralph-full.md](./问题清单-v5-ralph-full.md)
> 审查依据：[v5-综合审查报告.md](./v5-综合审查报告.md)
> 蓝图对齐：[工作流蓝图.md](./工作流蓝图.md) v0.3（两阶段拆分 + Ralph Agent）
> 评估报告：[e2e-实战评估报告-v29.md](./e2e-实战评估报告-v29.md)（最新） | [e2e-实战评估报告-v28.md](./e2e-实战评估报告-v28.md) | [e2e-实战评估报告-v27.md](./e2e-实战评估报告-v27.md) | [e2e-实战评估报告-v26.md](./e2e-实战评估报告-v26.md) | [e2e-实战评估报告-v25.md](./e2e-实战评估报告-v25.md) | [e2e-实战评估报告-v24.md](./e2e-实战评估报告-v24.md) | [e2e-实战评估报告-v23.md](./e2e-实战评估报告-v23.md) | [e2e-实战评估报告-v22.md](./e2e-实战评估报告-v22.md) | [e2e-实战评估报告-v21.md](./e2e-实战评估报告-v21.md) | [e2e-实战评估报告-v20.md](./e2e-实战评估报告-v20.md) | [e2e-实战评估报告-v19.md](./e2e-实战评估报告-v19.md) | [e2e-实战评估报告-v18.md](./e2e-实战评估报告-v18.md) | [e2e-实战评估报告-v17.md](./e2e-实战评估报告-v17.md) | [e2e-实战评估报告-v16.md](./e2e-实战评估报告-v16.md) | [e2e-实战评估报告-v15.md](./e2e-实战评估报告-v15.md) | [e2e-实战评估报告-v14.md](./e2e-实战评估报告-v14.md)
>
> **本文档只保留未解决的改进项和已知局限。已完成条目与历史实现记录保存在 full 版本中。**

---

## 一、未解决的 RO 改进项

> v30 已解决：RO-74/75/76 的实现记录已迁入 full 版本。
> v31 已解决：RO-77/78/79 的实现记录已迁入 full 版本。
> v32 E2E 验证通过：RO-77 ✅ / RO-78 ✅ / BP-2 ✅ / BP-4 ✅。迁入 full 归档。
> v31 Codex 审查新发现：RO-80/81。
> v32 E2E 新发现：UX-1/2/3（体验类改进）。

### RO-80 challenge/agent 验证不可用时降级为通过

**优先级**：P2
**影响维度**：过程
**预期分数变化**：过程 +0.5

**触发实例**：
> v31 Codex 审查发现 ralph_service.py 中 challenge/agent 路径把 Gemini/agent 验证不可用降级为通过结果（RuntimeError、OSError、timeout 等基础设施失败变成 warning 而非 fail-closed）。

**根因**：agent 验证的异常处理策略是 fail-open 而非 fail-closed。

**改进方案**：基础设施错误应返回 `failed` 而非降级为 `passed` + warning。

**验收标准**：Gemini 不可用时 challenge 模式返回 `failed`。

---

### RO-81 _check_cross_task_io_contracts 多上游场景误报

**优先级**：P3
**影响维度**：体验
**预期分数变化**：体验 +0.25

**触发实例**：
> v31 Codex 审查发现 `_check_cross_task_io_contracts()` 对每个依赖单独比较 keys，当多个上游共同满足输入时会误报 W_CROSS_TASK_IO_MISMATCH。

**根因**：验证规则只检查 1:1 依赖关系，不支持 N:1 聚合。

**改进方案**：收集所有上游 expected_output keys 的并集后再与 expected_input 比较。

**验收标准**：多依赖任务的 expected_input 由多个上游共同满足时不报 warning。

---

## 1.5、v32 新发现 — 体验类改进（UX）

### UX-1 provides/consumes 格式文档与 schema 不一致（P2）

**优先级**：P2
**影响维度**：体验
**预期分数变化**：体验 4→4.5

**触发实例**：
> v32 Foreman 用字符串格式 `provides: "backend_api"` 被 validate 拒绝，需 `{name, kind}` 对象。capability guide 示例用 `mode` 但 schema 要求 `level`。5 次 validate 至少 2 次因格式问题。

**改进方案**：foreman-capability-guide.md 增加完整 provides/consumes 示例，与 `ralph validate --show-schema` 一致。

**验收标准**：下一轮实战 Foreman validate 迭代 ≤3 次。

---

### UX-2 Greenfield 项目 W_VERIFICATION_SHAPE_UNKNOWN 大量重复（P2）

**优先级**：P2
**影响维度**：体验
**预期分数变化**：体验 +0.3

**触发实例**：
> v32 4 任务 plan 产生 17 warnings + 20 hints，W_VERIFICATION_SHAPE_UNKNOWN ×12 占主要噪音。

**改进方案**：`--compact` 模式或 warning 分级（actionable vs informational）。

**验收标准**：同类 4 任务 plan 验证输出 ≤10 条 warning/hint。

---

### UX-3 E_VERIFICATION_TARGET_MISSING_FILE 在 greenfield 应降级为 warning（P2）

**优先级**：P2
**影响维度**：体验
**预期分数变化**：体验 +0.2

**触发实例**：
> v32 T4 integration 的 verification target 由上游 task 创建，validate 阶段不存在报 error。

**改进方案**：当 target 路径被上游 claimed_paths 覆盖时降级为 warning。

**验收标准**：上游 task claim 的路径中的 verification target 不报 error。

---

## 二、未解决的 RL 改进项（Ralph 规则盲区）

### 已知盲区分类

| 盲区类型 | 代表编号 | 描述 | 改进方向 |
|---------|---------|------|---------|
| goal_behavior 语义验证 | RL-1/2/10/12/13/16/17/19/20 | Ralph 不验证 goal_behavior 中的技术断言是否与源码一致 | 🤖 Agent 可覆盖 |
| 字段透传完整性 | RL-9/18 | 新增字段从定义到使用的完整路径未被 claim | 需 Pydantic field 感知 |
| 接口变更测试覆盖 | RL-8/15 | 新增字段/参数破坏未 claim 的测试 | 增强 `W_UNCLAIMED_TEST_FOR_SOURCE` |
| task 合并检测 | RL-7 | 多个不相关 issue 合并为一个 task | 新增 `W_TASK_ADDRESSES_DISJOINT` |
| 因果关系检测 | RL-4 | 同一 bug 的多个症状被当作独立问题 | Agent 部分覆盖 |
| 控制流时序分析 | RL-14 | 修改时机过晚导致后续步骤使用旧值 | 需 data-flow propagation |
| ~~claimed_paths 冲突无依赖~~ | ~~RL-21~~ | ~~两个 task claim 同一文件但无 depends_on~~ | ✅ v30 已实现 `W_SHARED_PATH_NO_DEPENDENCY`（warning 级别） |

> **总结**：Ralph 最关键的缺失是 goal_behavior 语义验证能力（9 个实例）。Agent 可覆盖大部分，但需要更系统的集成。
> ~~RL-21~~ 已在 v30 修复：`_check_implicit_serialization` 升级为 `W_SHARED_PATH_NO_DEPENDENCY`（warning 级别），消息包含冲突路径和建议。

---

## 三、蓝图偏移：结果分天花板根因（2026-05-13 v28 后更新）

> v28 验证了验收标准具体化可以消除反复出现的实现 CRITICAL（v1-v27 的 3 个 CRITICAL 在 v28 全部消除）。但结果分天花板从"实现 bug"提升到"测试覆盖缺口"——FK 测试伪覆盖暴露 verification 无法检查"测试是否充分"。

| 设计要素 | 蓝图 | 当前实现 | 状态 |
|---------|------|---------|------|
| 第一层：Task 间 DAG 调度 | Ralph suggest + 依赖门控 | ✅ 已实现且稳定（v25-v28 连续通过） | 完成 |
| 验证 ralph 模式 | shell 命令 exit code | ✅ 已实现 | 完成 |
| 验证 agent 模式 | Foreman 预设模拟测试用例 | ✅ mock_tests 在 agent 模式下执行，Worker 不可见 | **BP-1 完成** |
| Worker 黑盒模型 | 输入(需求+接口规范+模拟输入) → 输出(模块) | ⚠️ expected_input/output 已渲染到 prompt，但需 Foreman 填写 | **BP-3 基础完成** |
| 第二层：Task 内模块化拆分 | Foreman 拆 Module + 统一接口规范 | ❌ 全缺失 | **BP-2** |
| 模块拼接 + 批次 E2E | 批次完成 → 独立 E2E 验证 | ⚠️ 批次完成日志+workflow 自动终态已实现，但无拼接步骤 | **BP-5 部分** |
| 并行解耦第二层 | 模拟 I/O + 接口匹配验证 | ❌ 只有静态校验 | **BP-4** |

### 最小可行路径（结果分 3→4 的关键）

```
1. ✅ plan.yaml 支持 mock_tests 字段（Foreman 预设模拟输入+预期输出）
2. ✅ verify gate 的 agent 模式执行 mock_tests（而非 Gemini 代码审查）
3. ✅ Worker 看不到 mock_tests 内容（对抗性）
```

> **v30 进展**：最小可行路径三项均已实现。下一步关键是让 Foreman 在计划生成时主动填写 mock_tests 和 expected_input/output。

---

## 四、已知局限（NOTE 类，无代码改进空间）

| 编号 | 观察 | Agent 覆盖 |
|------|------|-----------|
| RV-15 | Ralph 新规则自身的 bug 无法自检 | 部分 |
| RV-18 | goal_behavior 中引用的函数名可能不存在 | ✅ 可覆盖 |
| RV-19 | 模型扩展可能破坏已有语义 | 部分 |
| RV-20 | monitor wiring 调用位置可行性无法静态验证 | 部分 |
| RV-21 | accumulator 重构易引入分类回归 | — |
| RV-22 | W_UNCLAIMED_TEST_FOR_SOURCE 对高 import 文件噪音大 | — |
| RO-5n | W_FLOW_SEGMENT_UNOWNED 对 verification role 过度报警 | — |
| RO-6n | 同一 entrypoint 被多个 flow 使用时噪音大 | — |
| RO-10n | verification 命令强度无法检测运行时语义 bug | ✅ 可覆盖 |
| RO-11n | "删除函数"的副作用链无法静态检测 | 部分 |
| RO-12n | 同一文件多入口只覆盖部分时不报警 | 部分 |

---

## 五、版本历史评分追踪

| 版本 | 日期 | 结果 | 过程 | 体验 | 综合 | 关键变化 |
|------|------|------|------|------|------|----------|
| v1 | 04-01 | 2 | 1 | 2.5 | 1.8 | 基线 |
| v15 | 05-01 | 3 | 5 | 4 | 4.0 | 历史最高（至 v27） |
| v20 | 05-03 | 3 | 5 | 3 | 3.7 | 过程首次满分 |
| v27 | 05-13 | 2 | 4 | 4 | 3.3 | Gemini 排除成功 |
| v28 | 05-13 | 3 | 5 | 4.5 | 4.2 | 前历史最高 |
| v29 | 05-13 | 2 | 4 | 4 | 3.3 | v30 新能力全部验证(BP-1拦截+BP-3渲染+RO-76报错); codex 0%可靠(5/5 stall); 8任务暴露跨任务CRITICAL; RO-77/78/79新发现 |
| **v32** | **05-14** | **4** | **5** | **4** | **4.3** | **新历史最高**; RO-77/78确认修复; 0 CRITICAL; 过程满分; 100%自动化+零retry; 瓶颈转向plan编写体验; UX-1/2/3新发现 |
