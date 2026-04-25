# CCCC 实战评估报告 v6

> 日期：2026-04-07
> Workflow ID: markdown-notes-api
> 总耗时：~429s (~7 min)
> 任务数：4/4 completed, 0 failed
> Batches: 3 (T1 → T2+T3 parallel → T4)
> Workers: 2 (worker-1: claude, worker-2: claude)

## 评分摘要

| 维度 | 分数 | 关键发现 |
|------|------|---------|
| 结果 | 2/5 | Tag CRUD 缺 update endpoint (CRITICAL) |
| 过程 | 3/5 | 7/10 有证据；plan_validated 缺；assigned_by 空；7 条 monitor violation |
| 体验 | 4.5/5 | Foreman 决策权被尊重；仅 1 处 workaround |
| **综合** | **3.2/5** | |

---

## 一、结果指标（2/5）

审查者：Codex 对抗式代码审查

```
CRITICAL: [app/routers/tags.py:12] Tags router 缺 PUT/PATCH update endpoint
         Tag CRUD 不完整，tag 创建后无法改名
         复现：POST /tags/ 创建 tag → PUT /tags/{id} → 405

WARN:    [app/routers/notes.py:18] tag_ids 去重导致有效请求被拒
         请求含重复 tag_ids 时 IN 查询返回去重结果，len 不匹配触发 400

WARN:    [tests/test_notes.py:6] 测试未覆盖 response schema 细节
         created_at/updated_at 字段、nested tags schema 未断言

OK:      [security] 无 SQL 注入向量，全部使用 SQLAlchemy
OK:      [foreign keys] SQLite FK 正确启用 (PRAGMA foreign_keys=ON via event listener)
OK:      [data model] note_tags 关联表有级联删除
OK:      [API semantics] GET/PUT/DELETE 正确返回 404
OK:      [test coverage] 覆盖 note CRUD, tag create/read/delete, 关联, 筛选, 404, 400
```

---

## 二、过程指标（3/5）

审查者：Codex ledger 日志分析（60 行账本）

| # | 检查项 | 判定 | 证据 |
|---|--------|------|------|
| 1 | Foreman 执行 ralph validate | 无证据 | 账本无 workflow.plan_validated 事件 |
| 2 | 按 ralph suggest 分批提交 | 有证据 | 3 批次：T1 → T2+T3 → T4，由 tasks_ready 通知驱动 |
| 3 | claimed_paths 精确 | 有证据 | T1: 6 个具体文件，T2: routers/notes.py, T3: routers/tags.py, T4: tests/ |
| 4 | verification.checks 执行 | 有证据 | 4/4 任务有非空 checks 且全部 passed（compile+fk_check/smoke/test） |
| 5 | depends_on 被强制执行 | 有证据 | T2/T3 在 T1 passed 后启动；T4 在 T2+T3 都 passed 后启动 |
| 6 | 分配归因到 Foreman | 无证据 | batch_approved 中 assigned_by="" assigned_at=null |
| 7 | Worker 使用 task complete | 有证据 | 4 条 task_reported_completed 事件 |
| 8 | 卡死/失败/重试事件 | 无证据 | 无 failed/timeout/stalled 事件（无失败发生，N/A） |
| 9 | 失败显式暴露 | 有证据 | 7 条 monitor_violation 均 observe 模式，未静默吞掉 |
| 10 | plan.yaml 元数据透传 | 有证据 | task_registered 含 depends_on/claimed_paths/verification/provides/consumes |

**Monitor Violations（7 条，observe 模式）：**
- 4× `unauthorized_subagent`: worker-1/worker-2 不在 known-agents set（worker 是运行时创建的，尚未注册到 monitor）
- 3× `file_overstepping`: T2/T3/T4 修改了 claimed_paths 之外的 app/main.py（router include 需要修改 main.py）

---

## 三、体验指标（4.5/5）

审查者：Foreman 自评

**正面反馈：**
- Ralph validate 在第一次就抓到了 role 不匹配
- Ralph suggest 正确识别并行批次
- Auto-dispatch 消除了手工 `cccc send` 任务描述（v1-v2 的核心痛点）
- Verify gate 4/4 非空 checks，全部 passed
- DAG gating 正确（T2+T3 不互相等待）
- Resuggest 通知及时且可操作

**负面反馈：**
- Ralph state sync 需手动 `ralph complete`（engine 和 ralph 状态分离）
- 提交第二批时重复注册已有任务（语义混淆，非功能问题）
- Resuggest 通知含已运行的任务（minor）

**手工干预：**
- 9 项 Foreman 正常决策（计划、验证、选人、分配、提交、监控、验收）
- 1 项系统缺口 workaround（手动 ralph complete）

---

## 四、交叉验证

| 场景 | 分析 |
|------|------|
| 结果差(2) + 过程好(3) | Tag update endpoint 缺失未被 verify gate 拦截——verification.checks 只检查 compile + smoke（import 测试），不验证 API completeness。说明 checks 粒度不够，需要更强的 acceptance 验证 |
| 体验好(4.5) + 结果差(2) | Foreman 自评 5/5 result quality（"28/28 tests pass"），但审查发现 tests 本身就不覆盖 tag update。Foreman 的"通过=正确"假设未被挑战 |
| 过程 #1 无证据 | Foreman 确实运行了 ralph validate（自述"second attempt, 0 errors"），但未使用 --group/--ledger 参数，所以 ledger 无事件。FIX-15 (T5) 已实现该功能，但 Foreman 不知道使用方法 |
| 过程 #6 无证据 | assigned_by="" 是 ARCH-1 实现中的字段填充遗漏，不影响实际行为（Foreman 确实通过 --assignments 指定） |

---

## 五、与上一版对比（v6 vs v5）

| 项目 | v5 (4.2/5) | v6 (3.2/5) | 变化 | 归因 |
|------|-----------|-----------|------|------|
| 结果 | 4.5 | 2 | -2.5 | 项目不同（v5 由人审查且更简单），tag update 缺失 |
| 过程 | 3.5 | 3 | -0.5 | plan_validated 事件虽已实现但 Foreman 未使用；assigned_by 空 |
| 体验 | 4.5 | 4.5 | 0 | 维持高位，workaround 从 0 增到 1（ralph sync） |

**注意**：v5 和 v6 的项目不同（v5 是全栈看板，v6 是纯后端 API），结果分不直接可比。

### Batch G+H 新功能验证

| 功能 | 是否生效 | 证据 |
|------|---------|------|
| W_VERIFICATION_NO_CHECKS (RO-9n) | 未触发 | plan.yaml 所有 task 有 checks，规则无需触发（正确行为） |
| W_NO_FAILURE_PATH (RO-11) | 未触发 | plan 任务不含 assignment 关键词（正确行为） |
| --worker-prompt (ARCH-5) | 未使用 | Foreman 未使用该参数创建 worker |
| plan_validated 事件 (FIX-15) | 未生效 | Foreman 运行 ralph validate 但未加 --group/--ledger 参数 |
| heartbeat sweep (FIX-19) | 未触发 | 无 stalled worker（无 failure 场景） |
| skip reason (FIX-20) | 不适用 | 所有 verification 都执行了（无 skip） |

---

## 六、根因定位

### 已解决（本轮确认生效）
- Auto-dispatch 消除手工 cccc send（FIX-2/FIX-8）
- DAG gating 替代 batch gating（FIX-3/FIX-6）
- verification.checks 非空执行（FIX-1/WF-1 metadata 透传）
- Resuggest 通知 Foreman（ARCH-3）
- Monitor violation 显式记录（ARCH-9）

### 未解决
- **assigned_by 字段填充**：batch_approved 事件中 assigned_by="" assigned_at=null（ARCH-1 遗留）
- **known-agents 注册时机**：worker 动态创建后未注册到 monitor，触发 unauthorized_subagent 误报
- **file_overstepping 误报**：多个 task 需要修改共享文件（main.py 的 router include），但 claimed_paths 只能声明"主要修改的文件"

### 新发现
- **FIX-21** Foreman 不知道 `ralph validate --group` 用法——文档/提示词未提及该参数
- **FIX-22** Resuggest 通知含已运行任务——应排除 status=RUNNING 的任务
- **RO-16n** Ralph 未检查 verification.checks 是否覆盖 acceptance_criteria 的所有要求（tag update 在 acceptance 中但 checks 不检测）

---

## 七、后续改进及对应实例

### FIX-21 Foreman 文档需说明 ralph validate --group/--ledger 参数
- **优先级**：P2
- **影响维度**：过程 +0.5
- **触发实例**：v6 Foreman 运行 ralph validate 但未使用 --group 参数，ledger 无 plan_validated 事件
- **改进方案**：在 Foreman 能力指南和任务提示词中加入 `ralph validate plan.yaml --group GROUP_ID` 示例
- **验收标准**：下轮 Foreman 使用 --group 参数，ledger 出现 plan_validated 事件

### FIX-22 Resuggest 通知应排除 RUNNING 任务
- **优先级**：P2
- **影响维度**：体验 +0.5
- **触发实例**：v6 T3 完成后通知 "T2 ready" 但 T2 已在运行
- **改进方案**：_resuggest_ready_tasks 在构造通知前排除 status=RUNNING 的任务
- **验收标准**：通知中不包含已分配/运行中的任务

---

## 八、综合评分：3.2/5

计算：(2 + 3 + 4.5) / 3 = 3.2/5

**与 v5 对比**：综合分从 4.2 降至 3.2，主要因结果分大幅下降（tag update 缺失）。过程和体验维度基本持平，说明 Batch G+H 的机制改进未引入回归，但也未在本轮触发（新功能属于防御性增强，需要特定场景才能验证）。
