# CCCC × AgentFlow 整合架构设计

> 日期：2026-05-24
> 状态：Claude + Codex 共识方案（4 轮讨论，Codex 正式同意）
> SESSION_ID: 019e5992-3cc8-7e11-9ccf-94ab14de6095
> 信心评分：4/5（需 POC 验证 AF 补丁 + CCCC actor terminal event 协议）

---

## 1. 整合策略

**C 路线：CCCC 保留决策层，AgentFlow 承担执行层。**

| 层 | Owner | 职责 |
|---|---|---|
| Plan & Validation | CCCC Ralph | plan 生成、静态验证、discipline、DAG 依赖 |
| Strategy & Policy | CCCC Foreman + AgentPoolManager | 角色/模型决策、actor lease、审批 |
| DAG Scheduling | AgentFlow Orchestrator | 依赖满足、ready frontier、并发控制、retry/cancel 状态机 |
| Execution Transport | CCCCActorRunner | 持久 actor 会话投递、terminal event 等待 |
| Verification | CCCC VerificationGate | 最终验收权威（Ralph checks + security + aegis） |
| Trace & Evaluation | AF RunStore + CCCC performance store | trace 收集、评分聚合、agent 进化 |

**分配权归属**：AF 判断 node 是否 ready → CCCC `AgentPoolManager.acquire()` 判断是否有 actor lease。两段 gate，不争权。

**最终完成权**：AF `node_completed` = 执行完成；CCCC verification passed = 任务完成。

---

## 2. 核心数据结构

### ExecutionBundle（一次 workflow 执行的完整包）

```python
@dataclass(frozen=True)
class ExecutionBundle:
    run_id: str
    workflow_id: str
    pipeline: PipelineSpec       # AF 原生格式，用于 DAG 调度
    cccc_meta: dict[str, CCCCNodeMeta]  # CCCC 特有元数据 sidecar
```

### CCCCNodeMeta（每个节点的 CCCC 元数据）

```python
@dataclass(frozen=True)
class CCCCNodeMeta:
    task: TaskRef
    group_id: str
    workflow_id: str
    assignment_policy: AssignmentPolicy
    verification_spec: VerificationSpec | None
    acceptance_criteria: str
    critical_flows: tuple[str, ...]
    forbidden_flows: tuple[dict[str, Any], ...]
    prompt_projection: PromptProjection
```

### AssignmentPolicy（分配策略）

```python
@dataclass(frozen=True)
class AssignmentPolicy:
    mode: Literal["auto", "explicit", "role_pool"]
    explicit_actor_id: str = ""
    required_role: str = "worker"
    required_capabilities: tuple[str, ...] = ()
    preferred_model_key: str = ""
```

### AgentPoolManager 新增接口

```python
@dataclass(frozen=True)
class AgentAcquireRequest:
    run_id: str
    workflow_id: str
    node_id: str
    task: TaskRef
    attempt_id: str
    group_id: str
    project_root: Path
    assignment_policy: AssignmentPolicy

@dataclass(frozen=True)
class AgentLease:
    lease_id: str
    agent_id: str
    actor_id: str
    model_runtime: str
    model_id: str
    model_key: str
    is_new_actor: bool
    assignment_reason: str

class AgentPoolManager:
    async def acquire(self, request: AgentAcquireRequest) -> AgentLease: ...
    async def release(self, lease: AgentLease, outcome: str) -> None: ...
    async def mark_failed(self, lease: AgentLease, reason: str) -> None: ...
```

**设计决策**：不引入独立 ResourceBroker 层。AgentPoolManager 是唯一公开分配入口，统一承担评分、模型选择、actor 复用/创建和 lease 管理。ForemanWorkflow 保留为策略/审批层，不再自己拥有分配状态。

### ExecutionEvent（AF → CCCC 事件）

```python
@dataclass(frozen=True)
class ExecutionEvent:
    run_id: str
    workflow_id: str
    node_id: str
    task_id: str
    attempt_id: str
    kind: str  # node_ready | resource_waiting | node_started | trace |
               # node_raw_completed | verification_requested |
               # node_completed | node_failed | node_retrying |
               # node_cancelled | run_completed | run_failed
    payload: dict[str, Any]
```

---

## 3. 组件职责矩阵

| 责任 | Owner | 说明 |
|---|---|---|
| DAG scheduling | AF Orchestrator | 依赖满足、ready frontier、并发、retry tick |
| Resource allocation | CCCC AgentPoolManager | 评分、模型选择、actor lease、busy 状态 |
| Actor lifecycle | CCCC daemon + AgentPoolManager | actor add/start/restart/status |
| Task prompt | CCCC PlanCompiler + Adapter | Foreman prompt 投影保留 |
| Execution transport | CCCCActorRunner | send task、等待 terminal event、cancel bridge |
| Trace artifact | AF RunStore + CCCC trace bridge | AF 存 artifact，CCCC 建索引 |
| Verification | CCCC VerificationGate | Ralph checks / security / aegis / shallow depth |
| Evaluation | CCCC performance store + AF EvolutionRequest | trace → score → tuned candidate |

---

## 4. CCCCActorRunner 设计

AF Runner 实际签名（agentflow/runners/base.py:36）：

```python
async def execute(
    self,
    node: NodeSpec,
    prepared: PreparedExecution,
    paths: ExecutionPaths,
    on_output: StreamCallback,
    should_cancel: CancelCallback,
) -> RawExecutionResult
```

### 完整伪代码

```python
class CCCCActorRunner(Runner):
    def __init__(self, agent_pool, actor_gateway, event_stream, sidecar):
        self.agent_pool = agent_pool
        self.actor_gateway = actor_gateway
        self.event_stream = event_stream
        self.sidecar = sidecar
        self._last_outcome = "unknown"

    async def execute(self, node, prepared, paths, on_output, should_cancel):
        run_id = infer_run_id(paths)
        meta = self.sidecar[(run_id, node.id)]
        attempt_id = new_attempt_id(run_id, node.id)

        # 1. Lazy acquire: 评分 + 模型选择 + actor 创建/复用
        lease = await self.agent_pool.acquire(
            AgentAcquireRequest(
                run_id=run_id,
                workflow_id=meta.workflow_id,
                node_id=node.id,
                task=meta.task,
                attempt_id=attempt_id,
                group_id=meta.group_id,
                project_root=paths.host_workdir,
                assignment_policy=meta.assignment_policy,
            )
        )

        try:
            # 2. 通过 daemon 投递任务给 actor
            await self.actor_gateway.send_task(
                group_id=meta.group_id,
                actor_id=lease.actor_id,
                text=prepared.stdin or node.prompt,
                metadata={
                    "run_id": run_id,
                    "node_id": node.id,
                    "task_id": meta.task.id,
                    "attempt_id": attempt_id,
                    "lease_id": lease.lease_id,
                },
            )

            # 3. 等待 terminal event（非进程退出）
            while True:
                # 3a. drain actor 输出到 AF trace pipeline
                await self.drain_actor_trace(lease.actor_id, attempt_id, on_output)

                # 3b. 检查 cancel
                if should_cancel():
                    await self.actor_gateway.request_cancel(
                        group_id=meta.group_id,
                        actor_id=lease.actor_id,
                        task_id=meta.task.id,
                        attempt_id=attempt_id,
                    )
                    event = await self.event_stream.wait_cancel_terminal(attempt_id)
                    self._last_outcome = "cancelled"
                    return RawExecutionResult(
                        exit_code=130,
                        cancelled=True,
                        stdout_lines=[event.summary],
                    )

                # 3c. 检查 terminal event
                event = await self.event_stream.poll_terminal(attempt_id)
                if event is None:
                    await asyncio.sleep(0.2)
                    continue

                if event.kind == "task_completed":
                    self._last_outcome = "completed"
                    await self.emit_summary_trace(event, on_output)
                    return RawExecutionResult(exit_code=0, stdout_lines=[event.summary])

                self._last_outcome = "failed"
                await self.emit_summary_trace(event, on_output)
                return RawExecutionResult(exit_code=1, stderr_lines=[event.summary])

        finally:
            # 4. 释放 lease
            await self.agent_pool.release(lease, outcome=self._last_outcome)
```

### Retry 语义

Retry 不由 Runner 循环。AF Orchestrator 已按 `node.retries` 循环调用 `execute()`（orchestrator.py:963）。每次 `execute()` 创建新 `attempt_id`，`AgentPoolManager.acquire()` 根据 retry policy 决定：

- `same_actor`：复用 lease，重新投递 attempt prompt
- `fresh_actor`：释放旧 lease，重新 acquire
- `restart_actor`：先 daemon `actor_restart`，再投递

### Cancel 桥接

- AF cancel token 触发后 → runner 发送 CCCC cancel request
- 等 actor ack 或 cancel timeout event
- 不默认 kill PTY；只有显式 policy 允许时才 `actor_stop`
- cancel 未确认 → 可见 infra error event

---

## 5. PlanCompiler 设计

**输入**：CCCC plan.yaml + Ralph validation metadata

**输出**：`ExecutionBundle(PipelineSpec + CCCCNodeMeta sidecar)`

### 转换规则

1. 每个 CCCC task → 一个 AF `NodeSpec`
2. `depends_on` 原样映射
3. `agent` = `AgentKind.CCCC`（lazy，不在编译期确定 model）
4. `target.kind` = `cccc_actor`（新增 TargetSpec variant）
5. `capture` = `CaptureMode.TRACE`
6. `retries` = task.retry_policy.max_attempts
7. `verification.checks` **不** 映射为 AF `success_criteria` → 保存在 `CCCCNodeMeta.verification_spec`
8. AF `success_criteria` 只放轻量检查（file exists、output non-empty）
9. `acceptance_criteria`、`critical_flows`、`forbidden_flows` 进入 sidecar

### 示意

```python
NodeSpec(
    id=task.id,
    agent=AgentKind.CCCC,
    prompt=render_base_task_prompt(task),
    depends_on=task.depends_on,
    target=CCCCActorTarget(kind="cccc_actor"),
    capture=CaptureMode.TRACE,
    retries=task.retry_policy.max_attempts,
)
```

### 验证阶段分布

- plan 生成后、AF submit 前：schema、DAG、discipline、forbidden flows 静态检查（Ralph）
- node 完成后：task-level verification gate（CCCC）
- run 完成后：workflow-level validate / final closure（CCCC）

---

## 6. 评价闭环数据流

### 存储结构

AF RunStore 放在 CCCC workspace 下：

```text
.cccc/agentflow_runs/{run_id}/
  events.jsonl
  artifacts/{node_id}/trace.jsonl
  artifacts/{node_id}/result.json

.cccc/performance/
  model_usage.jsonl
  agent_versions/
  evolution_requests/
```

### AttemptLink（trace 索引）

```python
@dataclass(frozen=True)
class AttemptLink:
    run_id: str
    workflow_id: str
    node_id: str
    task_id: str
    attempt_id: str
    actor_id: str
    agent_id: str
    model_key: str
    prompt_version: str
    trace_path: Path
```

### 数据流

```text
CCCCActorRunner emits trace lines via on_output
  → AF Orchestrator writes trace.jsonl
  → CCCC TraceIndexer creates AttemptLink
  → CCCC VerificationGate writes verification result
  → UsageRecorder computes score (model + role + task_type + prompt_version + adapter)
  → ModelPerformanceStore aggregates
  → AF EvolutionRequest(trace_paths={node_id: path})
  → TunedAgentVersion candidate
  → CCCC agent profile candidate (.cccc/agent_profiles/{role}/{version}.yaml)
  → Explicit promotion updates active agent
```

**设计决策**：ModelRegistry 只保存摘要统计。trace/attempt/score 明细放 `.cccc/performance/`。模型能力和 agent prompt 是两类资产，不混存。

---

## 7. 迁移里程碑

| 阶段 | 交付物 | 验收标准 | 依赖 | 估计代码量 |
|---|---|---|---|---|
| **M0** | ExecutionBundle schema、engine config、PlanCompiler 骨架 | legacy 行为不变，plan 可编译 bundle | 无 | 300-500 LOC |
| **M1** | AgentPoolManager.acquire/release 重构 | explicit assignment 不绕过 pool；busy lease 生效 | M0（可部分并行） | 600-900 LOC |
| **M2** | LegacyExecutionEngine 包装 | 现有 E2E 参数化跑 legacy 全部通过 | M0/M1 | 600-1000 LOC |
| **M3** | TraceBridge + AttemptLink + raw/normalized trace | 每次 attempt 有 trace_path，可关联 model/actor/task | M2（可与 M2 并行） | 700-1200 LOC |
| **M4** | AF 源码补丁 + AFExecutionEngine headless path | AF engine 跑同一批 DAG E2E 子集 | M0-M3 | 800-1400 LOC |
| **M5** | CCCCActorRunner PTY actor path | cancel/retry/verification/lease E2E 全部通过 | M4 | 1200-2000 LOC |
| **M6** | 评价闭环 | trace → score → candidate → promotion 全链路可审计 | M3/M5 | 800-1400 LOC |

**总估计：5000-8400 LOC**

### 可并行关系

```text
M0 ─────┬──── M1 ───┐
        │            ├── M2 ──┬── M3 ──┐
        │            │        │        ├── M4 ── M5 ── M6
        └────────────┘        └────────┘
```

### Engine 选择配置

```yaml
# .cccc/config.yaml
execution:
  engine: legacy  # legacy | af
  af:
    run_store: .cccc/agentflow_runs
    concurrency: auto
```

优先级：daemon request > workflow metadata > .cccc/config.yaml > env var > default(legacy)

**回退策略**：不做 silent fallback。AF 不可用 → workflow 创建失败报 `execution_engine_unavailable`。

### E2E 回归策略

- M2：现有 E2E 抽成 engine-parametrized 测试，先只跑 legacy
- M3：增加 trace/attempt/run_id 断言
- M4：同批 E2E 跑 AF headless 子集
- M5：同批 E2E 跑 AF + PTY actor 子集
- 默认 engine 切换前：legacy/AF 核心 workflow 同测通过

---

## 8. AF 源码适配清单

基于 AF 实际源码检查：

| 文件 | 修改类型 | 内容 |
|---|---|---|
| `agentflow/specs.py:24` | Additive | 新增 `AgentKind.CCCC = "cccc"` |
| `agentflow/specs.py:418` | Additive | 新增 `CCCCActorTarget(kind="cccc_actor")` 并加入 `TargetSpec` union |
| `agentflow/prepared.py:35` | Additive | `build_execution_paths()` 增加 `cccc_actor` 分支 |
| `agentflow/agents/registry.py:11` | Additive | 注册 `CCCCAdapter` |
| `agentflow/traces.py:232` | Additive | 新增 `CCCCTraceParser` |
| CCCC 侧 | New | `RunnerRegistry().register("cccc_actor", CCCCActorRunner(...))` |

**关键发现**：
- `AgentKind` 是 `StrEnum`，支持新增值
- `NodeSpec.agent` 是 `AgentKind | str`，但任意 str 会被当成 tuned agent 解析，所以必须正式新增 enum 值
- `RunnerRegistry` 支持动态注册 `kind: str`
- `TargetSpec` 是固定 discriminated union，不支持自定义 target——必须修改
- Trace 由 Orchestrator 从 Runner 的 `on_output` stdout/stderr 解析，需要 `CCCCTraceParser` 约定 JSON line 格式
- Cancel 是 `should_cancel: Callable[[], bool]` 轮询，不是 async hook

所有修改都是 additive，不改变现有 AF 行为。

---

## 9. 架构红线

1. 同一 workflow 不能同时由 legacy dispatcher 和 AF scheduler 启动任务
2. explicit assignment 必须经过 `AgentPoolManager.acquire()`
3. `node_completed` 不能绕过 CCCC VerificationGate
4. AF engine 不可用不能 silent fallback 到 legacy
5. PTY 不可用不能 silent fallback 到 headless
6. Retry 必须产生新 `attempt_id`
7. Cancel 必须有 request → ack/timeout → terminal event
8. Trace parser 失败必须暴露为 trace/error event，不静默吞掉
9. ModelRegistry 不保存完整 trace，只保存摘要统计
10. TunedAgentVersion 只能生成候选；promotion 必须显式

---

## 10. 已知风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| CCCC actor terminal event 协议不够可靠 | CCCCActorRunner 无法稳定等待完成信号 | M5 前固化 task attempt terminal event contract |
| AF Runner API 不传 run_id / attempt number | Runner 需要从 ExecutionPaths 推断 | 后续可给 AF 增加显式 execution context |
| 新增 CCCCActorTarget 触及 AF schema | AF loader/API/UI 可能需要接受新 target kind | 默认 pipeline 不使用 cccc_actor 则不影响 |
| acquire() 等资源会占用 AF concurrency slot | 可能阻塞其他 ready node | AF concurrency 设为 DAG 最大并行度或略高 |
| actor cancel 不是进程 kill | 可能出现 cancel 长尾 | 明确 cancel timeout event，超时后升级处理 |
| AF/CCCC 两套状态的一致性 | AF run state 和 CCCC workflow state 可能漂移 | ExecutionEvent 作为桥接；CCCC ledger 是对外事实源 |

---

## 11. Codex 签署

> Codex 信心评分：4/5
> 保留意见：(1) 不承诺 AF core 零修改，必须接受小范围 additive patch；(2) M5 前必须先固化 CCCC task attempt terminal event contract。
> 状态：**正式同意此方案作为 CCCC × AgentFlow 整合的技术设计**
