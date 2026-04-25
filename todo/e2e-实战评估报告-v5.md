# CCCC 实战评估报告 v5

> 日期：2026-04-19
> Workflow ID: wf-notes-v1
> Group: g_6f3648c4dd49
> 总耗时：~13 分钟（04:33 ~ 04:46）
> 任务数：6（T1~T6, 3 批次）
> Worker：backend-worker (codex), frontend-worker (claude)

## 评分摘要

| 维度 | 分数 | 关键发现 |
|------|------|----------|
| 结果 | 2/5 | 1 CRITICAL（SQLite 写锁无错误处理→500）, 2 WARN（无 PRAGMA、无输入验证） |
| 过程 | 1/5 | Engine 使用旧 workflow 元数据，自动闭环 0/6，仅 1 批次注册 |
| 体验 | 4/5 | Foreman 自评 4.0，Worker 全部 6/6 完成，Ralph validate/verify 有正面反馈 |
| **综合** | **2.3/5** | |

---

## 一、结果指标（2/5）

### CRITICAL

- **[backend/database.py:9]** SQLite engine 无 WAL 模式、无 `busy_timeout`、无 PRAGMA 初始化。`backend/crud.py` 的所有写操作（:11, :32, :43）无 try/except、无 rollback。任何写锁竞争直接产生未处理的 500。复现：对 `notes.db` 持有 `BEGIN EXCLUSIVE` 锁时 `POST /notes` → 500 Internal Server Error。

### WARN

- **[backend/database.py:9]** `PRAGMA foreign_keys = 0`, `PRAGMA journal_mode = delete`。外键约束静默不生效（与 v1 E2E 发现的 FK 问题相同模式）。
- **[backend/schemas.py:6]** `title` 和 `content` 字段无非空/去空白/长度约束。`POST /notes {"title": "   ", "content": ""}` 返回 200 并持久化空白记录。

### OK

- XSS：前端无 `dangerouslySetInnerHTML`，React 文本节点渲染，无 XSS 路径
- SQL 注入：全部使用 SQLAlchemy ORM 参数化查询
- 孤儿记录：单表 schema，无 FK 关系，无孤儿风险
- 后端测试：6 passed, 0 failed (0.06s)
- 前端构建：vite build 成功，19 模块
- 前端测试：3 vitest tests passed

---

## 二、过程指标（1/5）

### 10 项必检结果

| # | 检查项 | 判定 | 证据 |
|---|--------|------|------|
| 1 | Foreman 是否执行 ralph validate | **有证据** | chat.message: "plan.yaml 已写好并通过 ralph validate（0 error, 11 warning）" |
| 2 | 是否按 ralph suggest 分批提交 | **无证据** | 仅 1 个 batch_registered（T1+T4），后续 T2/T5/T3/T6 未见批次注册 |
| 3 | claimed_paths 是否精确 | **有证据** | task_registered 中 claimed_paths 包含具体文件（非 "/"） |
| 4 | verification.checks 是否在 engine 执行 | **无证据** | 无 verification_passed 事件；仅 verification_failed（使用旧 plan 的 checks） |
| 5 | depends_on 是否被 engine 强制执行 | **无证据** | 依赖放行靠 Foreman 聊天协调，非 engine task_completed 事件驱动 |
| 6 | 任务是否分配给正确的 worker | **有证据** | batch_approved: backend-worker → T1, frontend-worker → T4，方向正确 |
| 7 | Worker 是否使用 cccc task complete | **无证据** | 6 个任务仅 T1 有 task_reported_completed，其余通过 cccc send 报告 |
| 8 | 有无卡死/失败/重试 | **有证据**（负面） | verification_failed(T1)，因 engine 使用旧 todo-cli 的 compile_check |
| 9 | 自动化比例 | **有证据**（负面） | 自动闭环 0/6，全靠 Foreman 手工 ralph verify + ralph complete |
| 10 | plan.yaml 元数据传递到 engine | **有证据**（负面） | task_registered 中 title="Core todo module" — 旧 workflow 元数据，非当前 plan |

**根因：** Group 复用了上一轮 todo-cli workflow 的 task ID (T1~T4)。新 workflow 提交时，engine 将 T1 映射到旧 workflow 的 task 定义。导致 verification 使用旧 checks、task_complete 报 workflow_id_mismatch。Foreman 被迫完全绕过 engine，用 ralph verify + ralph complete 手工闭环。

---

## 三、体验指标（4/5）

### Foreman 反馈摘要

**正面：**
- Ralph validate 早期拦截了 checks name 字段缺失
- Ralph suggest 正确识别并行批次（T1+T4, T2+T5, T3+T6）
- Ralph verify 真正发现了 T2 的 bug（TestClient + lifespan 不兼容）
- Worker 可靠性：backend 3/3, frontend 3/3

**负面：**
- Engine task ID 冲突 — 旧 workflow 的 T1~T4 定义仍在，新 workflow 无法正常 complete
- Engine verification 使用错误的 plan — 跑旧 todo-cli 的 compile_check
- Auto-process 不自动下发任务 — 每个任务仍需手工 cccc send

**手工干预：**
- 所有 6 个任务的下发（cccc send）
- 所有 6 个任务的验证（ralph verify）
- 所有 6 个任务的状态更新（ralph complete）

---

## 四、交叉验证

| 场景 | 分析 |
|------|------|
| 结果差(2) + 体验好(4) | Worker 产出代码基本可用但有并发 bug。Foreman 未发现 SQLite 写锁问题因为 ralph verify 的 checks 只做了 import + CRUD cycle（单线程）。**RO-17 的 W_VERIFICATION_SHALLOW_CHECKS 规则在此场景本应发出警告——但因为 Foreman 实际使用的 plan.yaml 的 checks 确实包含了 behavior test（crud_cycle），只是 test 本身覆盖不够深（无并发/错误路径测试）。这正是 RO-17 验收标准中描述的"acceptance_criteria → checks 交叉检查"增强方向。** |
| 过程差(1) + 体验好(4) | Foreman 用 workaround 完全绕过了 engine，感知上"工作流还行"，但日志显示 engine 闭环完全断裂。**Foreman 的正面体验来自 Ralph CLI 工具链（validate/suggest/verify/complete），不来自 workflow engine。** |

---

## 五、与上一版对比（v5 vs v4）

| 指标 | v4 | v5 | 变化 | 归因 |
|------|----|----|------|------|
| 结果 | 2/5 | 2/5 | = | 同类型 bug（SQLite 无错误处理），RO-17 规则已实现但 plan 的 checks 确实有 behavior test，只是深度不够 |
| 过程 | 4/5 | 1/5 | ↓↓ | **v4 用干净 group，v5 复用了旧 workflow group → task ID 冲突** |
| 体验 | 4/5 | 4/5 | = | Ralph CLI 工具链稳定，Worker 可靠性保持 |
| 综合 | 3.3/5 | 2.3/5 | ↓ | 过程维度因 group 复用问题大幅下降 |

**关键差异归因：** v5 过程分数下降的根因不是代码改进无效，而是 **测试环境问题** — 复用了带有旧 workflow 状态的 group。如果使用干净 group，过程分数预计与 v4 持平或更高（batch_approved + auto-dispatch 证据已出现）。

---

## 六、根因定位

### 已解决（本轮 Ralph 改进生效的）
- Ralph validate 正常工作，Foreman 遵守流程
- Ralph suggest DAG 批次正确
- Ralph verify 发现了真实 bug（T2 lifespan）
- Worker 自动下发部分生效（首批 T1+T4 的 batch_approved + auto-dispatch）

### 未解决
1. **Engine task ID 不按 workflow 隔离** — 旧 workflow 的 T1~T4 定义污染新 workflow
2. **Engine 不支持清除旧 workflow 状态** — 无 archive/clear 机制
3. **Engine verification 使用旧 plan** — 即使注册新 workflow，检查仍用旧定义
4. **自动下发仅首批有效** — 后续批次未见 batch_registered，Foreman 手工协调

### 新发现
- **FIX-6: Workflow scope isolation** — task ID 应按 workflow_id 命名空间隔离，防止跨 workflow 冲突
- **FIX-7: Stale workflow cleanup** — 提交新 workflow 时应归档/清除旧 workflow 的 task 映射

---

## 七、后续改进及对应实例

### [FIX-6] Workflow task ID 按 workflow_id 隔离

**优先级**：P0
**影响维度**：过程
**预期分数变化**：过程 1→3

**触发实例**：
> v5 E2E 中，旧 todo-cli workflow 的 T1~T4 定义仍在 engine 中。新 wf-notes-v1 提交 T1~T6 时，T1 映射到旧定义。`cccc task complete T1` 报 workflow_id_mismatch。verification 使用旧 plan 的 compile_check（检查 todo/ 模块）而非新 plan 的 import_check。

**根因**：Engine task ID 是全局唯一的，不按 workflow_id 隔离。

**改进方案**：Task ID 存储键改为 `{workflow_id}:{task_id}`，或在 task_complete 时要求显式指定 workflow_id 并验证一致性。

**验收标准**：同一 group 中两个 workflow 的 T1 不会冲突。

---

### [FIX-7] 提交新 workflow 时归档旧 workflow

**优先级**：P1
**影响维度**：过程
**预期分数变化**：过程 +1

**触发实例**：
> v5 E2E 中，group 已有已完成的 todo-cli workflow。提交 wf-notes-v1 时，旧 workflow 的 task 映射未清除，导致 ID 冲突。

**根因**：无 workflow 生命周期管理（archive/complete/clear）。

**改进方案**：`cccc workflow submit` 时检查是否存在同名或冲突的 task ID，发出警告或自动归档旧 workflow。

---

## 八、综合评分：2.3/5

**计算**：(结果 2 + 过程 1 + 体验 4) / 3 = 2.3

**评语**：Ralph CLI 工具链（validate/suggest/verify/complete）在 Foreman 手中工作良好，Worker 可靠性高。但 workflow engine 的 task ID 冲突导致过程维度完全断裂——engine 的闭环能力在复用 group 场景下为零。结果维度的 SQLite 并发 bug 与 v4 同模式，说明 verification checks 虽然从"只有 compile"升级到了"compile + behavior test"，但 behavior test 的深度仍不足以覆盖并发/错误路径。

**v6 建议重测条件**：
1. 使用全新 group（消除 task ID 冲突变量）
2. 实现 FIX-6（workflow scope isolation）或 FIX-7（stale workflow cleanup）
3. 观察 RO-17 W_VERIFICATION_SHALLOW_CHECKS 是否在 plan validate 时对浅层 checks 发出警告
