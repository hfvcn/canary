这份文档抓得最准的地方，是把问题从“代码有没有写出来”转成了“运行闭环有没有真的发生”，并且把三个约束讲清楚了：MCP 不是核心路径，Worker 报完成不等于完成，验证必须是真实运行而不是静态编译。我下面的意见，基本都是在这个判断上继续往前推。

### 先说结论

我认为文档里的总体方向是对的，尤其是这四点应该保留：

1. **把 `verifying` 作为硬门控**，只有 Ralph 验证通过才算 `completed`。
2. **把并行单元从“文件”改成“功能切片”**。
3. **把 HTTP/CLI 设为金路径，MCP 降为兼容层**。
4. **把端到端真实运行当成验收标准，而不是 py_compile / tsc。**

但如果按文档现在的 Phase 直接做，我觉得还会有几处高概率再次出问题。

---

## 我会质疑并改写的地方

### 1）我赞成“统一状态层”，但不赞成再造一份新的事实源

文档的 Phase 0 提出 `WorkflowStateStore + ledger.jsonl` 作为唯一真源。方向对，但实现方式我会质疑。因为文档前面已经明确说 Group 本身就有 append-only ledger；如果 workflow 再单独写一份 `ledger.jsonl`，那不是“唯一真源”，而是**第二套持久化真源**。这样以后一定会出现两个问题：
一是恢复时到底以哪个 ledger 为准；二是状态迁移和审计链条会再次分叉。

**更合适的方法：**
把 `WorkflowStateStore` 做成**投影层/索引层**，不要做成第二套事实源。真正落盘的仍然是 Group 现有 ledger，只是新增 workflow 事件类型，例如：

* `workflow.task_registered`
* `workflow.task_leased`
* `workflow.task_started`
* `workflow.task_reported_completed`
* `workflow.verification_passed`
* `workflow.verification_failed`
* `workflow.retry_requested`

`WorkflowStateStore` 负责的是：

* 从 ledger 重建快照
* 提供按 task/batch 查询
* 缓存当前投影
* 做状态校验

不是负责再写一份并列日志。

---

### 2）我不建议把 `transition(task_id, new_status)` 暴露成通用写接口

文档想用 `WorkflowStateStore.transition()` 作为“唯一写入口”，这个初衷是对的，但**通用状态写接口本身太危险**。因为你们这次已经踩过一次坑：问题不是没有状态层，而是有人绕过正确路径，直接调了不该调的对象。
如果以后所有 handler、orchestrator、Ralph、reporter 都能直接 `transition(...)`，那么“completed 必须经过 verifying”这条规则迟早还会再次被绕过去。

**更合适的方法：**
让 `StateStore` 变成**私有存储层**，对外只暴露**命令式领域接口**，例如：

```python
engine.register_task(...)
engine.approve_batch(...)
engine.lease_task(...)
engine.report_worker_started(...)
engine.report_worker_completion(...)
engine.record_verification_result(...)
engine.retry_after_verification_failure(...)
engine.block_task(...)
```

也就是说，**外部不能直接改状态，只能发业务命令**。
这样“running -> verifying -> completed”这种硬约束才能被集中封装，而不是靠每个调用方自觉遵守。

---

### 3）现有实施规划低估了“生命周期接线”这个最致命的问题

文档把很多力气放在状态统一、验证逻辑、Prompt 接线上，但对真正最致命的问题——**daemon 启动后谁来创建、持有、驱动 workflow runtime**——还不够显式。
R-2 的根因不是“逻辑没写”，而是“**没人活着持有并触发这段逻辑**”。如果没有一个明确的 daemon 级 runtime registry，后面再多状态机和验证器都可能继续是死代码。

**更合适的方法：**
在 Phase 0 前面再加一个 **Phase 0A：运行期接线与诊断**：

* daemon 启动时恢复所有活跃 group 的 workflow runtime
* 对新 group 采用 lazy-init，但要挂在统一 registry 上
* 绑定事件订阅：task event、verification result、batch completion、notification outbox
* 提供一个 `workflow doctor` 或 `/workflow/health` 诊断接口

诊断输出至少应该能回答这几个问题：

* 当前 group 的 orchestrator 是否已实例化
* Ralph 是否已接线
* reporter 是否订阅了 workflow 事件
* 最近一次 batch evaluate 是什么时候
* 当前 snapshot 来自哪个 projection version

一句话：**先证明这些代码真的在跑，再去继续抽象它。**

---

### 4）Phase 2 的验证方案还不够“真实”，而且 `expected_output` 的执行协议没定义清楚

文档 Phase 2 里虽然提出了 `verify_completion()`，但示例逻辑还是偏弱：先 `py_compile` 改过的 `.py` 文件，再跑 `verification_command`，再比 `expected_output`。
这里有两个问题：

第一，`py_compile` 只能算烟雾测试，不能算 build，更不能算验收。它本质上还是文档自己批评过的那种“静态正确但运行闭环断裂”。
第二，`expected_output` 要和“实际输出”比，但**实际输出从哪里取、怎么取、怎么比**，文档没有定义，这会导致实现时每个任务各写各的。

**更合适的方法：**
把 `verification_command` 从一个自由字符串，升级成一个**结构化 verification spec**。至少要有：

* `runner`: shell / http / python / test
* `command` 或 `request`
* `cwd`
* `timeout_sec`
* `env`
* `extract_from`: stdout / file / http_response / json_path
* `compare_mode`: exact / json_subset / schema / regex
* `artifacts`: 日志、响应体、截图、diff

这样 Ralph 不是“执行一个字符串”，而是在执行一个**标准化验证协议**。
另外我会把验证失败分成两类：

* **infra failure**：超时、服务没起来、命令执行异常
* **acceptance failure**：接口返回了，但不符合 `expected_output`

前者可以允许受限自动重试；后者仍然交给 Foreman 决策。这样既不违背“不要自动重试业务失败”，又能减少纯环境抖动带来的人工介入。

---

### 5）`assigned` 和 `running` 这两个状态，现在语义还不够稳

我认可 `verifying` 必须加，但我对 `assigned -> running` 这段持保留态度。因为文档自己已经承认：

* Worker 不可靠地使用 MCP
* unread/read 不能表示已接收
* runtime 行为有差异

在这种前提下，如果没有明确的“启动信号”，那 `running` 很容易变成一个**看起来精细、实际上不可判定**的状态。

**更合适的方法有两个选择：**

* **MVP 方案**：先把 `assigned` 和 `running` 合并成 `in_progress`，先保证闭环能跑通。
* **保留细分方案**：必须明确定义 `running` 的触发条件，比如：

  * 收到 worker heartbeat
  * 首次文件改动被观测到
  * worker 显式调用 `report_started`
  * PTY runner 发出“任务已开始”事件

没有观测协议，就不要假装有精细状态。

---

### 6）T-1 的更好解法，不一定是“修权限”，而是“别让 workflow assignment 走 `cccc_task`”

文档里把 T-1 当成 P0/P1 问题去排查，我认为这件事要分层看。
如果你们已经决定“Context 的 `TaskStatus` 退回项目管理用，不再承载 workflow 执行态”，那么 **Foreman 的任务分配本来就不该再依赖 `cccc_task.assignee`**。
否则你会得到两个平行的赋值系统：一个是项目管理 task，一个是 workflow runtime lease，迟早又会不同步。

**更合适的方法：**

* workflow 层新增明确的 `lease_task / assign_worker` 命令
* `cccc_task` 只作为人类可读的项目管理投影，必要时镜像 assignee
* 权限校验走 workflow command 的统一授权，不走 context 的旧路径

也就是说：
**T-1 可以修，但不要把它当成 workflow 金路径上的必经点。**

---

### 7）`claimed_paths` 只能降低文件冲突，不能解决“并行契约冲突”

文档对 P-1 的判断没问题，但给出的解决方式还是偏“文件系统思维”。
`claimed_paths` 可以减少“两个 worker 同时改一个文件”，但它解决不了更真实的问题：
前后端各改各的，文件没冲突，可是接口契约冲突。
这正是文档里 P-2 暴露出来的问题。

**更合适的方法：**

把“是否允许并行”从“文件是否重叠”提升成“**运行时边界是否共享**”：

* 如果两个切片共享 API / schema / event payload / types，就**不能只看 path**
* 要先有一个共享 contract artifact，才能并行
* 这个 artifact 可以是 OpenAPI、JSON schema、TS types、mock response fixture，形式不限，但必须是显式工件

我的建议是引入一个简单规则：

> **没有共享 contract artifact 的跨边界任务，不允许并行。**

`claimed_paths` 仍然保留，但只是**调度提示**，不是并行安全的唯一依据。
对高风险并行任务，再加一层 worktree 隔离，避免共享工作目录互相覆盖。

---

### 8）Prompt / capability YAML 的迁移不该太早进入主线

文档已经意识到 prompt 链路和 capability YAML 没打通，这个问题确实存在。
但我不建议把“全量切到 capability YAML”放进最小闭环主线里，因为这件事改动面太大，会同时影响 delivery、CLI、默认 preamble、测试快照，**收益不直接对应当前最痛的问题**。当前最痛的是闭环没跑起来，不是 prompt 来源不够优雅。

**更合适的方法：**

* 保留 `render_system_prompt()` 作为稳定入口
* 先让它**增量加载** `task_management` fragment
* 用 feature flag 控制 capability builder
* 先迁 Foreman，再迁 Peer
* 做 prompt snapshot tests，防止角色描述意外漂移

也就是说，**先做“把关键规则注进去”，再做“彻底重构 prompt 体系”**。

---

### 9）R-1 里“补 MCP 工具桥接”不应该再是 P0

这是文档前后有一点张力的地方：前面问题清单里把“补 MCP 工具桥接 Ralph”列成 P0，但后面的需求澄清又明确说了：
**MCP 是可选保留，HTTP + CLI 才是金路径。**
既然如此，再把 MCP bridge 当成 P0，其实会把你们重新带回“优化被替代对象”的老路。

**更合适的方法：**

* 先定义一个 transport-neutral 的 `WorkflowService/WorkflowEngine`
* HTTP、CLI 都调这套内部服务
* MCP 以后如果要保留，就做成薄适配层
* Prompt 里也尽量写“你可以通过 workflow API/CLI 完成这些动作”，不要绑死在 MCP tool 名称上

---

### 10）Phase 7 的开放式 E2E 场景很适合做 benchmark，但不适合当回归门禁

“让 Foreman 自己挑一个中等复杂度前后端项目去实现”这个场景，非常适合做真实评估；但它不适合做**稳定回归门禁**。
原因很简单：它高度依赖模型、提示词、环境、时间窗口，成功标准也有主观成分。把它当成 release gate，会导致你们很难判断失败到底是 workflow 回归，还是 LLM 波动。

**更合适的方法：两层验证**

* **第一层：确定性 smoke test**
  固定 repo、固定任务、固定 expected output、固定 verification spec。
  这个才是 CI gate，应该尽早出现，而不是放在最后。

* **第二层：开放式 benchmark**
  用文档里的那段测试提示词，作为周期性评估或人工验收。
  它产出的“工作流评价报告”很有价值，但不要拿它当唯一通过标准。

---

### 11）Hot reload 和飞书通知都不该留在主干验收路径里

Hot reload 是开发效率功能，不是 workflow 正确性功能；飞书通知是观察者集成，不是主业务闭环。
把这两件事放进核心路径太早，会增加额外不确定性：
状态恢复、重复订阅、重复通知、外部依赖失败，都会让你很难判断到底是哪一层坏了。

**更合适的方法：**

* Hot reload 放到 deterministic E2E 稳定以后
* 通知系统走 outbox，不参与主状态事务
* E2E 测试里先用本地 sink / fake notifier 验证“事件发出了”，不要把飞书连通性当核心验收项

---

## 我建议的重排版实施顺序

我会把文档里的 Phase 重排成下面这样：

### Phase A：运行期接线 + 诊断

先解决“代码是否真的被执行”。
要有 runtime registry、health/doctor、事件订阅、daemon restart 恢复。

### Phase B：统一命令面，不直接暴露状态写口

引入 `WorkflowEngine`，外部只发业务命令，状态存储做私有投影层。
同时修掉 `ralph_ipc_handler -> orchestrator` 的调用路径错误。

### Phase C：验证门控 MVP

实现 `running -> verifying -> completed/failed`，但验证协议必须结构化。
补齐 timeout、artifact、failure taxonomy、decision endpoints。

### Phase D：确定性 smoke command

尽早落一个命令，比如：

```bash
cccc workflow smoke --scenario minimal-two-slice
```

这个命令能：启动 daemon、创建 group、注入固定任务、模拟 worker/或跑真实 worker、完成验证、检查状态流转。
它应该比开放式 benchmark 更早出现，因为它才是防止“又写出一堆死代码”的第一道保险。

### Phase E：并行安全

再做 contract artifact、strict/flexible scope policy、claimed_paths、必要时 worktree 隔离。

### Phase F：HTTP/CLI 稳定化

把金路径做完整，把 `cccc_task` 和 unread_count 从 workflow 控制面里拿出去。
通知系统改成 outbox。

### Phase G：Prompt / capability 迁移

先兼容式接入，再逐步替换，不要反过来。

### Phase H：开放式 benchmark

最后再跑“让 Foreman 自主做一个中等复杂度项目”的评估场景。
这是质量评估，不是最早的门禁。

### Phase I：Hot reload / 飞书等开发与集成功能

放到主闭环稳定以后。

---

## 我还会新增的 5 个硬验收点

这 5 个点，文档里有些已经暗含了，但我建议明确写进每个 Phase 的通过标准：

1. **重复事件幂等**
   同一个 `task_completed` 上报两次，不能触发两次验证、两次通知。

2. **daemon 重启恢复**
   系统在 `verifying` 中间重启，恢复后不能把任务退回 `running` 或丢失验证结果。

3. **越界改动可判定**
   `strict` 切片如果 `changed_files` 超出 `claimed_paths`，不能直接进 `completed`。

4. **验证超时有去向**
   不能卡死在 `verifying`；要进入 `decision_required` 或 `blocked(timeout)`。

5. **无 UI 可自测**
   至少有一个命令能完整验证 workflow 主闭环，不依赖浏览器人工操作。

---

如果只让我挑一个最先做的东西，我会先做 **“workflow doctor + deterministic smoke command”**。
因为它最能防止你们再次进入那种“代码都在、测试都绿、但系统根本没接上线”的假进展。
