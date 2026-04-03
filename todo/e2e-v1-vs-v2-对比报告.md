# CCCC 工作流实战对比报告：v1 vs v2

> 日期：2026-04-02
> v1：无文档指引，Foreman 零预期运行
> v2：提供能力指南 + 工作流文档 + 已知限制说明
> 审查方法：三维度独立审查（结果 × 过程 × 体验）

---

## 一、结果指标 — 项目代码质量

> 来源：Codex 对抗式代码审查

### v1 vs v2 对比

| 维度 | v1 | v2 | 变化 |
|------|-----|-----|------|
| 后端文件数 | 8 | 9（+`__init__.py`） | 略增 |
| 前端组件数 | 4（Board/Column/TaskCard/Header） | 3（Board/KanbanColumn/TaskCard） | 略减 |
| **测试** | **0** | **15 个 pytest（3 文件 + conftest）** | **显著提升** |
| plan.yaml | 无 | 有（6 任务、精确路径、checks、契约） | **新增** |
| 分批 JSON | 无 | batch1-4.json | **新增** |

### CRITICAL 问题对比

| v1 | v2 |
|----|-----|
| 外键约束未启用，可创建指向不存在 board/column 的数据 | **同类问题换了形态**：删除任务后不重排 position，导致拖拽排序在删除后失效 |
| 1 个 CRITICAL | 2 个 CRITICAL（position 空洞 + move 不校验边界） |

### WARN 问题对比

| 类别 | v1 | v2 |
|------|-----|-----|
| API 契约（body vs path param 不一致） | ✓ | ✓（未修复，同类问题） |
| 拖拽非原子 | ✓ | 形态变化（position 不重排） |
| 输入约束缺失 | ✓ | ✓（未修复） |
| CORS 脆弱 | ✓ | ✓（v2 更窄，只允许 5173） |
| run.sh 可靠性 | ✓ | 未审查到同类问题 |
| 测试覆盖盲区 | N/A（无测试） | ✓（move 复杂场景未覆盖） |
| plan 与实现不一致 | N/A | ✓ 新问题（target_column_id vs column_id） |

### 结果指标结论

**v2 在测试覆盖和计划规范性上显著进步，但核心业务逻辑质量未见本质提升。** 两版都有影响主流程的 CRITICAL 问题，说明 verify gate 没有真正拦住质量问题——无论是 v1 的"无 verification"还是 v2 的"verification skipped"，结果等价。

---

## 二、过程指标 — 工作流机制遵守情况

> 来源：Codex 工作流日志分析

### 逐项对比

| 检查项 | v1 | v2 | 判定 |
|--------|-----|-----|------|
| **ralph validate** | 未执行 | Foreman 声称执行（0 error），但日志无硬证据 | 未证实改善 |
| **分批提交** | 1 次提交 5 个任务 | 4 批提交（T1+T2 → T3 → T4+T5 → T6） | **改善** |
| **claimed_paths** | 全部 `"/"` | plan.yaml 精确（`backend/`、`frontend/src/`） | **计划层改善** |
| **claimed_paths 运行时** | `"/"` | engine 注册时变成空数组 `[]` | **未传递到引擎** |
| **verification.checks** | 不存在 | plan.yaml 有 checks（compile+test） | **计划层改善** |
| **verification 运行时** | skipped | skipped（`no command configured`） | **未传递到引擎** |
| **depends_on 执行** | 引擎未强制 | 引擎未强制，Foreman 手工维持 | 无变化 |
| **任务分配准确性** | 2/5 错配 | 初始正确，但 Codex 卡住后大量漂移 | 略差 |
| **Codex 可靠性** | 慢但完成（500s/1 任务） | 卡死未完成（0/1），Foreman 代做 | **退步** |
| **自动化比例** | ~20% | ~17%（1/6 自动闭环） | 无改善 |

### 核心发现：计划层 vs 执行层断裂

v2 最重要的发现是 **plan.yaml 的结构化元数据没有进入 workflow engine 的运行时**：

```
plan.yaml                    →  workflow engine 注册
claimed_paths: ["backend/"]  →  claimed_paths: []
verification.checks: [...]   →  verification: skipped
depends_on: ["T1"]           →  全部同时 running
```

这意味着 Foreman 在计划阶段做的所有改进（精确路径、多步验证、契约声明）在执行阶段全部失效。**问题不在 Foreman，在引擎**。

### 过程指标结论

**v2 的计划质量显著优于 v1，但执行闭环质量没有实质改善。** 根因是 workflow engine 的 `cccc workflow submit` 没有从 plan.yaml 传递 claimed_paths、verification.checks 等关键元数据，导致计划层的改进在执行层全部丢失。

---

## 三、体验指标 — Foreman 实践反馈

> 来源：Foreman 自生成的 WORKFLOW_EVALUATION.md

### v1 Foreman 反馈摘要

| 问题 | 严重度 | 描述 |
|------|--------|------|
| depends_on 未强制执行 | Critical | 全部任务立即 running |
| assign_to 被忽略 | Major | 任务被随机分配 |
| 无自动任务下发 | Major | Foreman 手工中继每个任务 |
| Verify gate 空操作 | Minor | 自动通过，无实际检查 |
| duration_seconds 全零 | Minor | 无性能数据 |
| **自评分** | **2.5/5** | 状态追踪可用，执行自动化缺失 |

### v2 Foreman 反馈摘要

| 问题 | 严重度 | 描述 |
|------|--------|------|
| 批次门控过严 | 新发现 | T3 依赖已满足但被 batch 边界阻塞 |
| Codex 静默卡死 | 新发现 | 无超时/无错误/无进度，只能人工判断 |
| deferred 任务无法正式完成 | 新发现 | 绕过引擎完成的任务状态不一致 |
| 自动下发仍缺失 | 已知 | 确认为核心限制 |
| **新评价** | — | "Ralph validate 是最有价值的部分" |
| **新评价** | — | "Claude worker 100% 可靠，Codex 0% 可靠" |

### 体验指标结论

**Foreman 的体验从"完全不知道怎么用"进步到"知道怎么用但工具没跟上"。** v1 的 Foreman 连 ralph validate 都没用；v2 的 Foreman 会写合格的 plan.yaml、分批提交、声明 checks——但引擎没有兑现这些声明。Foreman 最正面的反馈给了 Ralph validate（"caught a real issue before execution"），最负面的反馈给了 batch 门控（"rigid, should be dependency-aware"）。

---

## 四、综合评分

| 维度 | v1 | v2 | 变化方向 |
|------|-----|-----|----------|
| **结果：产出物质量** | 2/5（能跑但有 CRITICAL bug，无测试） | 3/5（有测试，仍有 CRITICAL bug） | ↑ |
| **过程：机制遵守度** | 1/5（无 validate、无分批、无 verify） | 2/5（有 validate 意图、分批、但执行层断裂） | ↑ |
| **体验：Foreman 满意度** | 2.5/5（"记账可用，执行缺失"） | 3/5（"Ralph 有价值，引擎跟不上"） | ↑ |
| **综合** | **1.8/5** | **2.7/5** | **+0.9** |

---

## 五、根因定位

### 已解决（v1→v2）

1. ✅ Foreman 缺乏工作流知识 → 通过文档+能力指南解决
2. ✅ 计划质量差（无 claimed_paths / checks / 契约） → 通过指南引导解决
3. ✅ 无测试 → v2 产出 15 个 pytest

### 未解决（需要代码修复）

1. ❌ **plan→engine 元数据丢失**：`cccc workflow submit` 不传递 claimed_paths、verification.checks、depends_on 到 engine 运行时。这是所有"计划层改善但执行层无效"的根因。
2. ❌ **引擎不自动下发任务**：batch_approved 后 engine 不往 worker inbox 发任何消息
3. ❌ **batch 门控过严**：按 batch 边界阻塞而非按 depends_on DAG 阻塞
4. ❌ **Codex 静默卡死无检测**：无超时、无 heartbeat、stall detection 未触发
5. ❌ **verification_passed 语义不准**：skipped 但事件名叫 passed

### 新发现（v2 独有）

1. 🆕 **plan.yaml 和实现不一致**：plan 写 `target_column_id`，实现用 `column_id`。Ralph validate 无法检测这类语义不匹配（结构上是合法的）
2. 🆕 **deferred 任务完成路径缺失**：绕过引擎做完的任务无法正式关闭
3. 🆕 **context.sync 编号污染**：不同批次的任务被写成 T001/T002 相同编号

---

## 六、下一步优先级

| 优先级 | 改进 | 预期影响 |
|--------|------|----------|
| **P0** | 修复 plan→engine 元数据传递（claimed_paths, checks, depends_on） | 让计划层改进在执行层生效 |
| **P0** | 引擎自动下发任务给 worker | 自动化从 ~17% → ~60% |
| **P0** | 改 batch 门控为 DAG 门控 | 消除 deferred 卡死 |
| **P1** | Codex worker 超时/heartbeat 检测 | 消除静默卡死 |
| **P1** | verification_passed 事件修正（skipped ≠ passed） | 语义准确 |
| **P2** | 更新 Foreman prompt 内置工作流引导 | 不依赖外部文档 |
| **P2** | duration_seconds 修复 | 性能数据 |
