# CCCC 实战评估报告 v4

> 日期：2026-04-03
> Workflow ID: kanban-v4
> Group: g_22b16455dff8
> 总耗时：~396s (~6.5 分钟)
> 任务数：4/4 completed, 0 failed
> Workers: 3 (全部 claude runtime), 100% completion rate

## 评分摘要

| 维度 | 分数 | 关键发现 |
|------|------|----------|
| 结果指标 | 2/5 | 1 CRITICAL (SQLite FK 连接级失效), 4 WARN |
| 过程指标 | 4/5 | 9/10 项正面；缺 validate 日志证据 |
| 体验指标 | 4/5 | 70% 自动化，零手工 cccc send，DAG 门控生效 |
| **综合** | **3.3/5** | 过程+体验大幅提升，结果被 CRITICAL 拉低 |

---

## 一、结果指标（2/5）

### CRITICAL

- **[backend/app/database.py:24]** SQLite 外键约束只在建表连接上执行 `PRAGMA foreign_keys = ON`，但 `NullPool` 配置下每个 `AsyncSession` 都拿到新连接，默认 `foreign_keys=0`。非法外键值可直接 commit 成功。**v1 根因仍然存在。**

### WARN

- **[frontend/src/api.ts:3]** API 基址写死 `http://localhost:8000/api`，与 nginx.conf 反代设计不一致
- **[frontend/src/types.ts:16]** `Task.description` 是必填 `string`，后端 schema 是 `str | None`
- **[backend/app/main.py:18]** CORS origin 硬编码两个本地端口
- **[frontend/src/pages/KanbanPage.tsx:86]** render 阶段对 state 数组原地 `sort()` 突变

### OK

- 删除后 position 重排 — v2 bug 已修复
- Task move endpoint 跨列/同列重排正确
- Docker/start.sh 构建链路一致

---

## 二、过程指标（4/5）

| # | 检查项 | 判定 | 证据 |
|---|--------|------|------|
| 1 | ralph validate 提交前执行 | **无证据** | ledger 无 validate 事件；Foreman 事后总结提及但无执行痕迹 |
| 2 | 按 ralph suggest 分批提交 | ✅ | 3 个 batch_registered: [T1,T2]→[T3]→[T4]，间隔 ~2min |
| 3 | claimed_paths 精确 | ✅ | backend/, frontend/, 具体文件路径，无 "/" |
| 4 | verification 执行 | ✅ | 4 个 verification_passed，checks 非空，outcome=passed |
| 5 | depends_on 强制执行 | ✅ | T3 在 T1 验证后才启动，T4 在 T2+T3 后才启动 |
| 6 | 任务分配正确 | ✅ | T1→backend-worker, T2→frontend-worker, T3/T4→general |
| 7 | Worker 使用 task complete | ✅ | 4 个 task_reported_completed 事件 |
| 8 | 无卡死/失败 | ✅ | 无 failed/timeout/stalled 事件；T4 verification 标记 SUSPICIOUS |
| 9 | 自动化比例 | ✅ | 任务级 100%（4/4），全流程 ~70%（actor 创建手工） |
| 10 | plan 元数据传递 | ✅ | goal_behavior/verification/provides/consumes/addresses 全部保留 |

---

## 三、体验指标（4/5）

Foreman 自评要点：
- **最大改进**：零手工 `cccc send`，引擎自动下发 `[Foreman Assignment]` 到 Worker
- **DAG 门控**：T3 在 T1 完成后立即启动，不等 T2（v3 中全量提交）
- **Verification 真正执行**：非 skipped，含真实 stdout
- **Worker 自动创建**：batch 2-3 的 claude-general-worker 由引擎创建
- **不足**：batch 1 仍需手工 `cccc actor add`；plan.yaml state 不与 engine 同步；polling 无推送

---

## 四、交叉验证

| 场景 | 分析 |
|------|------|
| 结果差(2) + 过程好(4) | SQLite FK 是 **代码层** bug，工作流 verification 跑了但命令只是 `pytest`，无法发现连接级 PRAGMA 问题。需要更强的验收标准（如在测试中加 FK 违约断言） |
| 结果差(2) + 体验好(4) | Foreman 不知道 FK 没生效（测试全过），说明 verification 的质量是关键瓶��� |

---

## 五、与 v3 对比

| 方面 | v3 | v4 | 变化 |
|------|----|----|------|
| 任务自动下发 | ❌ Worker 未收到消息 | ✅ 自动 [Foreman Assignment] | **FIX-8 生效** |
| 分批门控 | ❌ 全量一批 | ✅ DAG 门控 3 批 | **FIX-6 生效** |
| Metadata 传递 | ✅ 已有 | ✅ 保持 | 无退化 |
| Verification | ✅ 已有 | ✅ 保持 | 无退化 |
| 手工 cccc send | 4+ 次 | 0 次 | **消除** |
| 自动化率 | ~30% | ~70% | +40pp |
| 过程评分 | 3/5 | 4/5 | +1 |
| 体验评分 | 3/5 | 4/5 | +1 |
| 结果评分 | 3/5 | 2/5 | -1 (不同 CRITICAL) |
| 综合评分 | 3.0/5 | 3.3/5 | +0.3 |

---

## 六、根因定位

### 已解决
- **FIX-8** Worker PTY 消息消费 → daemon op=send fallback ✅
- **FIX-6** --plan 全量提交 → atomic register_and_suggest ✅
- **FIX-10** 任务分配匹配 → path-domain scoring ✅ (T1→backend, T2→frontend)
- **FIX-7** duration_seconds → 已在 WF-7 中修复 ✅

### 未解决
- **SQLite FK** 连接级 PRAGMA 失效 — v1 遗留，verification 无法检测
- **plan.yaml state 不同步** — CLI ralph suggest 用静态文件，engine 更新不回写
- **Batch 1 worker 手工创建** — 后续 batch 自动创建，首批不行

### 新发现
- **FIX-11** daemon start 恢复所有 group actor — 已写入问题清单
- **validate 无 ledger 事件** — 无法从日志证明 Foreman 执行过 validate

---

## 七、后续改进

### FIX-12 SQLite 外键约束连接级启用（P0）
- **触发实例**：v4 对抗审查发现 NullPool + 一次性 PRAGMA = 每个请求连接 FK 未启用
- **方案**：在 engine 创建时注册 `event.listen(engine.sync_engine, "connect", _set_fk_pragma)` 回调，确保每个新连接都执行 PRAGMA
- **影响维度**：结果 2→4

### FIX-13 plan.yaml state 自动回写（P1）
- **触发实例**：Foreman 反馈 ralph suggest 显示 stale state
- **方案**：engine 完成任务时回写 plan.yaml 的 state.completed_task_ids

### FIX-14 Batch 1 worker 自动创建（P2）
- **触发实例**：Foreman 手工 `cccc actor add` backend-worker + frontend-worker
- **方案**：workflow submit 时如果 agent pool 为空，自动创建 worker actor

---

## 八、综合评分：3.3/5

| 版本 | 日期 | 结果 | 过程 | 体验 | 综合 | 关键改进 |
|------|------|------|------|------|------|----------|
| v1 | 04-01 | 2/5 | 1/5 | 2.5/5 | 1.8/5 | 基线 |
| v2 | 04-02 | 3/5 | 2/5 | 3/5 | 2.7/5 | +文档指引 +能力指南 |
| v3 | 04-02 | 3/5 | 3/5 | 3/5 | 3.0/5 | +WF-1 metadata +WF-4 --plan +WF-6 warning |
| v4 | 04-03 | 2/5 | 4/5 | 4/5 | 3.3/5 | +FIX-8 auto-dispatch +FIX-6 DAG gating +FIX-10 scoring |

**趋势**：过程(1→2→3→4)和体验(2.5→3→3→4)持续上升。结果波动(2→3→3→2)受具体项目 bug 影响较大。核心工作流机制（自动下发、DAG 门控、metadata 传递、verification 执行）已全面生效。下一步瓶颈在 verification 质量（能否发现连接级 bug）和首批 worker 自动创建。
