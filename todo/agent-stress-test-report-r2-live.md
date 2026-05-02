# Ralph Agent 改进后压力测试报告 — R2 Live

> 日期：2026-05-03
> 测试 plan：tests/ralph/stress_plan_agent_r2.yaml (8 tasks)
> Gemini CLI：v0.40.0, model=flash, timeout=60s

## 结果矩阵

| Task | 场景 | 期望 | 实际 | 判定 |
|------|------|------|------|------|
| T-pass-1 | 验证 suggest() 已正确实现 | passed | **error(timeout)** | ⚠️ 超时 |
| T-pass-2 | 验证 _run_check 超时处理已存在 | passed | **failed** | ❌ 假阳性 |
| T-subtle-1 | _OUTPUT_TRUNCATE 应为4000但实际是2000 | failed | **failed** ✓ | ✅ 正确 |
| T-wrong-file | explain 在 cli.py 不在 core.py | failed | **failed** ✓ | ✅ 正确 |
| T-contradict | goal 和 acceptance 矛盾 | failed | **failed** ✓ | ✅ 正确 |
| T-test-fail | 代码正确但测试命令写错 | failed | **failed** ✓ | ✅ 正确 |
| T-large-file | 安全审计大文件（截断） | passed | **failed** | ⚠️ 边界问题 |
| T-cross-file | 跨文件常量一致性 | passed | **error(timeout)** | ⚠️ 超时 |

**正确率：4/8 (50%)**

## 问题分析

### P1: 超时问题 (T-pass-1, T-cross-file)

当 source_context 包含大文件时，prompt 超过 Gemini 60s 处理能力：
- core.py ≈ 8KB（截断上限），agent.py ≈ 8KB
- 两个文件一起注入 ≈ 16KB source + prompt + schema
- **建议**：将 GEMINI_TIMEOUT_SECONDS 提高到 120s，或缩小 _SOURCE_FILE_MAX_BYTES

### P2: "验证已有功能"假阳性 (T-pass-2)

Agent 过度依赖 git diff 为空 → 判定"没有实施"的逻辑：
- Rule 3 说"如果 git diff 为空，任务可能没有做它声称的更改"
- 但对于**审查/验证类**任务（非修改代码），diff 本来就应该为空
- **根因**：prompt 没有区分"实施任务"和"验证任务"
- **建议**：当 goal_behavior 包含"verify"/"ensure"/"check"/"audit"等词时，放宽 diff 为空的判定

### P3: 文件截断导致不完整分析 (T-large-file)

validator.py 超过 8KB 被截断，agent 正确识别了这一点并拒绝给出确定性结论：
- "truncated at 8000 bytes ... cannot be verified for the entire file"
- 这其实是**正确行为**（不编造结论），但导致审计类任务无法通过
- **建议**：对审计类任务提高单文件上限，或引入按 function 提取的策略

### P4: Plan 模型截断导致误报 (T-test-fail)

Agent 报告"Plan class is not present in the provided source code"：
- models.py 很大，Plan 类定义在文件后部，被 8KB 截断切掉了
- Agent 正确地不编造（好），但得出了错误结论"Plan 不存在"（不好）
- **建议**：source_context 应包含 AST 级摘要（类名/函数签名列表）而非裁切

## 积极发现

### 真正的 bug 全部被正确检测

- **T-subtle-1**：agent 不仅看到了 git diff 为空，还看到了 verification output 中 `AssertionError: _OUTPUT_TRUNCATE is not set to 4000`——综合两个证据判定 failed
- **T-wrong-file**：agent 分析了 core.py 源码，确认里面没有 explain 相关逻辑
- **T-contradict**：agent 主动识别出"goal behavior and acceptance criteria were contradictory"——这是纯推理能力，非常好
- **T-test-fail**：agent 同时使用了三个信号源（diff + source + verification_output.status=failed）

### 对比改进前

- 改进前：agent 会对不存在的函数声称"验证通过"（T3 幻觉）
- 改进后：agent 对截断的文件说"cannot be verified for the entire file"——**诚实地承认不确定**而非编造

## 下一步

1. **P1**：提高 GEMINI_TIMEOUT_SECONDS 到 120s 解决超时
2. **P1**：prompt 添加任务类型区分（implement vs verify/audit），放宽 audit 类任务的 diff 判定
3. **P2**：source_context 改为 AST 摘要 + 关键函数体，而非简单截断
