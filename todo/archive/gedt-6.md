**VERDICT**: `needs-attention`

**SUMMARY**: The proposed v5 optimization path correctly identifies the system's architectural drift, but the execution plan introduces severe deployment deadlocks and state corruption risks. By mandating that strict runtime monitors (Phase 1) actively block behaviors that aren't actually fixed until Phase 4, the plan guarantees a complete system outage. Furthermore, its rollback strategy ignores persistent state schemas, its asynchronous safety rails fail to handle partial DAG execution, and it lacks concurrency controls for new IPC messages.

**FINDINGS**:

**[severity: critical] Sequencing deadlock guarantees system outage in Phases 1-3**
- File: `六、分阶段方案`, Phase 1 (P1-B) vs Phase 4 (P4-A/B)
- Confidence: 1.0
- Body: The rollout plan mandates serial execution where Phase 1 deploys a runtime monitor that actively blocks execution ("违规时阻断") on 5 invariants. However, the system's ability to comply with these invariants is not built until later phases. For example, `ASSIGNMENT_PERSISTED` (banning shadow state) and `NO_AUTO_DISPATCH` are enforced in Phase 1, but the `_active_workflows` shadow state (ARCH-4) and auto-dispatch logic (ARCH-3) are not removed/fixed until Phase 4. Deploying a blocking monitor against a system that fundamentally requires these drift behaviors to function will instantly paralyze all workflows during the interim phases.
- Recommendation: Decouple monitor *deployment* from monitor *enforcement*. Phase 1 must deploy monitors in an "Audit/Log-Only" mode. Active blocking (`阻断`) for a specific invariant must only be toggled ON atomically with, or strictly after, the phase that introduces its underlying architectural fix.

**[severity: high] Irreversible state corruption on Phase 4 code-only rollback**
- File: `六、分阶段方案`, Phase 4 (P4-B Schema 迁移 & 回滚检查点)
- Confidence: 0.95
- Body: Phase 4 mandates a persistent schema migration for the JSON workflow state (extending `TaskState` and dropping `_active_workflows`). The defined rollback mechanism across all phases is strictly code-based (`git tag pre-phase4`). If a rollback is executed after in-flight workflows have transitioned to the new schema, reverting the codebase will not revert the mutated JSON state files on disk. The `pre-phase4` code will crash when attempting to load the newer v2 schema, and the required `_active_workflows` state will be permanently lost, resulting in unrecoverable data corruption for all active workflows.
- Recommendation: The Phase 4 rollback plan must mandate an explicit persistent state backup (e.g., creating a hard snapshot of the Engine's JSON state directory) prior to deployment. The rollback checklist must enforce restoring this data alongside the `git checkout`.

**[severity: high] Option Z 'BLOCKED' state creates unrecoverable partial DAG execution**
- File: `六、分阶段方案`, Phase 2 (P2-C / Option Z 混合方案)
- Confidence: 0.90
- Body: Under Option Z, if Foreman fails to provide a valid agent within N minutes or 2 retries, the task transitions to a terminal `BLOCKED` state. However, workflows execute as a DAG with parallel tasks. If Task A becomes `BLOCKED`, sibling Task B might still be executing, actively mutating the repository. The document defines no workflow-level cascade behavior. Without it, parallel tasks will continue to run, but the overarching workflow will permanently hang in an unfinished state, wasting resources and leaving a torn, non-idempotent repository state.
- Recommendation: Define explicit partial failure semantics. When any task reaches the `BLOCKED` terminal state, the Orchestrator must transition the overall Workflow to a `SUSPENDED` or `FAILED` state and immediately issue explicit cancellation signals to halt all currently executing parallel sibling tasks.

**[severity: medium] Asynchronous IPC race conditions in DAG unlocking**
- File: `六、分阶段方案`, Phase 4 (P4-A)
- Confidence: 0.85
- Body: P4-A changes the orchestrator to send an asynchronous `TasksReadyForAssignment` IPC message to the Foreman AI when downstream tasks unlock. In a parallel execution environment, multiple tasks can complete concurrently. Without explicit debouncing at the Orchestrator level, the system will evaluate the DAG multiple times in rapid succession, firing overlapping and duplicate `TasksReadyForAssignment` events. The Foreman AI will process these disjointed events concurrently, likely issuing conflicting `workflow submit` commands and clobbering task assignments.
- Recommendation: Introduce a debounce window in the Orchestrator to batch concurrently unlocked tasks into a single `TasksReadyForAssignment` IPC event. Additionally, inject an optimistic concurrency token (e.g., a DAG state `version`) into the payload, which the Foreman must return to prevent stale assignments.

**[severity: medium] Event listener enforcement risks torn engine state**
- File: `六、分阶段方案`, Phase 1 (P1-B)
- Confidence: 0.85
- Body: P1-B specifies adding the monitor "作为事件监听器接入 WorkflowOrchestrator" (as an event listener) to block violations. Event streams are inherently reactive and typically fire *as* or *after* state transitions are committed. If the orchestrator commits a forbidden state to the Engine or spawns an unapproved worker process, and the monitor "blocks" it by throwing an exception in the event listener pipeline, the underlying state has already been dirtied. The workflow will enter a torn state (e.g., Engine mutated, but downstream execution crashed).
- Recommendation: The monitor must be implemented as a synchronous pre-execution interceptor (Gatekeeper) that validates the state transition payload *before* any side-effects occur or Engine writes are persisted.

**NEXT STEPS**:
- Convert Phase 1's rollout instructions from immediate blocking to an "Audit/Warn-Only Mode" until corresponding architectural fixes are deployed.
- Amend the Phase 4 rollback mechanism to require physical/data-level state snapshots.
- Define explicit cancellation routing for Option Z when partial batch failures hit the safety rails.
- Add concurrency control mechanisms (versioning/debouncing) to the IPC contract changes for Phase 4.
- Redesign the Phase 1 monitor as a pre-execution interceptor rather than a reactive event listener.