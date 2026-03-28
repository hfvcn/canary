**“状态模型分裂 + 契约漂移”**这一共同根因，精准抓住了复杂多智能体（Multi-Agent）系统中各模块协作的痛点。文档中关于 Wave 1 修复数据管线的基本思路是可行的。

然而，在审阅其针对**并发控制、权限模型、状态流转以及前端架构**提出的解决方案（Wave 2 & 3）后，我认为部分设计偏向于“短期打补丁”，在应对**大语言模型（LLM）的不确定性、系统吞吐量上限以及安全性**上存在明显的架构隐患甚至反模式。

以下是对原方案的**5个核心质疑**、**质疑理由**以及我推荐的**更优解决方法**：

---

### 质疑一：多 Agent 并发写控制严重损耗性能且脱离 LLM 实际 (针对 WF-02)

*   **原方案：** 短期引入“全局单写者”（Single Writer，同批次只批准一个可写任务）；中期引入“声明式路径锁”（Claimed Paths，要求 Worker 提前声明修改路径并静态拦截冲突）。
*   **质疑理由：**
    1.  **全局单写者是性能倒退**：直接将多 Agent 系统降维成了单线程串行执行，完全扼杀了分布式并发协作的核心价值。
    2.  **悲观锁不契合 LLM 行为**：LLM 具有“探索性编程”的特征（例如在修改 `Login.tsx` 时发现必须连带重构底层的 `utils.ts`）。如果强制要求其提前精确声明所有变动路径，会导致任务频繁因“越权访问”而中断；如果为了绕过拦截而声明 `["*"]`（全量锁），则锁机制形同虚设。
*   **💡 更合适的解决方法：乐观并发控制 (OCC) + 智能合并兜底**
    放弃悲观文件锁，采用类似人类 Git 协作的模式：
    1.  **无锁并发读写**：Worker 执行时获取文件的 Version/Hash，不阻塞其他 Agent。
    2.  **底层写拦截**：Worker 提交修改调用底层 `write_file` 时，系统校验 Version。如果文件已被其他跑得快的 Worker 修改，**直接拦截写入**。
    3.  **LLM 自动解冲突**：拦截后，将**最新版本的文件内容或 Diff** 返回给该 Worker，并附带 Prompt：“*目标文件已被其他协作者更新，这是最新内容，请基于此重新应用你的修改。*” LLM 极其擅长处理文本 Diff，这种机制能在保证绝对安全的同时，实现系统吞吐量最大化。

### 质疑二：调度身份越权引入 God-Mode 安全漏洞 (针对 WF-05/06)

*   **原方案：** 遇到 Foreman 无法 Reassign / Remove Actor 的权限问题时，让调度操作以 `by="system"` 身份执行，直接绕过权限检查。
*   **质疑理由：**
    这是严重的安全反模式。Foreman 本质上依旧是由 LLM 驱动的智能体。一旦 Foreman 遭遇 **提示词注入攻击（Prompt Injection）**（例如用户在任务描述中恶意写入系统指令）或产生严重幻觉，它就能利用 `system` 这个无所不能的后门身份，无差别删除核心数据、杀死底层守护进程或篡改其他租户的 Actor。
*   **💡 更合适的解决方法：坚持最小权限原则，建立专属 RBAC 角色**
    1.  绝不能用 `system` 绕开鉴权。应在 `kernel/permissions.py` 的权限矩阵中，新增一个系统内置角色：`Role.ORCHESTRATOR`。
    2.  显式赋予该角色严格收敛的权限边界：例如仅允许执行本组内的 `task:reassign`，以及仅允许删除 `状态为 STOPPED` 的 Actor。
    3.  操作记录依然保留 Foreman 的真实身份，实现控制面提权的物理隔离与安全溯源。

### 质疑三：Worker 沉默失败防假死机制极不可靠 (针对 WF-04)

*   **原方案：** 依赖 Worker 上的 LLM 主动调用 `cccc_agent_state` 工具上报心跳（更新 `last_progress_at`），Orchestrator 扫描超时后标为 `stalled`。
*   **质疑理由：**
    将系统监控的命脉交给被监控对象（LLM）是非常脆弱的。当 LLM 陷入逻辑死循环、API 断连或面临复杂的长链推理时，它**恰恰会失去主动调用心跳工具的能力**。此外，一刀切的固定超时极易误杀正在正常“长考”的模型。
*   **💡 更合适的解决方法：底层被动 IO 探针 + 断路器 + 介入式抢救**
    1.  **底层被动探活**：不要指望 LLM 主动 Ping。只要 Daemon 的 Tool Executor 发现该 Worker 正在执行**任何底层动作**（读文件、跑测试），或者 API Client 正在**持续接收流式 Token**，系统就自动在后台刷新活跃时间。
    2.  **逻辑断路器**：如果检测到 LLM 连续 N 次调用同样的工具且获得同样的报错（典型死循环），无视时间直接抛出异常中断。
    3.  **介入式抢救 (Poke)**：超时发生时先不杀进程，而是向 Worker 强行注入一条高优系统 Prompt：“*System: You haven't made progress in X minutes. Are you stuck? Please report status.*” 若依然无响应再行回收。

### 质疑四：Actor 状态控制陷入状态机反模式 (针对 WF-01)

*   **原方案：** 引入 `hold_reason` 字符串字段并持久化到 `group.yaml`。执行 `actor.stop` 时设置 `enabled=false` + `hold_reason="manual_stop"`，守护进程据此跳过唤醒。
*   **质疑理由：**
    `group.yaml` 是声明式配置文件，写入 `manual_stop` 会导致严重的**配置漂移**。同时，用布尔值 `enabled` 加字符串 `hold_reason` 拼凑状态，极易产生二义性（如果人为将配置改回 `enabled=true` 但忘了清空 `hold_reason` 会怎样？）。这混淆了“配置意图”和“运行时瞬态”。
*   **💡 更合适的解决方法：引入 Kubernetes 范式的期望状态模型 (Desired State)**
    1.  彻底分离配置与状态。保持配置文件纯洁，在运行时的 `.state` 库中引入 `desired_state: RUNNING | STOPPED`。
    2.  Foreman 或用户手动执行 Stop 时，仅修改 `desired_state = STOPPED`。
    3.  **状态对齐 (Reconciliation)**：`auto_wake` 守护进程仅做单一职责的比较——如果进程挂了，且 `desired_state == RUNNING`，则拉起；如果 `desired_state == STOPPED`，则完全无视。架构极简，彻底杜绝异常复活。

### 质疑五：前端数据传递违背 React 范式与 API 契约妥协 (针对 KB-BUG-02/03 & BUG-04)

*   **原方案：**
    *   (前端) 从最顶层 `App.tsx` 的全局 Store 中提取 `tasks`，然后通过 Props 一层层透传给 `AppShell`，再传给底层的 `BoardTab`。
    *   (后端) 无活跃工作流时，后端为了迎合前端接口，将所有数值填 `0`，数组填 `[]` 返回完整结构。
*   **质疑理由：**
    *   **Prop Drilling 反模式**：既然已经使用了 Zustand/Redux 等全局 Store，在顶层拦截数据并透传会让本只负责布局的 `AppShell` 强耦合业务数据，引发不必要的重渲染。
    *   **语义混淆**：后端用假数据塞满结构，会导致前端业务逻辑无法区分**“系统健康运行中但当前没任务”**和**“系统根本未启动（Idle）”**这两种截然不同的情况。
*   **💡 更合适的解决方法：状态就近消费 + 强类型契约**
    1.  **前端直连 Store**：彻底取消 `App.tsx` 和 `AppShell` 的传参。让底层的 `BoardTab.tsx` 直接订阅它需要的数据：`const tasks = useWorkspaceStore(state => state.tasks);`。
    2.  **TS 可辨识联合 (Discriminated Unions)**：后端在 Idle 状态只干净地返回 `{ status: 'idle', active: false }`。前端通过联合类型严格约束，如果 `status === 'idle'`，渲染独立的引导 UI（如：“唤醒 Foreman 分配任务”），而不是一个满是 0 的死板看板。

---

### 🚀 总结：调整后的修复实施路径建议 (Revised Plan)

如果推进重构，建议对原波次进行如下架构级对齐：

*   **Wave 1 (管线与前端重构)**：落实 API 结构展平；**拒绝前端 Props 透传**，改为组件内部直连 Store；采用 TS 联合类型重构接口契约，拒绝后端数据造假。
*   **Wave 2 (生命周期与探活)**：引入 `desired_state` 状态机彻底理顺 Actor 启停；落地**底层被动 IO 探针 + 介入式抢救机制**，摒弃 LLM 主动心跳。
*   **Wave 3 (并发与安全加固)**：全面废弃单写者与悲观锁，拥抱 **OCC 乐观并发控制机制**以释放多 Agent 算力；废弃 `by="system"` 后门，引入 `Role.ORCHESTRATOR` 角色完成鉴权闭环。