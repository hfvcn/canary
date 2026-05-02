# Ralph Agent 压力测试报告 — 第一轮

> 日期：2026-05-03
> 测试文件：tests/ralph/test_agent_stress.py
> 测试结果：30/30 passed (0.14s)
> 目标：验证问题清单中标记"🤖 Agent 可覆盖"的 10 项已知局限是否真的能被 agent 解决

## 核心发现

**Agent 的根本限制**：prompt 明确禁止代码访问（`"Do not use tools, shell commands, file reads, MCP, or workspace inspection."`），agent 只接收 plan JSON payload，不读源码、不执行命令、不解析 AST、不访问 import graph。

## 判定矩阵

| 编号 | 声称 | 判定 | 原因 |
|------|------|------|------|
| RL-1 | 检测计划描述已完成功能为 TODO | **不可覆盖** | 无代码访问，无法比较 plan intent vs 实际代码状态 |
| RL-2 | 检测 goal_behavior 中错误的函数名 | **不可覆盖** | 无符号表/AST/文件读取，无法解析引用 |
| RL-4 | 检测同一 bug 的多个症状 | **部分覆盖** | beyond-scope 批量审查可传多个 issue，Gemini 可能识别模式；但 task verification 严格按单任务 |
| RV-15 | 检测 Ralph 自身规则 bug | **部分覆盖** | 能标记可疑的 validate 输出，但无法检查规则实现。manual fallback 匹配一切 |
| RV-18 | 检查 goal_behavior 中函数名是否存在 | **不可覆盖** | 无代码访问，同 RL-2 |
| RV-19 | 检测模型扩展破坏语义 | **不可覆盖** | 无 import graph 或消费者链分析 |
| RV-20 | 验证 monitor wiring 运行时可达性 | **不可覆盖** | 无运行时 trace 或执行路径分析 |
| RO-10n | 检测运行时语义 bug | **部分覆盖** | 能通过对抗推理建议边缘场景，但无法执行。建议是 advisory，无 ground truth |
| RO-11n | 检测删除函数的副作用链 | **不可覆盖** | 无 import graph，无法追踪已删函数的调用者 |
| RO-12n | 检测同文件多入口部分覆盖 | **不可覆盖** | 无 AST 分析，无法枚举文件入口点 |

## 统计

- **不可覆盖**：7/10 (70%)
- **部分覆盖**：3/10 (30%)（且均为 advisory only，无判定权）
- **完全覆盖**：0/10 (0%)

## 额外发现

### F1: Checklist 优先级 bug
- `_match_checklist()` 按顺序遍历 checklist items，`code_prefix` 匹配优先于 `field_content`
- 当 issue code 以 `W_VERIFICATION` 开头时，RO-10n 总是赢过 RO-11n/RO-12n（因为 RO-10n 的 code_prefix=`W_VERIFICATION` 在列表中更靠前）
- 导致 RO-11n/RO-12n 的 `field_content` 匹配永远无法触发（对 W_VERIFICATION_* 系列 code）

### F2: Stub provider 退化
- Stub provider 对所有 beyond-scope issue 返回 `"Requires manual review: {description}"` + `confidence="low"`
- 实质上是把"🤖 Agent 可覆盖"降级为"需要人工审查"
- Gemini provider 理论上能提供更有价值的建议，但受限于无代码访问

### F3: Verification prompt 信息缺失
- verification prompt 不包含：源代码内容、测试输出、git diff、import graph、AST/符号表、其他任务上下文
- 仅包含：task spec 元数据（id, title, goal_behavior, acceptance_criteria, claimed_paths, verification_mode）+ changed_files 列表（仅文件名）

## 建议改进方向

1. **给 agent 注入代码上下文**：至少把 claimed_paths 的文件内容、git diff 传入 prompt
2. **给 agent 注入 verification 执行结果**：compile+test 的 stdout/stderr 是 RO-42 根因解法
3. **给 agent 工具访问能力**：允许 grep/AST 查询解决 RV-18/RL-2/RO-11n/RO-12n
4. **修复 checklist 优先级**：让 field_content 匹配在更具体时优先于 code_prefix
5. **更新清单中的"🤖 可覆盖"标记**：对 7 项标为"❌ 当前不可覆盖（需代码访问）"
