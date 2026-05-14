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

### UX-4 plan.yaml 模板维护 + 能力指南补全（P1）

**优先级**：P1
**影响维度**：体验
**预期分数变化**：体验 4→4.5，间接提升结果（batch_e2e_command 触发后可拦截更多问题）

**触发实例**：
> v32 Foreman 不知道 `batch_e2e_command` 字段存在——capability guide 和 workflow doc 中都未提及。validate 输出 `W_BATCH_E2E_NO_COMMAND` 但淹没在 17 warnings 噪音中。同时 provides/consumes 格式（`{name, kind}` vs 字符串）、verification.level 取值、from_task 字段等均因文档不精确导致多次 validate 迭代。

**根因**：foreman-capability-guide.md 靠人工扫描代码库生成，速度慢且必然遗漏新增字段。plan.yaml 模板（plans/_template.yaml）未包含所有字段的完整示例。

**改进方案**：
1. 更新 `plans/_template.yaml` 为**全字段模板**（含 batch_e2e_command、provides/consumes 完整格式、module_spec、suppress_codes 等），加注释说明每个字段用途和取值范围
2. 在 foreman-capability-guide.md 中指向模板，并增加 provides/consumes、batch_e2e_command 的具体示例
3. 此项为文档改动，零代码风险

**验收标准**：
- plans/_template.yaml 包含所有 Plan schema 字段
- 下一轮 E2E Foreman validate 迭代 ≤3 次
- Foreman 在 plan 中使用 batch_e2e_command

---

### UX-6 ralph flow 渐进式流程引导（P1）

**优先级**：P1
**影响维度**：体验 + 过程（工作流外流程的可靠性）
**预期分数变化**：间接提升所有维度（消除观察者步骤遗漏）

**触发实例**：
> v32 E2E 中观察者（Claude Code）在 Phase 4 用内置 agent 代替 Codex（被用户纠正后才改），Phase 6 未主动执行（等用户提醒）。长上下文记忆衰减导致流程步骤遗漏。修复流程同理——Codex 审查、缺陷记录、能力指南生成等步骤在长对话中容易被跳过。

**根因**：工作流外流程（修复流程、E2E 流程）完全依赖 AI 记忆文档约束，长上下文下记忆衰减导致步骤遗漏。且操作者自报式验证存在作弊/幻觉风险。

#### 核心设计原则

1. **渐进式披露**：每完成一步才显示下一步指令和验证标准，操作者 working set 永远只有一步
2. **触发式自动检查**：操作者做完后运行 `ralph flow next`，Ralph 自动去检查证据，不依赖操作者自报内容
3. **Codex 强制验证**：所有要求 Codex 的步骤，检查约定目录下 codex_bridge.py 输出 JSON 结构，内置 agent 无法产生此格式
4. **失败不前进**：检查不通过时重新显示当前步骤指令和缺失项，不跳过

#### 约定目录结构

```
{workspace}/
  .ralph-flow/
    state.json                # 流程状态
    step-1-understand/        # 各步骤产出物目录
    step-2-plan/
    step-3-review/            # Codex 输出 JSON 放这里
    step-4-gaps/
    step-5-execute/           # 每个 batch 的 Codex 输出 JSON
    step-6-verify/
    step-7-guide/
```

#### state.json 结构

```json
{
  "flow_type": "solve",
  "workspace": "/path/to/project",
  "started_at": "2026-05-14T18:00:00Z",
  "current_step": 3,
  "params": {
    "test_cmd": "pytest",
    "tracker": "todo/issues.md",
    "guide_output": "docs/capability-guide.md"
  },
  "steps_completed": [1, 2],
  "steps_failed": {"3": {"attempts": 1, "last_error": "no codex output"}}
}
```

#### Codex 输出验证函数（通用）

所有标注"Codex"的步骤共用同一验证逻辑：

```python
def validate_codex_output(dir_path, min_content_length=200):
    """验证是真正的 Codex 执行而非内置 agent"""
    # 扫描目录下所有 .json 文件
    for f in dir_path.glob("*.json"):
        data = json.load(f)
        assert "SESSION_ID" in data           # codex_bridge 特有字段
        assert UUID(data["SESSION_ID"])        # 合法 UUID
        assert data.get("success") is True    # 执行成功
        assert len(data.get("agent_messages", "")) > min_content_length  # 有实质内容
    # 内置 agent 不产生此格式，无法伪造
```

#### 流程 A：问题解决（solve）

启动：`ralph flow start solve --workspace /path --test-cmd "pytest" --tracker todo/issues.md --guide-output docs/capability-guide.md`

| # | 阶段 | Ralph 自动检查 |
|---|------|---------------|
| 1 | **理解问题** | 放行（思考无可检产出物），显示下一步指令 |
| 2 | **生成计划** | `plan.yaml` 存在 + `ralph validate plan.yaml --project-root {workspace}` 输出 0 error |
| 3 | **Codex 审查** | `.ralph-flow/step-3-review/` 下 ≥1 个合法 Codex 输出（SESSION_ID UUID + agent_messages > 200 字符）|
| 4 | **缺陷记录** | `--tracker` 文件 `git diff` 有新增行（确保不跳过记录步骤）|
| 5 | **Codex 执行** | `.ralph-flow/step-5-execute/` 下 Codex 输出数量 ≥ `ralph suggest` 当前 batch 的 task 数；每个输出合法（SESSION_ID + agent_messages 非空）|
| 6 | **全量验证** | 执行 `--test-cmd`，exit code = 0 |
| 7 | **能力指南** | `--guide-output` 文件存在 + 修改时间 > flow 启动时间 + 文件大小 > 1KB |

#### 流程 B：实战测试（e2e）

启动：`ralph flow start e2e --workspace /tmp/cccc-e2e-vN --group GROUP_ID --cccc-root /path/to/cccc --version vN`

| # | 阶段 | Ralph 自动检查 |
|---|------|---------------|
| 0 | **代码验证** | 执行 pytest，检查输出含 "0 failed"；ralph validate smoke 0 error |
| 1 | **环境准备** | `$workspace` 存在 + `docs/` 下 4 个指定文件存在 + `cccc daemon status` 返回 running + `cccc actor list --group $group` 有 planner 且 runtime_state=running |
| 2 | **任务下发** | `cccc tail --group $group` 中有 `chat.message` 事件 to planner，时间戳 > flow 启动时间 |
| 3 | **监控等待** | `cccc workflow status --group $group` 显示 tasks.completed = tasks.total 且 tasks.failed = 0 |
| 4 | **Codex 审查** | `.ralph-flow/step-4-review/` 下 ≥2 个合法 Codex 输出（结果审查 + 过程审查），每个 agent_messages > 500 字符 + `$workspace/WORKFLOW_EVALUATION.md` 存在且 > 500 字节 |
| 5 | **报告合成** | `$cccc_root/todo/e2e-实战评估报告-$version.md` 存在 + 文件内容包含"评分摘要"和"交叉验证"字符串 |
| 6 | **改进登记** | `git diff` 显示问题清单短版（问题清单-v5-ralph.md）和 full 版（问题清单-v5-ralph-full.md）都有变更 + 版本历史评分表（e2e-实战评估规范.md）有新增行 |

#### CLI 交互示例

```bash
$ ralph flow start solve --workspace ./my-project --test-cmd "pytest"
✅ 流程已创建：.ralph-flow/state.json
📂 Codex 输出约定目录：.ralph-flow/step-{N}-{name}/

── Step 1/7: 理解问题 ──────────────────────
阅读代码和相关文档，定位问题根因和待修改的文件。
准备好后运行：ralph flow next

$ ralph flow next
✅ Step 1 通过（无检查项）
── Step 2/7: 生成计划 ──────────────────────
生成 plan.yaml，包含任务分解、依赖、验证命令。
检查项：plan.yaml 存在 + ralph validate 0 error
准备好后运行：ralph flow next

$ ralph flow next
🔍 检查中...
  ✅ plan.yaml 存在
  ✅ ralph validate: 0 errors, 3 warnings
✅ Step 2 通过
── Step 3/7: Codex 审查 ──────────────────────
用 codex_bridge.py 审查计划的合理性。
⚠️  输出必须保存到：.ralph-flow/step-3-review/
示例：python codex_bridge.py --cd . --PROMPT "审查" > .ralph-flow/step-3-review/review.json
检查项：目录下有合法 Codex 输出（SESSION_ID + agent_messages > 200字符）
准备好后运行：ralph flow next

# 如果用了内置 agent 而非 Codex：
$ ralph flow next
🔍 检查中...
  ❌ .ralph-flow/step-3-review/ 下无合法 Codex 输出
     找到 0 个文件匹配 codex_bridge JSON 格式（需含 SESSION_ID + agent_messages）
     提示：请使用 codex_bridge.py，不要使用内置 agent
── Step 3/7: Codex 审查（重新显示）──────────
...
```

#### 后续泛化

solve 流程可直接用于任意项目问题解决，启动参数变化：
- `--workspace`：不同项目目录
- `--test-cmd`：不同测试命令（pytest/npm test/go test）
- `--tracker`：不同问题追踪文件（可选）
- `--guide-output`：不同能力指南路径（可选，CCCC 专用步骤）

不传 `--tracker` 和 `--guide-output` 时对应步骤跳过，solve 流程退化为 5 步（理解→计划→审查→执行→验证）。

**验收标准**：
- `ralph flow start solve --workspace /path` 成功创建 `.ralph-flow/` 目录和 `state.json`
- 每步 `ralph flow next` 自动检查对应产出物，无需操作者提交内容
- Codex 步骤拒绝非 codex_bridge JSON 输出（无 SESSION_ID 或 agent_messages 为空）
- 失败时重新显示当前步骤指令和缺失项
- 完整走完一轮修复流程无步骤遗漏
- solve 流程可在非 CCCC 项目中使用（`--tracker`/`--guide-output` 可选）

---

### UX-5 ralph guide 自动生成能力指南（P2）

**优先级**：P2
**影响维度**：体验 + 可维护性
**预期分数变化**：体验 +0.5（长期）

**触发实例**：
> 每次修复后需要重新扫描代码库更新 foreman-capability-guide.md，耗时长且仍会遗漏。v31 新增 BP-2/4/5 三个能力但指南完全未更新，导致 v32 Foreman 不知道 batch_e2e_command 存在。

**根因**：能力指南是手工文档，与代码不同步。

**改进方案**：新增 `ralph guide` 子命令，从 Pydantic schema (Plan/TaskSpec/Verification/ModuleSpec) + validation rules (warning/error codes 枚举) + CLI --help 自动生成结构化能力指南。代码改了→guide 自动同步。

**验收标准**：
- `ralph guide` 输出包含所有 Plan schema 字段、所有验证规则代码、所有 CLI 命令
- 输出与当前代码完全一致（无遗漏）

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

## 五、后续方向

### Modal 集成（待调研）

将 Modal (modal.com) 云计算平台集成到 CCCC 系统中，潜在改进方向包括但不限于：Worker 执行环境隔离、并行 E2E 测试、验证步骤云端执行、Codex bridge 替代等。具体集成方案和优先级待后续讨论确定。

---

## 六、版本历史评分追踪

| 版本 | 日期 | 结果 | 过程 | 体验 | 综合 | 关键变化 |
|------|------|------|------|------|------|----------|
| v1 | 04-01 | 2 | 1 | 2.5 | 1.8 | 基线 |
| v15 | 05-01 | 3 | 5 | 4 | 4.0 | 历史最高（至 v27） |
| v20 | 05-03 | 3 | 5 | 3 | 3.7 | 过程首次满分 |
| v27 | 05-13 | 2 | 4 | 4 | 3.3 | Gemini 排除成功 |
| v28 | 05-13 | 3 | 5 | 4.5 | 4.2 | 前历史最高 |
| v29 | 05-13 | 2 | 4 | 4 | 3.3 | v30 新能力全部验证(BP-1拦截+BP-3渲染+RO-76报错); codex 0%可靠(5/5 stall); 8任务暴露跨任务CRITICAL; RO-77/78/79新发现 |
| **v32** | **05-14** | **4** | **5** | **4** | **4.3** | **新历史最高**; RO-77/78确认修复; 0 CRITICAL; 过程满分; 100%自动化+零retry; 瓶颈转向plan编写体验; UX-1/2/3新发现 |
