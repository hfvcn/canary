下面是我对这份方案的进一步质疑与改进建议。先给结论：

**这份方案方向对，但还不够“硬”。**
它能提高系统“更可能走对路径”的概率，但还没有把“必须走对路径”变成系统约束。现在最大的风险是：**你们把闭环恢复的责任继续放在 prompt，而不是放在统一入口、状态机和适配层上。**

---

## 一、我最核心的质疑

### 质疑 1：把“改 prompt”当成最高 ROI 没错，但把它当成主解法不够稳

**理由：**

* 你们已经验证过一次，“代码存在 ≠ 默认路径会走到它”。
* 现在的新方案仍然主要靠 P1/P2/P3/P4 改 prompt、help、capability，让 Foreman/Worker“知道该怎么做”。
* 这能修复“不可见性”，但修不了“路径歧义”。Agent 仍然可能：

  * 继续用 `cccc_message_send`
  * 混用 MCP 和 CLI
  * 在 prompt 退化、截断、局部覆盖时再次偏航

**更合适的做法：**
把 prompt 变化保留，但降级为**引导层**，同时新增**强制收敛层**：

1. **完成上报只能有一个 canonical 语义入口**

   * 无论 CLI / MCP / HTTP，最终都调用同一个 `complete_task(...)` 领域接口
   * 不能让“message_send 也像完成”“task complete 也像完成”同时存在

2. **对旧路径做兼容，但不要继续让它成为主路径**

   * 如果 worker 还在用 `cccc_message_send` 发“我做完了”，系统应：

     * 要么拒绝并返回明确错误：“completion must use `cccc task complete`”
     * 要么自动转换为 completion event，但记录 warning/telemetry
   * 不能继续静默吞掉

3. **把“M-1 已解决”改成“M-1 部分缓解”**

   * 只改 prompt，不足以证明“核心工作流不再绑定 MCP”
   * 真正解决 M-1 的标准应该是：**MCP/CLI/HTTP 都落到同一个服务层，或 MCP 被正式降级/废弃**

---

### 质疑 2：W1 和 W2 的边界划分不合理，说明你们对“胶水层”仍然低估

**理由：**

* W1 要验证的是：`task complete -> daemon IPC -> apply_task_event -> verify_completion -> state advance`
* W2 要验证的是：`get_orchestrator(..., project_root)` 能正确创建 `RalphService`
* 但这两个问题都指向同一条运行时链，且都高度依赖 `workflow_orchestrator.py`
* 现在 W1 没有 claim `workflow_orchestrator.py`，W2 才 claim 了它，这意味着：

  * 如果 verify gate 真正的问题出在 orchestrator 内部，W1 没权限修
  * W1/W2 看起来是两个任务，实际上是一条 seam 的两半
  * 你们又在重复“按文件/按模块切开，结果没人负责把链条接通”的老问题

**更合适的做法：**
两种方案选一种：

#### 方案 A：直接合并 W1 + W2

合成一个更诚实的任务：

**W-runtime-wiring**

* claim：

  * `src/cccc/daemon/foreman/workflow_orchestrator.py`
  * `src/cccc/daemon/ralph_ipc_handler.py`
  * `src/cccc/cli/main.py`
  * `src/cccc/cli/workflow_cmds.py`
  * **以及真正承载 `task complete` 的命令文件**（很可能不是 `workflow_cmds.py`）
* 目标：

  * 真实 public path 能创建 orchestrator
  * `task complete` 真能打到 verify gate
  * 状态能推进

这是并行度更低，但责任更完整。

#### 方案 B：保留拆分，但明确主从关系

* W2 改成“初始化与 caller 传参修复”
* W1 显式 `depends_on: ["W2-daemon-init", "P2-worker-prompt"]`
* W1 也必须 claim `workflow_orchestrator.py`

不建议继续靠 `claimed_paths_conflict:batch` 这种**隐式串行**来表达真正的工程依赖。那是调度器知道，执行者不知道。

---

### 质疑 3：W1 可能 claim 错文件，至少是 claim 不全

**理由：**
你要打的是：

`cccc task complete <task_id> --changed-file ...`

但 W1 当前 claim 的是：

* `ralph_ipc_handler.py`
* `workflow_cmds.py`
* `main.py`

这里有两个明显问题：

1. **`task complete` 不像是 `workflow_cmds.py` 的责任**

   * 按命名看，更可能在 `task_cmds.py`、`task_cli.py`、或某个 click/typer 注册文件
   * 如果不是，至少也要确认 command parser/dispatcher 的真实入口

2. **CLI 注册和 handler 经常不在同一文件**

   * `main.py` 可能只是挂载命令组
   * 真正的参数解析、event 构造、daemon 调用可能在别处

**更合适的做法：**
把 W1 的 claimed_paths 从“猜测的实现文件”升级为“按 flow segment 覆盖”：

至少覆盖这四段：

* command registration
* command handler
* daemon IPC bridge
* orchestrator event application

也就是：

* `cli main`
* `task complete command impl`
* `ralph_ipc_handler`
* `workflow_orchestrator`

否则这还是“看起来覆盖了链路，实际上链路中间有一段没人 claim”。

---

### 质疑 4：当前验证命令偏弱，很多只是在验证“文本存在”，不是验证“行为成立”

**理由：**
P1/P2/P3/P4 的验证几乎全是 grep。
这会带来几个问题：

* 注释里出现关键字也能过
* 死代码里的字符串也能过
* prompt source 有词，不代表最终 assembled prompt 里有
* “有 workflow submit”不等于“Foreman 把它当主路径”
* “有 task complete”不等于“Worker completion protocol 已切换”

你们自己已经从第一轮失败里学到：**静态存在不等于运行可达**。现在又在 prompt 层重复这个错误。

**更合适的做法：**

### 对 Wave 1 的验证全部升级成“渲染结果级”的 pytest

#### P1

不要 grep `system_prompt.py`，而要：

* 调 `render_system_prompt()` / public builder
* 断言 Foreman prompt 中：

  * 明确出现 `workflow submit` / `workflow status`
  * 明确将 `cccc_task` 降级为 shared kanban / 非 workflow truth source

#### P2

不要 grep `workflow_orchestrator.py`，而要：

* 构造 worker assignment prompt
* 断言完成动作的第一指令是 `cccc task complete`
* 断言 `cccc_message_send` 只用于进度，不用于 completion

#### P3/P4

不要只检查资源文件里是否有词，而要：

* 断言它们被真正注入最终 prompt
* 且优先级、顺序、措辞符合预期

---

### 质疑 5：W2 的验证方式证明不了真实问题被修掉了

**理由：**
当前 W2 验证：

```python
o = get_orchestrator('ralph-test', project_root=Path('.'))
assert o.ralph is not None
```

这只能证明：

* “如果我手工正确调用一个内部函数，它能构造出来”

但 R-3 的问题不是“构造器坏了”，而是：

* **默认调用路径不传 `project_root`**
* **真实 caller 不会触发 lazy-init**

也就是说，你在验证“内部函数可手动成功”，不是验证“真实入口已不再漏传”。

**更合适的做法：**
W2 应改成验证**公共入口**，而不是验证内部 helper：

### 更强的 W2 验证应至少满足其一：

1. 启动 daemon / workflow operation 的真实入口后，首次操作自动创建 orchestrator
2. 从 CLI `workflow submit/status/assign/complete` 任一真实路径进入时，不需要测试手工传 `project_root`
3. 测试中显式覆盖“caller 未传 project_root 时系统如何补齐”

换句话说，W2 应验证：
**“不靠调用者自觉，系统也能把 Ralph 接上。”**

---

### 质疑 6：M-1 的定义和当前 scope 不一致，导致“完成判定”会失真

**理由：**
你们写的是：

* 待修复：**M-1 核心工作流仍绑定 MCP**
* 本轮 scope：**CLI path only**
* 方案内容：**让 Foreman/Worker 更倾向于 CLI**

这三句话合在一起，意味着一个问题：

> 你们解决的是“默认引导路径”，不是“绑定关系”。

如果 MCP 仍然：

* 被 prompt 暴露
* 能单独改状态
* 不走同一服务层
* 和 CLI 语义不一致

那 M-1 就不能叫“已覆盖”，最多叫“主路径已切换，绑定尚未解除”。

**更合适的做法：**
把 M-1 拆成两个 issue：

* **M-1a：默认操作路径仍由 MCP 主导**

  * 本轮可以解决
  * 通过 prompt/help/capability + E2E 证明 CLI 成为主路径

* **M-1b：MCP/CLI/HTTP 未统一到同一领域服务**

  * 本轮不解决
  * 作为后续架构任务

这样问题陈述会更诚实，验收也不会虚高。

---

## 二、我建议你们新增的两个关键修复，不加的话这轮仍然脆

## 新增任务 A：completion guardrail

**目标：防止 Worker 再次走 `cccc_message_send` 假完成**

### 为什么必须加

因为这是这次事故的真正断点。
如果不加 guardrail，你只是告诉 Worker“请不要这样做”，但没阻止它再次这样做。

### 建议行为

当系统看到：

* 某个 assigned task 对应的 worker 发“done/completed/finished”类消息
* 但没有对应 `task complete`

则系统必须二选一：

1. **严格模式**

   * 拒绝状态推进
   * 自动回复：“Completion must use `cccc task complete <task_id> --changed-file ...`”
   * 记录 warning

2. **兼容模式**

   * 自动将消息转为 completion event
   * 要求可解析出 task_id / changed files
   * 仍记录 warning 和 telemetry

我更推荐 **严格模式默认，兼容模式仅过渡期启用**。

---

## 新增任务 B：统一 workflow service / command adapter

**目标：CLI、MCP、HTTP 都是壳，底层只有一个 workflow domain service**

### 为什么必须加

因为否则你们会永久维护三套语义：

* CLI 一套
* MCP 一套
* HTTP 一套

这正是“看起来都有路，实际上不是一条路”的根源。

### 更合适的结构

统一为：

* `WorkflowService.submit(...)`
* `WorkflowService.complete(...)`
* `WorkflowService.status(...)`
* `WorkflowService.retry(...)`
* `WorkflowService.fail(...)`

然后：

* CLI 调它
* MCP 调它
* HTTP 调它

这样：

* Prompt 可以只引导 CLI
* 但就算以后 agent 走了 MCP/HTTP，系统语义也不会分叉
* E2E 只需要证明“任一入口 -> 同一 service -> 同一状态机”

---

## 三、我会怎么改你们现有 plan

## 1）保留 Wave 1，但把“文本检查”升级成“渲染结果检查”

当前 P1-P4 可以保留，但要改验证方式：

* **P1**：测试 rendered foreman prompt，而不是 grep 源文件
* **P2**：测试 rendered worker assignment prompt，而不是 grep 源文件
* **P3/P4**：测试资源真的被装配到最终 prompt，而不是文件里有字

另外，我建议把 P1/P3/P4 的内容抽成**一个共享 prompt fragment**，避免三处文案再漂移。
否则几轮后又会出现：

* help 写的是一套
* capability yaml 写的是一套
* system prompt 写的是一套

---

## 2）把 W1/W2 改成一条真正对“胶水层”负责的任务

建议变成：

### W-runtime-wiring

claim：

* `workflow_orchestrator.py`
* `ralph_ipc_handler.py`
* `cli/main.py`
* `task complete 的真实命令文件`
* 如有必要，加调用方里负责传 `project_root` 的入口文件

验证：

* 从真实 public entrypoint 发起
* 不手工构造内部对象
* 覆盖：

  * orchestrator lazy-init
  * ralph attached
  * completion event reaches verify gate
  * state advances

这比“W1 验证半条链，W2 验证另一半链”更符合你们这次事故的本质。

---

## 3）W3 现在太弱，必须从“有词”升级为“主路径优先级正确”

当前 W3 的 acceptance：

> confirms 'workflow' appears

这个标准几乎没意义。
应该改成：

* Foreman prompt 中 workflow CLI 被描述为 primary path
* `cccc_task` 被明确降级为 board/kanban/shared visibility，而非 workflow truth
* Worker prompt 中 completion 的 imperative step 是 `cccc task complete`
* 帮助文档 / preamble / capability 文案一致，不互相矛盾

你们这次要修的是**决策引导**，不是**字符串存在性**。

---

## 4）E1 需要加一个“负向 E2E”

当前 E1 只有正向链：

`submit -> assign -> complete -> verify -> done`

这还不够。
必须再补一个反例，否则这轮仍可能把“旧坏路径”漏掉。

### 建议新增 E2E 负向用例

#### E2E-negative-legacy-completion

场景：

* worker 被分配任务
* worker 用 `cccc_message_send` 报告“done”
* 系统应：

  * 不推进为 completed
  * 或自动转换并明确记录 warning
  * 且行为符合你们选定的过渡策略

这个测试价值非常高，因为它直接钉住“上次到底是怎么死的”。

---

## 四、关于并行度，我会怎么判断

你们现在强调最大并行度，但我认为这里应该**牺牲一点并行度，换责任完整性**。

### 现在的问题

表面上是：

* P1/P2/P3/P4 并行
* W1/W2/W3 第二波
* E1 第三波

但实际上：

* P2 和 W2 同文件冲突
* W1 的真实修复也很可能要动同一个 orchestrator 文件
* 所以“第二波并行”未必真实存在

### 我更建议的原则

* **Prompt surface 可以并行**
* **Runtime glue 不要强行并行**
* **Runtime glue 由一个任务或一位 owner 负责到底**

这是你们从“精致死代码”事故里应该吸取的更深层教训。

---

## 五、Ralph 还缺哪些检查规则

你们现在的 Ralph 很强，但仍漏了几类对这次事故很关键的规则。

## 1）缺“验证强度与目标行为匹配”检查

现在 Ralph 允许：

* goal_behavior 写 runtime flow
* verification 却只是 `grep`

这应该至少给 warning。

### 我建议新增规则

**W_VERIFICATION_BEHAVIOR_MISMATCH**

* 如果 goal_behavior / acceptance_criteria 里出现：

  * trigger
  * state advance
  * end-to-end
  * verify gate
  * initialize service
* 但 verification 只是 grep/compile/static existence
* 则告警

---

## 2）缺“问题是否只有 prompt 层修复”检查

对像 R-1 / M-1 这类“默认路径错误”的问题，单靠 prompt 修复风险很高。

### 我建议新增规则

**W_RUNTIME_ISSUE_ONLY_PROMPT_FIXED**

* 如果某个 required_issue 是 runtime/path 类问题
* 但 addresses 它的任务全部是 prompt/docs/resource 类
* 则警告：该问题只被软修复，缺运行时收敛手段

---

## 3）缺“公共入口是否被 claim”检查

你们这次最危险的就是“以为改到了入口，实际上改到的是旁支”。

### 我建议新增规则

**E_FLOW_SEGMENT_UNOWNED**
对 critical flow，要求至少覆盖：

* public entrypoint
* transport/adapter
* domain/state transition
* verification/side-effect

不能只 claim 其中一半。

---

## 4）缺“验证命令存在性/目标存在性”预检查

你们已经踩过一次“命令里引用不存在函数”的坑了。

### 我建议不要追求“完全可执行性检查”，但至少加：

**W_VERIFICATION_TARGET_MISSING**
对常见命令做静态预检：

* `pytest some_file.py` -> 文件是否存在
* `pytest some_file.py -k xxx` -> 文件是否存在，是否至少包含测试名片段
* `grep path` -> path 是否存在
* `python -c 'from x import y'` -> 可静态解析 import path 是否存在（粗粒度即可）

不用 100% 完美，但能挡掉最蠢的假命令。

---

## 5）缺“隐式串行”检查

你们现在靠 `claimed_paths_conflict:batch` 让 W2 串行，这在调度上可以，但在计划表达上不够清晰。

### 我建议新增规则

**W_CONFLICT_USED_AS_DEPENDENCY**

* 如果两个任务反复依赖文件冲突才能保持正确顺序
* 但没有显式 depends_on
* 给 warning：建议将真实工程依赖显式化

---

## 六、关于“只修 CLI，不修 HTTP”，我的判断

**这个 scope 本身是合理的。**
“先打通一条路径，再扩展”是对的。

但我会加一个限定：

> **CLI-only 作为阶段目标合理；把它当成 M-1 的最终解决不合理。**

### 为什么 CLI-only 合理

* 你们当前最急的是恢复一条可靠闭环
* CLI 已有命令、已有验证链、已有 routes，是最短修复路径
* 在系统失真阶段，减少变量比扩大覆盖更重要

### 为什么不能因此宣布 MCP/HTTP 问题解决

* MCP 还在，且曾经就是默认路径
* HTTP 还在，且没有 contract test 保证语义一致
* 如果这些适配层仍然能绕开同一状态机，未来还会再炸

### 所以更诚实的表述应是

* 本轮目标：**建立 CLI 为 canonical path**
* 后续目标：**让 MCP/HTTP 变成 CLI 同源适配层，而不是替代路径**

---

## 七、我建议的更合适版本（最小改法）

如果不大改计划，我建议最少做这 6 个修正：

1. **P1/P2/P3/P4 全部把 grep 改成 pytest 渲染断言**
2. **W1 把 `workflow_orchestrator.py` 和 `task complete` 的真实命令文件纳入 claimed_paths**
3. **W2 改成验证真实 public path，不再手工调内部 helper**
4. **新增一个 completion guardrail 任务**
5. **E1 之外新增一个 legacy-path negative E2E**
6. **把 M-1 拆成 M-1a（主路径）和 M-1b（适配层统一）**

---

## 八、如果让我重排计划，我会改成这样

### Wave 1：统一引导面

* Prompt fragment / help / capability / preamble 同源化
* 渲染结果测试
* 明确 CLI 是 primary，`cccc_task` 是 shared board，不是 workflow truth

### Wave 2：统一运行时入口

* 修 `task complete` 真实入口
* 修 orchestrator lazy-init / project_root 传递
* 加 completion guardrail
* 让 CLI path 真正通到 verify gate

### Wave 3：验证与防回退

* 正向 E2E：submit -> assign -> complete -> verify -> done
* 负向 E2E：message_send “done” 不得形成假完成
* prompt assembly integration test

### Wave 4：适配层收口

* MCP 调同一 service
* HTTP 调同一 service
* contract test 确保三入口同语义

---

## 最后一句判断

这份方案**已经比 v3 更接近正确答案**，但仍带着一点“上次问题是 prompt 不够好”的思维惯性。
我认为更准确的结论应该是：

> **上次的问题不是 prompt 不够好，而是系统允许错误路径长期存在且没有 guardrail。**

所以更合适的解决方式不是“把正确路径讲得更清楚”，而是：

> **把正确路径做成 canonical path，把错误路径变成不可用、可转换或可观测。**

如果你愿意，我可以下一步直接按这个判断，帮你把 `plans/fix-cccc-workflow.yaml` 改写成一个更稳的 v2 版本。
