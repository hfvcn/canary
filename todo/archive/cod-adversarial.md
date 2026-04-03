• FINDINGS

  - [severity: high] 计划校验和运行时执行没有共享同一条验证命令
    File: todo/问题清单-v5-ralph.md:75, todo/问题清单-v5-ralph.md:181, src/cccc/contracts/v1/ralph_ipc.py:63, src/cccc/daemon/foreman/ralph_service.py:295, src/cccc/daemon/foreman/
    workflow_orchestrator.py:1026
    Confidence: 0.97
    Body: 方案把 Plan.verification.command 当作 v5 新规则的核心检查对象，但当前运行时真正执行的是 TaskRef.verification_command。文档没有定义 plan 到 runtime task ref 的强制投影与一致性
    校验，所以 ralph validate 可以在一条命令上给出“有效”结论，而 daemon 在另一条命令上实际执行。这样核心问题“假验收命令通过校验”并没有被真正关闭，只是从 plan 层转移到了 runtime 契约
    层。
    Recommendation: 收敛为单一真相源。要么让 runtime 直接消费结构化 verification.command，要么在 batch/assignment 生成时做显式投影，并加 round-trip 一致性测试保证两者永不分叉。
  - [severity: high] RV-2 可以被一层 shell wrapper 轻易绕过，P0 目标会落空
    File: todo/ralph-v5-implementation-spec.md:51, todo/ralph-v5-implementation-spec.md:60, todo/ralph-v5-implementation-spec.md:66, src/cccc/daemon/foreman/ralph_service.py:297
    Confidence: 0.93
    Body: 方案只对白名单形状做静态预检；cd ... && pytest ...、bash -lc ...、环境变量前缀、uv run pytest ... 这类现实里很常见的写法都会降级成 hint 或 unknown。与此同时，运行时仍用
    shell=True 原样执行。结果就是，只要把无效验证命令包一层 shell，v5 仍会放行，这和 RV-2 想解决的 failure mode 是同一个。
    Recommendation: 对 unit/integration/e2e 级验证，把 opaque/complex shell 直接视为 error，或者至少支持剥掉一层常见 wrapper 后递归静态检查；否则不要把 RV-2 作为 P0 风险已关闭来宣称。
  - [severity: high] Composition root 继续依赖 plan generator 手工枚举，会复现 v4 的死代码漏 wiring
    File: todo/问题清单-v5-ralph.md:196, todo/ralph-v5-implementation-spec.md:172, todo/ralph-v5-implementation-spec.md:183, src/cccc/ralph/validator.py:351
    Confidence: 0.94
    Body: 文档已经明确承认 v4 的根因之一是没有任务负责 daemon startup wiring，导致“全通过但全是死代码”。但 v5 明确不加 CCCC-specific root rule，而是继续依赖 plan generator 预填
    critical_entrypoints。当前 validator 只能检查“已声明的关键入口是否被 claim”，不能发现“关键入口根本没被声明”。这把最昂贵的遗漏重新交还给最容易遗漏它的组件。
    Recommendation: 把已知 composition roots 变成代码内置默认集、模板强制字段，或显式 schema 必填项；不要继续依赖 planner 记忆去声明它们。
  - [severity: medium] WF-NEW-3 的沉默检测缺少任务级进度信号，MVP 会高噪声甚至不可用
    File: todo/问题清单-v5-ralph.md:230, src/cccc/contracts/v1/ralph_ipc.py:181, src/cccc/contracts/v1/ralph_ipc.py:161, src/cccc/daemon/ralph_ipc_handler.py:448, src/cccc/kernel/
    workflow_state_engine.py:68
    Confidence: 0.89
    Body: 方案说“分配后 N 秒无 ledger 事件就报警”，但当前 TaskEvent 只有 completed/failed 两种终态事件，没有执行中的 progress/heartbeat；ActorStatus 虽然带 current_task_id/
    progress_pct，却只存进 _RALPH_STATE 内存，不进 ledger。这样长任务在完成前天然会表现为“沉默”，而无关状态更新又可能掩盖真实停滞。没有 task-scoped、可持久化的进度信号，这个检测很难既
    低误报又低漏报。
    Recommendation: 先补任务级 progress/heartbeat 事件并持久化，再做 stalled/offline 判定；否则应把 WF-NEW-3 从 v5 主波次拆出。

  VERDICT: needs-attention

  SUMMARY: 当前 v5 方案不适合直接按“问题已闭环”推进。它在 4 个关键点上仍把同一类 failure mode 留在另一条契约或另一层运行时路径里，尤其是 verification 的 plan/runtime 分叉，以及
  composition root 继续依赖人工声明；这会让 validate 变强，但不会让真实闭环同等变硬。结论基于方案文档与当前实现接口对照，未运行测试。

  NEXT STEP: 先把 verification 的 plan/runtime 双契约收敛成单一真相源，再讨论其余规则，否则后面的 P0 校验都建立在可分叉的基础上。