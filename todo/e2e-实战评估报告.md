# CCCC 工作流实战评估报告

> 日期：2026-04-02
> 项目：任务管理看板（FastAPI + React）
> Workflow ID: kanban-v1
> 总耗时：~20 分钟（含 worker 启动）
> 任务：5/5 completed, 0 failed
> 信息来源：Foreman 评价报告 + Codex 代码审查 + Codex 日志分析

---

## 一、实验设置

| 项 | 值 |
|----|-----|
| Foreman | Claude Code (planner actor, role=foreman) |
| Worker 1 | Claude Code (backend-worker, role=peer) |
| Worker 2 | Codex CLI (frontend-worker, role=peer) |
| 项目目录 | /tmp/cccc-e2e-test |
| 5 个任务 | backend-setup, backend-api, frontend-setup, frontend-components, integration |

### 实验偏差说明

发送给 Foreman 的参考文档路径 `docs/ralph-foreman-workflow.md` 是旧版（3/25），且 Foreman 的 scope 是 `/tmp/cccc-e2e-test`（空目录），**两个版本的文档它都读不到**。Foreman 仅依赖内置 prompt 中的工作流引导。这意味着：

1. Foreman 不知道 `ralph validate` 的具体用法和规则集
2. Foreman 不知道 verify gate 需要 `verification_command` 才能真正运行
3. 我们刚实现的 E-1（multi-check）、E-2（model scoring）、E-3（context rollover）未被触发

---

## 二、工作流机制评估

### 正常工作的机制

| 机制 | 证据 |
|------|------|
| `cccc workflow submit` 批次注册 | 5 个任务 + 1 个 batch 成功注册并批准 |
| 完成记账 + Foreman 通知 | 每个 `task_reported_completed` 后自动发 `@foreman` 通知 |
| batch 完成检测 | 5/5 完成后正确发出 `batch_completed` 事件 |
| Worker 用 `cccc task complete` 报告 | 5 个任务均有正式 `workflow.task_reported_completed` 事件 |
| 多 runtime 支持 | Claude Code + Codex CLI 在同一 workflow 中协作 |
| Context Rollover（E-3） | `.cccc/task_contexts/` 下生成了 5 个 context 文件 |

### 部分工作的机制

| 机制 | 问题 | 证据 |
|------|------|------|
| `depends_on` 排序 | 元数据被记录但未被引擎强制执行，Foreman 手工维持顺序 | batch approval 一次性分配全部 5 个任务 |
| 任务分配 | 3/5 合理，2/5 明显错配（backend-api → frontend-worker） | batch approval 事件 `97d3dfeca784` |

### 未工作的机制

| 机制 | 问题 | 影响 |
|------|------|------|
| **自动任务下发** | Worker 不会自动收到任务说明，Foreman 用 `cccc send` 手工转发 | **80% 的编排工作变成手工** |
| **Ralph validate** | Foreman 提交前未执行 `ralph validate` | 计划质量未经结构性检查 |
| **Verify gate** | 所有任务 `overall_outcome: skipped, checks: []` | 验证门是空操作，无质量保障 |
| **E-1 多步验证** | 任务未配置 `verification.checks[]` | 刚实现的能力完全未触发 |
| **E-2 模型评分** | 引擎未使用 strengths/weaknesses 评分来选择 worker | 任务被随机/轮询分配 |
| **duration_seconds** | 全部报 0 | 无法做性能分析 |
| **Worker heartbeat** | 全部 `last_heartbeat: null, progress_pct: null` | 无法检测卡死 |
| **runtime_state** | 活跃 worker 显示 "stopped" 同时 running=true | 状态矛盾 |

### 未测试的路径

- 失败重试（0 个任务失败，retry 路径未覆盖）
- Ralph validate 拦截低质量计划
- Verify gate 拦截低质量实现
- Worker 卡死恢复（stall detection）
- Context Rollover 注入（无 retry 则无注入）

---

## 三、产出物代码质量（Codex 审查）

### CRITICAL（1 个）

- **外键约束未启用**：SQLite 未开启 `PRAGMA foreign_keys=ON`，可以创建指向不存在的 board/column 的数据，move 操作可跨 board 移动任务。涉及 `database.py:6`, `routers/columns.py:21`, `routers/tasks.py:27,61`

### WARN（7 个）

| # | 问题 | 文件 |
|---|------|------|
| 1 | API 契约误导：schema 要求 `board_id`/`column_id` 但 handler 只用 path param，body 字段被忽略 | `schemas.py`, `routers/` |
| 2 | 拖拽持久化非原子：move + 多个 position update 无事务边界，部分失败留脏数据 | `Board.tsx:95-108`, `models.py:37-38` |
| 3 | 写接口缺输入约束：空标题、负 position、超长字符串可入库 | `schemas.py` |
| 4 | 前端创建任务无 try/catch，4xx/5xx 导致 unhandled rejection | `Board.tsx:169`, `Column.tsx:24` |
| 5 | CORS + 端口配置脆弱：Vite 端口被占时自动换端口，CORS 白名单不含新端口 | `main.py:50`, `client.ts:4`, `run.sh:23` |
| 6 | 后端导入依赖 cwd：`from database import ...` 只在 `cd backend` 后能用 | `main.py:7`, `models.py:6` |
| 7 | run.sh 半启动：一个服务崩掉另一个继续运行，无清晰失败信号 | `run.sh:17-28` |

### OK

- SQL 注入：全部走 SQLAlchemy ORM，无拼接 SQL ✅
- TypeScript 编译：`tsc --noEmit` 通过 ✅
- 路由注册：3 个 router 正确挂载 ✅
- 前端组件挂载链路正常 ✅

---

## 四、自动化比例分析

基于日志事件计数：

| 类别 | 自动 | 手工 |
|------|------|------|
| 批次登记 + 批准 | ✅ | |
| 任务下发给 Worker | | ❌ Foreman 手工 `cccc send` ×5 |
| 依赖顺序控制 | | ❌ Foreman 手工排序 |
| 完成记账 + 通知 | ✅ | |
| Verify gate | ✅（但 skipped） | |
| 错配纠偏 | | ❌ Foreman 手工重发 |

**估算：~20% 自动 / ~80% 手工**（与 Foreman 自评一致）

---

## 五、任务耗时（墙钟估算）

| 任务 | Worker | Runtime | 耗时 |
|------|--------|---------|------|
| backend-setup | backend-worker | Claude | ~42s |
| backend-api | backend-worker | Claude | ~90s |
| frontend-setup | backend-worker | Claude | ~166s |
| frontend-components | frontend-worker | Codex | ~500s |
| integration | backend-worker | Claude | ~35s |

**Codex 显著慢于 Claude**（~500s vs ~40-90s），但仅基于单次观测。

---

## 六、根因分析

### 为什么 80% 是手工的？

核心问题是 **workflow engine 只管状态记账，不管任务投递**。`workflow.batch_approved` 事件后，引擎把所有任务标记为 "running"，但不往 worker inbox 发任何消息。Foreman 不得不充当消息中继。

```
期望：batch_approved → engine 自动发 task spec 给 worker → worker 执行 → task complete
实际：batch_approved → 什么都没发生 → Foreman 手工 cccc send → worker 执行 → task complete
```

### 为什么 verify gate 是空操作？

两个原因叠加：
1. Foreman 提交的任务 JSON 没有 `verification_command` 字段（因为不知道需要）
2. 我们刚实现的 `verification.checks[]`（E-1）需要在计划中显式配置，Foreman 不知道这个新能力

### 为什么 depends_on 没生效？

`workflow submit` 把所有任务一次性提交为一个 batch。batch 内部的 `depends_on` 信息被记录但未被 batch approval 阶段的调度器使用。调度器只做 write-set 冲突检测（全是 `claimed_paths: ["/"]` 所以也没冲突），不做 DAG 拓扑排序。

### 为什么新能力（E-1/E-2/E-3）未被触发？

E-1（multi-check）和 E-3（context rollover）需要任务定义中显式配置。Foreman 不知道这些新字段的存在，因为：
- 工作流文档未更新
- Foreman 内置 prompt 未提及 `checks[]` 和 context rollover
- 即使文档可用，Foreman 也读不到（scope 不对）

E-2（model scoring）需要 agent pool 有 model registry 配置。虽然 `.cccc/models/registry.yaml` 存在，但调度器在分配时未使用增强评分逻辑。

---

## 七、评分

| 维度 | 分数 | 说明 |
|------|------|------|
| 任务提交 UX | 4/5 | JSON + 单命令，清晰 |
| 状态记账 | 4/5 | 事件流完整，可追溯 |
| 通知/可观测性 | 4/5 | 完成通知及时准确 |
| 多 runtime 支持 | 4/5 | Claude + Codex 共存 |
| 依赖排序 | 1/5 | 未强制执行 |
| 任务自动下发 | 1/5 | 不存在，Foreman 手工中继 |
| Worker 分配 | 2/5 | assign_to 被忽略 |
| 验证质量 | 1/5 | 空操作 |
| 时长/进度追踪 | 1/5 | 全零 |
| **综合成熟度** | **2.5/5** | **记账层可用，执行自动化缺失** |

---

## 八、改进优先级

| 优先级 | 改进 | 预期收益 |
|--------|------|----------|
| **P0** | 任务自动下发：batch_approved 后 engine 自动发 task spec 给 worker | 自动化从 20% → 70% |
| **P0** | depends_on 强制执行：batch 内按 DAG 拓扑排序，仅 ready 任务分配 | 消除 Foreman 手工排序 |
| **P1** | Foreman prompt 注入新能力：教 Foreman 使用 `checks[]`、`claimed_paths`（非 "/"） | 触发 verify gate + 并行调度 |
| **P1** | assign_to 尊重或文档化为 hint | 消除错配 |
| **P1** | 文档同步：更新 `todo/ralph-foreman-workflow.md` 反映 E-1/E-2/E-3/M-2 | Foreman 能利用新能力 |
| **P2** | duration_seconds 修复 | 性能分析 |
| **P2** | Worker heartbeat | 卡死检测 |
| **P2** | runtime_state 与 running 统一 | 消除状态矛盾 |

---

## 九、结论

CCCC 工作流系统的**记账层**（事件流、状态追踪、通知）已经可用且可靠。但**执行自动化层**（任务下发、依赖编排、验证门控）存在显著缺口，导致 Foreman 不得不充当手工消息中继，整体自动化率仅 ~20%。

我们刚完成的能力扩展（E-1 多步验证、E-2 模型评分、E-3 上下文延续、M-2 CLI 命令）在代码层面已实现并通过测试，但在实战中**完全未被触发**。根因是 Foreman 的 prompt 和文档没有告诉它这些新能力的存在，且任务提交格式缺少必要字段。

**下一步：修复 P0 项（自动下发 + depends_on 强制），然后更新 Foreman prompt 和文档，再做一轮实战验证。**
