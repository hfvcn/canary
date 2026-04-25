**VERDICT**: `needs-attention`

**SUMMARY**: 风险评级 `high / no-ship`。Batch D 瞄准了真实问题，但按当前计划直接推进仍然不安全：T5 的级联阻塞设计建立在 `_active_workflows` 影子状态之上，而 `WorkflowEngine.block_task()` 现在对终态没有保护，容易把已完成任务重新打成 `BLOCKED`，并在菱形 DAG 中重复写 block 事件；T3/T4 想用 `attempt_id` 做 CAS，但当前 daemon -> orchestrator -> engine 的完成事件链路只透传 `assignment_id/actor_run_id`，且 `apply_task_event()` 根本不消费这些字段，导致“可选 attempt_id 校验”会在兼容旧客户端时留下陈旧完成消息的旁路；T1 把 `DEFERRED -> READY` 交给 `register_batch()` 也过于宽松，当前实现会无条件把非完成任务提回 `READY`，且不会清理复用的 `blocked_reason`。我已读取用户指定的全部文件，并运行了 `python -m pytest tests/test_workflow_state.py tests/test_foreman_workflow.py tests/test_workflow_e2e_closure.py -q --tb=short`，当前基线为 `86 passed`；但这些测试没有覆盖 deferred 持久化、attempt CAS、block cascade。

**PRIMARY FINDINGS**:
- **[severity: critical]** T5 的递归级联阻塞会在并发完成和菱形 DAG 下产生错误 block 与重复 ledger 事件
  - File: `plans/batch-d-engine-state-integrity.yaml`, lines 189-203; `src/cccc/kernel/workflow_state_engine.py`, lines 177-184; `src/cccc/daemon/foreman/workflow_orchestrator.py`, lines 1011-1016, 1119-1127, 1719-1726
  - Confidence: 0.96
  - Body: T5 计划要求 `_cascade_block()` 递归遍历 `_active_workflows[workflow_id]["tasks"]`，只要影子状态不是 `COMPLETED/ARCHIVED` 就继续 `engine.block_task(...)`。但当前 `WorkflowEngine.block_task()` 没有任何终态保护或幂等保护：
    ```py
    self._append(kind=wt.KIND_TASK_BLOCKED, ...)
    self._tasks[tid] = replace(prev, status=WorkflowTaskStatus.BLOCKED, blocked_reason=why)
    ```
    这意味着只要影子状态读到的是旧值，级联就能把刚刚完成的任务重新覆盖成 `BLOCKED`。`on_task_completed()` 先通过 engine 完成验证，再单独回写 `_active_workflows`（`workflow_orchestrator.py:1011-1016`），两者之间没有原子性；而 T5 明确依赖影子状态做递归裁决。另一个问题是菱形 DAG：按 T5 的递归写法，`A -> B`, `A -> C`, `B/C -> D` 时，`D` 会沿两条路径各触发一次 `engine.block_task()`，ledger 中出现重复 `workflow.task_blocked` 事件，通知也会重复。
    Worst case: 已经成功完成并通过验证的下游任务被晚到的级联重新打成 `BLOCKED`，随后更下游全部停摆；或者同一个下游在 fan-in 图上被重复 block/cancel，导致 ledger 与 UI 都出现不可解释的重复状态。
    Test coverage: 我没有在 `tests/test_workflow_state.py`、`tests/test_foreman_workflow.py`、`tests/test_workflow_e2e_closure.py` 里找到任何针对 `block_task()` / `_cascade_block()` / 菱形 DAG 去重的现有测试。`tests/test_workflow_e2e_closure.py:116-167` 只覆盖“完成后 resuggest 通知 Foreman”，不覆盖 block。
  - Recommendation: 在 T5 落地前把 block 语义收紧到 engine 侧。至少要同时做 4 件事：1) `WorkflowEngine.block_task()` 拒绝覆盖 `COMPLETED/ARCHIVED`，并对已 `BLOCKED` 的 task 幂等返回；2) `_cascade_block()` 使用 `visited` 集合，避免 fan-in 重复 block；3) 每次递归前重读 engine 真实状态，而不是只看 `_active_workflows`；4) “取消 RUNNING 下游”不能只通知 Foreman，必须定义可执行的取消路径，否则 sibling 仍会继续写仓库。

- **[severity: high]** T3/T4 的 `attempt_id` CAS 没有接入真实完成事件入口，且“仅在 payload 包含 attempt_id 时校验”会把旧客户端留成绕过通道
  - File: `plans/batch-d-engine-state-integrity.yaml`, lines 107-127, 150-161; `src/cccc/contracts/v1/ralph_ipc.py`, lines 213-221; `src/cccc/daemon/ops/workflow_task_ops.py`, lines 109-126; `src/cccc/daemon/ralph_ipc_handler.py`, lines 891-907; `src/cccc/daemon/foreman/workflow_orchestrator.py`, lines 1584-1591; `src/cccc/daemon/foreman/ralph_service.py`, lines 232-253
  - Confidence: 0.98
  - Body: 当前完成事件的真实入口是 `workflow_task_ops.complete_task()` -> `handle_ralph_task_event()` -> `WorkflowOrchestrator.apply_task_event()`。这条链路现在只透传 `assignment_id/actor_run_id`，没有 `attempt_id` 字段；更关键的是，`apply_task_event()` 最终调用 `engine.report_worker_completion()` 时，只带了 `agent_id/duration_seconds/changed_files/idempotency_key`，完全忽略 `assignment_id/actor_run_id`：
    ```py
    self.engine.report_worker_completion(
        task_id,
        {
            "agent_id": agent_id,
            "duration_seconds": duration_seconds,
            "changed_files": list(changed_files),
            "idempotency_key": ...,
        },
    )
    ```
    所以 T3 如果只在 engine 里加“payload 有 `attempt_id` 才做 CAS”，旧客户端或旧 ledger replay 的空值路径仍会直接绕过 CAS。反过来，如果实现成“空 `attempt_id` 也必须匹配”，当前所有只会发 `assignment_id/actor_run_id` 的调用方都会被误杀。`ralph_service.py:232-253` 的 docstring 还声称做了 “Assignment validity”，但实现实际上只有 idempotency，这进一步说明当前协议边界还没准备好承接 T3 的方案。
    Worst case: 任务 retry 并重新分配后，旧 worker 的迟到完成事件仍被接受，新的 attempt 被旧结果污染；或者升级后所有旧 worker/旧 CLI 因为空 `attempt_id` 被系统性拒绝。
    Test coverage: `tests/test_workflow_state.py:99-123` 只验证 retry 后状态回到 `READY`，没有验证 `agent_id` 清空，也没有 attempt correlation。当前三个测试文件中，我没有找到任何覆盖 `assignment_id/actor_run_id` 或 stale completion 的测试。
  - Recommendation: 不要把 T3 设计成“engine 内部补一个可选字段”就结束。需要先定义兼容策略，再改入口协议：1) 在 `TaskEvent`、`workflow_task_ops.complete_task()`、`handle_ralph_task_event()`、`WorkflowOrchestrator.apply_task_event()` 全链路统一透传 `attempt_id`；2) 明确旧字段如何映射，最好把 `assignment_id` 视为旧版 `attempt_id` 的兼容来源；3) 在 orchestrator 接收完成事件时先做 CAS，再调用 engine；4) T6 必须走 daemon IPC 入口，而不是只测 engine API。

- **[severity: high]** Batch D 仍把 `_active_workflows` 留作真实调度权威，T2/T4/T5 只修局部写入点，无法消除 engine 与 shadow 的状态撕裂
  - File: `plans/batch-d-engine-state-integrity.yaml`, lines 64-80, 150-157, 199-203; `src/cccc/daemon/foreman/workflow_orchestrator.py`, lines 617-649, 651-691, 927-985, 1104-1147, 1792-1839; `src/cccc/daemon/foreman/ralph_service.py`, lines 605-621; `todo/问题清单.md`, lines 113-123
  - Confidence: 0.93
  - Body: T2 确实打中了 `_record_deferred_tasks()`，但计划只提到 `_build_task_snapshot()` 改读 engine，没有处理当前一系列仍然把 shadow 当权威的读路径：`_get_all_assignments()` 读取 `_active_workflows` 再驱动 `_defer_batch_for_single_writer()`；`get_workflow_state()` 直接把 `_active_workflows[workflow_id]["tasks"]` 序列化给外部；`ralph_service._build_task_status_index()` 又从 `_active_workflows` 拉状态用于依赖判断。也就是说，即使 T1/T2 把 `DEFERRED` 写进 ledger，实际“是否允许 resuggest / 是否还算 running / 单写者冲突是否存在”的判断仍然可能基于旧 shadow。`todo/问题清单.md:113-123` 已经把这个裂缝定义为 `ARCH-4`，而 Batch D 目前没有把这层 authority 收紧，只是加了更多双写点。
    Worst case: engine 已经把任务 defer/block/retry 了，但 orchestrator 仍按旧 shadow 把它当成 pending/running 继续参与 resuggest 或单写者判定；daemon 重启后 ledger replay 与内存 shadow 产生不同视图，前台 API 和实际执行各说各话。
    Test coverage: `tests/test_workflow_e2e_closure.py:155-160` 直接手改 `_active_workflows` 来驱动 `_resuggest_ready_tasks()`；`tests/test_foreman_workflow.py:1698-1719` 也手工注入 `_active_workflows` 给 monitor 使用。现有测试事实上强化了 shadow 依赖，而不是验证 engine authority。
  - Recommendation: 把 T2/T4/T5 当成一次“权威边界收口”而不是几个点修。至少先把下列读路径切到 engine 或 engine-first：`_get_all_assignments()`、`get_workflow_state()`、`_resuggest_ready_tasks()` 候选过滤、`ralph_service._build_task_status_index()`。在这之前，任何“状态已持久化到 engine”的验收结论都不牢靠。

- **[severity: medium]** T1 用 `register_batch()` 作为通用 undefer 路径会留下陈旧 `blocked_reason`，而且当前实现对状态过于宽松
  - File: `plans/batch-d-engine-state-integrity.yaml`, lines 26-35; `src/cccc/kernel/workflow_state_types.py`, lines 41-52; `src/cccc/kernel/workflow_state_engine.py`, lines 33-49
  - Confidence: 0.88
  - Body: T1 明确要把 defer 原因复用到 `TaskState.blocked_reason`，并允许 `register_batch()` 把 task 从 `DEFERRED` 拉回 `READY`。但当前 `register_batch()` 的状态更新是：
    ```py
    self._tasks[tid] = replace(prev, status=WorkflowTaskStatus.READY, batch_id=bid)
    ```
    这会保留 `prev.blocked_reason`，因为没有显式清空；同时它只禁止 `COMPLETED/ARCHIVED`，也就是未来如果枚举里新增 `DEFERRED`，任何重新 register 的 batch 都能把它提回 `READY`，不区分 defer 原因是否已经消失。计划把“undefer”绑定给 `register_batch()`，但没有补清理规则和更窄的状态机边界。
    Worst case: UI/API 上出现“状态是 READY，但 reason 仍显示 single_writer_active”的脏状态；或者外部重复提交 batch 时，在冲突条件未解除的情况下把 defer 任务重新唤醒。
    Test coverage: 当前三个测试文件中，我没有找到任何覆盖 deferred reason 清理或 `register_batch()` 对新状态枚举约束的测试。
  - Recommendation: T1 至少要补 3 条明确规则：1) `register_batch()` 只允许 `{PLANNED, READY, DEFERRED}` 进入 READY，不接受任意非终态；2) 从 `DEFERRED -> READY` 时清空 `blocked_reason`；3) 如果 defer 原因是单写者冲突，undefer 前必须重新验证冲突是否消失，而不是把“重新 register batch”本身当成解除条件。

**STRUCTURAL PRESSURE TEST**:

Per-task analysis:
- T1: 目标方向正确，但“把 defer reason 塞进 `blocked_reason` 再靠 `register_batch()` 解除”过于偷懒。`src/cccc/kernel/workflow_state_engine.py:33-49` 说明 undefer 现在会保留旧 reason，且没有更细的状态守卫。最坏后果是 READY 任务携带陈旧阻塞原因，或在冲突未消失时被错误唤醒。现有测试无法抓到这一点；我没有找到 deferred 场景测试。
- T2: `_record_deferred_tasks()` 改调 engine 是必要的，但计划只修了 `_build_task_snapshot()`，没有覆盖 `_get_all_assignments()`、`get_workflow_state()`、`ralph_service._build_task_status_index()` 这些仍读 shadow 的路径（`workflow_orchestrator.py:617-649`, `1792-1839`; `ralph_service.py:605-621`）。最坏后果是 deferred 已持久化，但调度与前台仍看见旧状态。现有测试也主要围绕 shadow 打桩。
- T3: 计划核心风险在于边界定义不完整。真正需要 CAS 的不是一个抽象的 `complete_task()`，而是 `WorkflowOrchestrator.apply_task_event()` 这条统一入口（`workflow_orchestrator.py:1524-1686`）。最坏后果是引入了 `attempt_id` 字段但旧完成事件仍能穿透，形成“看起来有 CAS，实际上没有”的假安全。现有测试只覆盖 retry 状态回退。
- T4: 计划要求 shadow 也记录 `attempt_id`，但当前 `TaskAssignment` 数据结构根本没有该字段（`src/cccc/daemon/foreman/agent_pool.py:90-110`）。如果不先扩展任务分配对象和所有序列化路径，T4 很容易沦为局部 dict hack。最坏后果是 engine 与 shadow 的 attempt 不一致，monitor / resuggest / UI 又各自读不同来源。现有测试没有覆盖 retry 后 agent 元数据清空。
- T5: 这是本批最高风险任务。除了上面的主发现外，计划宣称“RUNNING 下游 task 收到取消通知”，但当前 orchestrator 只实现了通知 Foreman，没有任何 worker cancel/stop 路径，`_stop_actor_fn` 在本文件中完全未用于任务取消（`workflow_orchestrator.py:126, 178`）。最坏后果是下游虽然被标记 blocked，但真实 worker 继续修改代码。现有测试无覆盖。
- T6: 计划里的 6 个 E2E 场景是必要的，但还不够。它必须显式覆盖 daemon IPC 入口 `handle_ralph_task_event()` / `workflow_task_ops.complete_task()`，否则抓不住 T3/T4 的协议断层；还应该补一个菱形 DAG 案例来断言 block 事件只写一次。最坏后果是测试全部通过，但真实 CLI/daemon 入口仍然绕过 `attempt_id` 或重复 block。当前仓库还没有 `tests/e2e/test_engine_state_integrity.py`。

Cross-cutting concerns:
- Race conditions: `_active_workflows` 在 `process_batch_suggestion()`、`on_task_completed()`、`on_task_failed()`、`on_heartbeat()`、`retry_task()`、`block_task()` 多处直接原地修改（`workflow_orchestrator.py:292-377`, `1011-1016`, `1236-1240`, `1276-1287`, `1700-1705`, `1722-1726`），没有锁、没有版本号、没有 compare-and-swap。任何基于 shadow 的递归状态变更都要假设并发事件会打进来。
- State consistency: `get_workflow_state()`、`_get_all_assignments()`、`ralph_service._build_task_status_index()` 仍把 shadow 暴露给外界；Batch D 如果不先切 read-path，就会继续扩散双写。
- Backward compatibility: 当前外部协议里存在 `assignment_id/actor_run_id`，不存在 `attempt_id`；同时旧 ledger 也没有 `attempt_id`。Batch D 需要明确“旧字段如何映射到新 CAS 语义”，否则要么绕过，要么误拒绝。

Dependency and ordering analysis:
- 当前依赖图里，T5 只依赖 T1 不够。因为 `_resuggest_ready_tasks()` 和 `ralph_service` 现在都依赖 shadow 状态，T5 至少应依赖一个“blocked/deferred/read-path 已 engine-first”的前置任务；否则它修的是症状，不是边界。
- T3/T4 的顺序本身合理，但 T3 还缺一个更早的协议前置：先定义 `attempt_id` 在 `TaskEvent` / daemon op / ledger event 中的兼容格式，再改 engine。否则 T4 无法证明 shadow 和 engine 的 `attempt_id` 一致。
- T6 现在依赖 `T2/T4/T5`，但测试内容若不覆盖 daemon IPC 完成路径、菱形 DAG 和旧字段兼容，就不能真正验收 T3/T5。建议把“daemon completion path coverage”写成 T6 的硬验收项，而不是可选补测。

Final ranked issues by severity:
1. `critical`: T5 可能把已完成任务重新 block，并在 fan-in DAG 中重复写 `workflow.task_blocked`。
2. `high`: T3/T4 的 `attempt_id` CAS 没有接上真实完成事件链路，旧字段兼容策略缺失。
3. `high`: Batch D 仍然把 `_active_workflows` 留作调度权威，engine 与 shadow 会继续撕裂。
4. `medium`: T1 的 undefer 路径会保留陈旧 `blocked_reason`，且 `register_batch()` 状态边界过宽。

**NEXT STEPS** (if needs-attention):
- 先重写 T5：把 block 去重、终态保护、engine-first 读取、真实取消路径定义清楚，再谈级联。
- 先补 T3 的协议设计：统一 `attempt_id` 入口和旧字段映射，再把 CAS 接到 `apply_task_event()`。
- 把 T2/T4/T5 共同前置为一次 read-path 收口，至少覆盖 `_get_all_assignments()`、`get_workflow_state()`、`_resuggest_ready_tasks()`、`ralph_service._build_task_status_index()`。
- 扩大 T6：必须覆盖 daemon IPC 完成路径、菱形 DAG block 去重、以及空/旧 `attempt_id` 兼容场景。
