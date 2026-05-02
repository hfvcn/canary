# Ralph Agent 压力测试报告 — 第二轮（Codex 协作）

> 日期：2026-05-03
> 测试文件：tests/ralph/test_agent_stress_r2.py
> 测试结果：34/34 passed (0.14s)
> 两轮合计：64/64 passed (0.15s)
> 来源：Codex (SESSION_ID: 019de9a8-b00a-7c10-8a6e-f0aed6302c24) 审查 R1 后提出的 7 类测试场景

## 新发现（R2 独有）

### F4: Prompt Injection（严重度：HIGH）

Plan 字段（`goal_behavior`、`acceptance_criteria`、`issue.message`）被 `json.dumps` 序列化后直接拼入 Gemini prompt。

- JSON 序列化提供了"意外防御"：内部引号被转义为 `\"`
- 但**对抗文本本身完整保留**且 LLM 可读（`"IGNORE ALL PREVIOUS INSTRUCTIONS"` 原样出现）
- `claimed_paths` 中的 shell 元字符（`$(whoami)`、`` `id` ``）也被原样序列化
- Unicode bidi 覆写字符（`‮`、`‭`）可造成路径视觉欺骗

### F5: Session 跨调用污染（严重度：MEDIUM）

`warm_up()` 后所有后续调用使用 `--resume latest`，复用同一 Gemini 会话：
- warmup prompt 内容持久化在 session memory 中
- 第 N 次调用的恶意 plan 数据可能泄漏到第 N+1 次调用

### F6: Checklist 假阳性匹配（严重度：MEDIUM）

`field_content` 匹配使用简单子串搜索：
- 任何 issue message 中偶然包含 `"goal_behavior"` 的 issue 都会被错误归类到 RV-18
- 包含 `"monitor"` 的 issue 被错误归类到 RV-20
- 根因：没有区分 issue.message 中的关键字是"关于该主题"还是"碰巧提到该词"

### F7: Checklist 遮蔽效应（严重度：MEDIUM，R1 发现扩展）

`code_prefix` 匹配优先级高于 `field_content`：
- RO-10n（`W_VERIFICATION`）遮蔽了 RO-11n 和 RO-12n（对所有 `W_VERIFICATION_*` code）
- RO-11n 和 RO-12n 的 checklist 条目对 `W_VERIFICATION_*` issue 实质上是死代码

### F8: Prompt 无大小限制（严重度：LOW）

- `goal_behavior` 100KB+ 被原样序列化，无截断
- `changed_files` 1000+ 条目全部序列化
- `issue.task_ids=[]` 时整份 plan（所有 task）被展开到 prompt
- 风险：Gemini 上下文溢出导致响应质量下降

### F9: 幻觉接受（严重度：HIGH）

解析层无交叉验证：
- Gemini 可声称"在 src/app.py:42 行发现 XSS 漏洞"，解析器照单全收
- `passed=True` 与 2/3 checks `outcome=failed` 矛盾时，信任顶层 `passed`
- 空 check name 被静默替换为 `"agent_simulation"`
- Gemini 可对任何建议声称 `confidence: "high"`，无验证

### F10: 上下文缺口量化（严重度：CRITICAL）

当前 verification prompt 包含：
- 0 字节源代码
- 0 字节测试输出（stdout/stderr）
- 0 字节 git diff
- 0 字节 AST/符号表
- 0 字节 import graph

这使得 7/10 "🤖 Agent 可覆盖" 声称在**信息论层面不可能成立**。

## A/B 上下文注入分析

| 注入类型 | 可解锁的 issue | 不可解锁的 issue | 评估 |
|----------|---------------|-----------------|------|
| 源代码 | RL-2/RV-18（函数名校验） | RO-11n（需跨文件） | 单文件有效，跨文件不够 |
| Git diff | RL-1（空 diff = 已完成） | — | 高杠杆 |
| 测试输出 | RO-42/RO-10n（ground truth） | — | **最高杠杆**，直接解决 RO-42 |
| Import graph | RO-11n/RO-12n | — | 需要额外基础设施 |
| 运行时 trace | RV-20 | — | 最难实现 |

## 改进优先级（综合两轮）

1. **P0**：注入 verification 执行结果（stdout/stderr + exit_code）到 agent prompt → 解决 RO-42 + RO-10n
2. **P0**：注入 claimed_paths 文件内容到 agent prompt → 解决 RL-2/RV-18
3. **P1**：注入 git diff 到 agent prompt → 解决 RL-1
4. **P1**：修复 checklist 优先级逻辑（更具体的 field_content 应优先于泛化的 code_prefix）
5. **P2**：添加 prompt 大小限制/截断策略
6. **P2**：agent 输出交叉验证（passed 与 checks 一致性）
7. **P3**：prompt injection 防御（对用户输入字段做边界标记）
