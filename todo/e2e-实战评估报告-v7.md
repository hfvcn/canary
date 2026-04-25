# CCCC 实战评估报告 v7

> 日期：2026-04-07
> Workflow ID: wf-notes-v7
> Group: g_22495d48db02
> 总耗时：~18 分钟（含 2 次 retry）
> 任务数：3/3 completed, 17/17 tests passing
> 项目：笔记管理 REST API（FastAPI + SQLite + pytest）

## 评分摘要

| 维度 | 分数 | 关键发现 |
|------|------|----------|
| 结果 | 4/5 | 0 CRITICAL, 4 WARN (LIKE wildcard, 连接泄漏, TOCTOU, import 副作用) |
| 过程 | 4/5 | 10/10 有证据; 首批 assigned_by 空（daemon 重启前旧代码）; unauthorized_subagent violation (observe) |
| 体验 | 3.5/5 | retry 需两步操作; worker 自报告不可靠; sync-state 反馈不清 |
| **综合** | **3.8/5** | v6 was 3.3/5, +0.5 |

---

## 一、结果指标（4/5）

### 审查方法
Codex 对抗式代码审查，逐文件静态审查 + pytest 执行。

### 发现

```
WARN: [app/db.py:62-64] LIKE wildcard 注入 — search 中 % 和 _ 未转义
      影响：搜索 "%" 返回所有笔记。非 SQL 注入（用了参数化查询），但违反最小惊讶原则。

WARN: [app/db.py] SQLite 连接无 try/finally
      影响：异常后连接不关闭，长期运行可累积文件描述符泄漏。

WARN: [app/main.py:36-41] TOCTOU 竞态 — PUT 先查再改，两次连接之间可被删除
      影响：并发下可能返回 null/200 而非 404。

WARN: [app/main.py:8] init_db() 在 import 时执行，产生 notes.db 副作用
      影响：测试 monkeypatch 在 import 后，残留 notes.db 文件。

OK:   SQL 注入 — 全部使用参数化查询，无 f-string SQL
OK:   HTTP 状态码 — 201/200/204/404/422 全部正确
OK:   数据模型 — id/title/content/created_at/updated_at 完整
OK:   输入验证 — Pydantic NoteIn 正确拒绝无效输入
OK:   测试覆盖 — 17 个测试覆盖 CRUD + 搜索 + 错误路径 + 空列表
OK:   测试隔离 — conftest 每测试独立临时数据库
```

**评分理由**：0 CRITICAL, 4 WARN 不影响主流程, 测试全面 → 4/5

---

## 二、过程指标（4/5）

### 10 项必检结果

| # | 检查项 | 结果 | 证据 |
|---|--------|------|------|
| 1 | Foreman 执行 ralph validate | 有证据 | workflow.plan_validated 事件 04:27:43, valid=true, 0 errors |
| 2 | 按 ralph suggest 批次提交 | 有证据 | 3 个 ralph- 前缀 batch（T1→T2→T3 串行） |
| 3 | claimed_paths 精确 | 有证据 | T1:[app/db.py, app/__init__.py, requirements.txt], T2:[app/main.py], T3:[tests/...] |
| 4 | verification.checks 在 engine 运行 | 有证据 | 5 次 verification 全部执行了实际 checks（CRUD smoke, TestClient, pytest），无 skipped |
| 5 | depends_on 被 engine 强制执行 | 有证据 | T2 在 T1 passed 后才提交，T3 在 T2 passed 后才提交 |
| 6 | 分配来自 Foreman 决策 | 有证据（瑕疵）| 5 个 batch_approved 中 4 个 assigned_by="planner"，首批 assigned_by="" |
| 7 | Worker 使用 cccc task complete | 有证据 | 5 个 task_reported_completed 事件 |
| 8 | 失败/重试事件 | 有证据 | T1, T2 各 1 次 verification_failed + retry_requested |
| 9 | 失败显式暴露，无 silent fallback | 有证据 | 所有失败通过 orchestrator 通知 Foreman，Foreman 手动诊断+重试 |
| 10 | plan.yaml 元数据透传到 engine | 有证据 | task_registered 含 goal_behavior, acceptance_criteria, verification.checks, provides/consumes |

**附加观察**：
- `unauthorized_subagent` violation（observe 模式）：worker-1 在首批中触发，因 known-agents 未包含动态创建的 actor。这是 daemon 重启前旧代码的行为——重启后不再发生（FIX-24 生效）。
- 首批 `assigned_by: ""` 是 daemon 重启前旧代码的行为——重启后的批次全部有 `assigned_by: "planner"`（FIX-23 生效）。
- retry 路径有摩擦：worker 遇到 `invalid_state_transition`，Foreman 需要两步操作（retry + 重新 submit with assignments）。

**评分理由**：10/10 有证据, 无 P0 机制失效, 无 silent fallback; 首批 assigned_by 空+violation 为旧代码残留 → 4/5

---

## 三、体验指标（3.5/5）

### Foreman 反馈摘要（来源：WORKFLOW_EVALUATION.md）

**正面**：
- Ralph verification checks 捕获了真实 bug（T1 签名不匹配, T2 init_db 未调用）
- plan.yaml + acceptance_criteria + checks 结构使失败诊断快速明确
- 工作流状态机（submit/retry/complete）运行可预测
- provides/consumes 契约正确阻断了有依赖的下游任务
- ralph suggest 正确识别下一批

**负面**：
- retry 留 task 在 ready 状态（丢失 agent assignment），需两步操作恢复
- Worker 自报告"all checks pass"但 verification 实际 failed，自报告不可靠
- ralph sync-state 显示 "Synced 0 tasks" 但实际已同步，反馈令人困惑

**手工干预**：3 正常决策 + 2 系统缺口 workaround

**自评**：7/10

**评分理由**：中等摩擦, retry 两步操作是系统缺口, 但 Foreman 始终掌握决策权 → 3.5/5

---

## 四、交叉验证

| 场景 | 分析 |
|------|------|
| 结果 4 + 过程 4 | 一致：工作流机制运行正常，verify checks 拦住了 2 次实现问题，最终产出质量高 |
| 过程 4 + 体验 3.5 | 差异来源：retry 路径的摩擦。日志显示机制正确（retry→resubmit→pass），但体验有 2 次 workaround |
| verification_failed 拦住 bug | 这是 v7 最大亮点：checks 不只是 compile+import，包含了实际 CRUD smoke test，成功拦截了 2 个实现偏差 |

---

## 五、与上一版对比（v7 vs v6）

| 维度 | v6 | v7 | 变化 | 归因 |
|------|----|----|------|------|
| 结果 | 3.5/5 | 4/5 | +0.5 | verification checks 更强（含 CRUD smoke, TestClient），拦住了实现偏差 |
| 过程 | 3/5 | 4/5 | +1.0 | plan_validated 写入 ledger（FIX-15）; assigned_by 有值（FIX-23, 重启后）; metadata 透传（FIX-18） |
| 体验 | 3.5/5 | 3.5/5 | 0 | retry 摩擦仍在；sync-state 反馈问题新增 |
| **综合** | **3.3/5** | **3.8/5** | **+0.5** | 主要来自过程指标改善 |

### Batch G2 修复在 v7 中的验证情况

| 修复 | 验证结果 |
|------|----------|
| FIX-13 plan.yaml auto-sync | 部分验证：daemon 重启前的完成任务无法自动同步（旧代码），重启后机制就绪但 Foreman 未再触发 |
| FIX-21 Foreman --group 文档 | 已验证：Foreman 使用了 `ralph validate --group g_22495d48db02`，ledger 出现 plan_validated 事件 |
| FIX-22 resuggest 排除 ASSIGNED | 未触发验证场景（无并行任务） |
| FIX-23 assigned_by | 已验证：重启后 4 个批次全部有 `assigned_by: "planner"` |
| FIX-24 monitor 动态 actor | 部分验证：重启前旧代码产生 violation，重启后无新 violation |

---

## 六、根因定位

### 已解决（本轮验证）
- **plan_validated 无 ledger 事件**（FIX-15）→ 有事件
- **assigned_by 为空**（FIX-23）→ 重启后有值
- **metadata 未透传**（FIX-18）→ task_registered 含完整 goal_behavior/checks/provides
- **checks 质量不足导致 verify gate 跳过**（FIX-21 checks 质量要求）→ 本轮 checks 含 CRUD smoke，成功拦截

### 未解决
- **retry 需两步操作** → 新增 FIX-25
- **Worker 自报告与 verification 矛盾无告警** → 新增 FIX-26
- **sync-state "Synced 0 tasks" 反馈不清** → FIX-13 追加

### 新发现
- **daemon 重启导致 Foreman 上下文丢失** — actor 进程重启后需要 cold start，中断了工作流。需要人工 nudge 恢复。
- **首批 assigned_by 空** — 因 daemon 重启前运行旧代码。教训：代码修改后必须在 E2E 前重启 daemon。

---

## 七、后续改进及对应实例

### FIX-25 retry 应支持 --assign AGENT_ID 一步完成（P1）
- **现象**：v7 T1/T2 retry 后 task 变为 ready（丢失 assignment），Foreman 需手动创建 temp JSON + resubmit
- **根因**：`cccc workflow retry` 只重置状态，不保留或接受新 assignment
- **改进方案**：`cccc workflow retry TASK_ID --assign AGENT_ID` 一步完成重置+分配
- **影响维度**：体验 +0.5

### FIX-26 Worker 自报告与 verification 矛盾应显式告警（P2）
- **现象**：v7 T1/T2 worker evidence_summary 声称 "all checks pass"，但 verification_failed
- **根因**：orchestrator 不比较 worker 自报告与 verification 结果
- **改进方案**：verification 结果与 worker evidence 不一致时，在通知中显式标注 "DIVERGENCE: worker claimed success but verification failed"
- **影响维度**：过程（审计）+ 体验 +0.5

---

## 八、综合评分：3.8/5

相对 v6（3.3/5）提升 0.5 分，主要来自过程指标改善（plan_validated 事件、assigned_by 填充、metadata 透传、checks 质量提升）。体验维度无变化（retry 摩擦新增，抵消了 checks 质量带来的正向体验）。
