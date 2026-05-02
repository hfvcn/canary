# Ralph Agent 真实调用压力测试报告

> 日期：2026-05-03
> 测试方式：`ralph verify` 调用真实 Gemini CLI (v0.40.0, model=flash)
> 测试 plan：tests/ralph/stress_plan_agent.yaml
> 结果：5/5 task 全部 **failed**（agent 判定）

## 植入的问题 vs Agent 实际行为

### T1-already-done（RL-1：描述已完成功能为 TODO）

**植入问题**：goal_behavior 说"添加 field_validator"，但该功能在 models.py 中**可能已经存在**
**Agent 行为**：
- ❌ **完全没检测到"功能已存在"** — 无代码访问，不可能知道
- 代之编造了 3 个模拟场景（空字符串、省略字段、None 值）
- 1 pass / 2 fail → 判定 failed
- **实质**：Agent 在做无根据的对抗推理，生成的"bug"是虚构的

### T2-wrong-ref（RL-2：引用不存在的函数名）

**植入问题**：goal_behavior 说"修改 validate_input()"，但该函数**不存在**（实际叫 `validate_with_project()`）
**Agent 行为**：
- ❌ **完全没检测到函数名错误** — 接受了 plan 中的虚假引用
- 编造了 3 个场景（空列表、None、缺失属性）
- 1 pass / 2 fail → 判定 failed
- **实质**：Agent 假设 validate_input() 存在并推理其边缘行为，**信以为真**

### T3-phantom-func（RV-18：引用完全不存在的函数）

**植入问题**：goal_behavior 说"调用 delete_orphan_nodes()"，该函数在 core.py 中**完全不存在**
**Agent 行为**：
- ❌ **完全没检测到函数不存在** — 假设函数存在
- 编造了 3 个场景（正常路径、异常恢复、调用频率）
- 2 pass / 1 fail → 判定 failed
- 甚至说"delete_orphan_nodes() 在正常路径下被正确调用" — **纯幻觉**
- **实质**：Agent 对完全虚构的函数做了详细的"验证"，包括声称 2 个 check 通过

### T4-delete-side-effects（RO-11n：删除函数副作用链）

**植入问题**：要删除 `_run_check()`，但该函数被 `verify()` 调用，删除会导致系统崩溃
**Agent 行为**：
- ⚠️ **部分检测到问题** — 提到"residual calls within unexecuted function scopes"
- 但推理基于猜测而非代码分析
- 1 pass / 2 fail → 判定 failed
- **实质**：Agent 的对抗推理碰巧猜对了方向，但无法给出具体的调用者

### T5-partial-entry（RO-12n：只覆盖部分入口）

**植入问题**：只给 validate() 加 rate limiting，validator.py 中其他函数不受影响
**Agent 行为**：
- ❌ **没有检测到部分覆盖问题**
- 反而编造了 rate limiting 的具体实现问题（全局 vs per-client、滑动窗口）
- 2 pass / 2 fail → 判定 failed
- **实质**：Agent 在验证一个**尚未实现的功能**的设计质量，而非验证代码

## 关键发现

### 1. Agent 100% 假阳性率

5/5 task 全部 failed，但**没有一个是因为检测到了植入的真正问题**。所有 failure 都来自 agent 编造的边缘场景。

### 2. Agent 无法区分"存在"与"不存在"

- T3 中 `delete_orphan_nodes()` 完全不存在，agent 声称"正确调用了"（passed）
- T2 中 `validate_input()` 不存在，agent 假设它存在并推理其 null-safety
- Agent 无法验证 plan 中任何代码引用的真实性

### 3. Agent 的对抗推理本质是猜测

Agent 遵循"adversarial reviewer"指令，**总是能找到理由判 failed**：
- 对正确实现编造不存在的 bug
- 对不存在的功能假装已验证
- 对未执行的代码做"模拟分析"

### 4. "🤖 Agent 可覆盖"判定修正

| 编号 | 清单声称 | 真实 Gemini 测试结果 | 实际判定 |
|------|---------|---------------------|---------|
| RL-1 | Agent 可检测已完成功能 | 完全无法检测 | ❌ 不可覆盖 |
| RL-2 | Agent 可检测错误函数引用 | 完全无法检测，信以为真 | ❌ 不可覆盖 |
| RV-18 | Agent 可检测函数是否存在 | 对不存在的函数声称"验证通过" | ❌ 不可覆盖 + 制造幻觉 |
| RO-11n | Agent 可检测删除副作用 | 碰巧猜到方向但无具体证据 | ⚠️ 部分（靠运气） |
| RO-12n | Agent 可检测部分覆盖 | 完全没检测到，跑偏到实现细节 | ❌ 不可覆盖 |

### 5. 最严重的问题：T3 幻觉

Agent 对 `delete_orphan_nodes()` 的判定暴露了核心缺陷：
```
"Standard Success Path Cleanup" → passed
"The function delete_orphan_nodes() is correctly invoked at the end of 
a successful suggest() call, and orphans are removed as expected."
```
**这个函数根本不存在。** Agent 声称验证通过了一个虚构的调用。这不是"部分覆盖"——这是**主动制造虚假的安全感**。

## 结论

真实 Gemini agent 调用**确认并加强了** R1/R2 的理论分析：

- 10 项"🤖 Agent 可覆盖"声称中 **0 项得到真实验证**
- Agent 不仅无法覆盖，还**主动产生幻觉**（声称验证通过了不存在的代码）
- 对抗推理模式导致 **100% 假阳性率**：总是找到理由判 failed
- 改进方向不变：**必须给 agent 注入源代码 + 测试输出**，否则 agent 是有害的
