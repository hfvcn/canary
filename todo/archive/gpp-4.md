这份方案的大方向是对的：你们已经从“继续修 Ralph 后端本体”转向“修默认入口和可达路径”，这是比 v3 更接近根因的判断。

但如果让我做外部审查，我不会把它当成“可以直接执行的最终版”。我会指出一个更核心的问题：

**你们现在修的是“CLI 被看见”，但真正该修的是“谁有权改变工作流状态”。**

也就是说，`CLI 成为主路径` 是一个战术目标；`daemon 内部只有一个权威状态迁移入口` 才是结构性解法。否则这轮你们修好 CLI，下轮 HTTP/MCP/消息旁路还会以别的形式复发。

---

## 我会重点质疑的 8 个点

### 1) 把“提示词可见”当成“功能可达”，仍然偏表层

你们现在对 R-1 / M-1 的修复，主要落在：

* system prompt
* capability YAML
* help/preamble
* worker prompt

这能提高模型走 CLI 的概率，但**不能保证 workflow 成为唯一真相源**。只要 `cccc_task` 或 `cccc_message_send` 还能走另一条能改变状态的路径，系统仍然是双控制面。

### 我认为更合适的解法

不要把“CLI 成为主路径”当成架构边界，而应当把它当成**一个 adapter**。

更稳的结构应该是：

* daemon 内部有且只有一个权威接口，比如 `complete_task(...)`
* `cccc task complete` 调它
* HTTP route 调它
* MCP `cccc_task` 如果还保留，也只能调它，或者直接变成只读/报错
* `cccc_message_send` 明确不能触发状态迁移

一句话概括：

**CLI-only 作为验收路径是合理的；CLI-only 作为核心设计边界并不合理。**

---

### 2) W2 现在验证的是 helper，不是生产链路

W2 的验收是：

> `get_orchestrator('test', project_root=Path('.'))` 返回的 orchestrator 有 ralph 属性

这个测试能证明的，只是：

* `get_orchestrator()` 这个 helper 在手工喂参数时能 new 出对象
* `WorkflowOrchestrator.__init__()` 里确实会挂 `ralph`

它**不能证明**下面这些真实问题被修好了：

* 实际 CLI / IPC / daemon cold start 路径会不会调用到这里
* 真实 group/session 上下文里 `project_root` 有没有被正确保存
* verify 命令是不是在正确的项目目录执行
* “调用方不传 `project_root`”这个根因是否真的消失了

### 我认为更合适的解法

与其要求“所有调用方都记得传 `project_root`”，不如直接改设计：

* 在 `workflow submit` 或 group 初始化时，一次性把 `project_root` 注册到 daemon/group context
* `get_orchestrator(group_id)` 只吃 `group_id`
* orchestrator 自己从权威上下文里解析 `project_root`
* 最好在 group 创建时就 eager-init，而不是继续靠 lazy-init 藏着

也就是说，**`project_root` 不该是到处手传的业务参数，而应是 group 的元数据。**

### W2 应该怎么测

我会把 W2 改成一个真正的 integration test：

1. 启一个 fresh daemon
2. 在 `tmp_path` 下造一个最小项目
3. 用真实 CLI / IPC 提交 workflow
4. 再走一次真实 `task complete`
5. 断言：

   * orchestrator 是在 cold-start 路径里被创建的
   * `ralph` 已初始化
   * verify 的 cwd 就是那个 `tmp_path`

这才是在验证“生产链路可达”。

---

### 3) R-2 现在仍然缺一条“反向证明”：旧旁路被封死了没有

W1 的目标是让：

`task complete -> verify gate -> state advance`

这条正向链条可达。

但 R-2 的真正风险不只在于“正向链条没接上”，还在于：

> **旧旁路是否仍然能把任务变成完成态。**

比如：

* `cccc_message_send "done"` 会不会仍被 Foreman / daemon 某处解释成完成
* `cccc_task` 的某些写操作会不会仍能绕开 verify
* 人工状态推进会不会跳过 verifying

如果这些没被封死，R-2 实际上只是“新增了一条正确路径”，不是“移除了错误路径”。

### 我认为更合适的解法

把“任务完成”定义成**受保护的状态迁移**：

* 只有 `complete_task()` / `TaskCompletionRequested` 事件可以把 task 推进到 `verifying`
* 消息系统只做通信，不做状态推进
* MCP 只能委托给同一权威接口，不能自带状态机
* 保留 transition history / audit trail，测试里要断言真的经过 `verifying`

### 必须补的测试

至少要有三类：

1. **pass 分支**：`assigned -> verifying -> completed`
2. **fail 分支**：`assigned -> verifying -> failed/retryable`
3. **anti-bypass 分支**：发送 `cccc_message_send "done"`，状态不变

没有第 3 条，我不会认为 R-2 真的关掉了。

---

### 4) P1 / P3 / P4 三处同时改 prompt，漂移风险很高

现在你们把 workflow 指导分散在：

* `system_prompt.py`
* `task_management.yaml`
* `cccc-help.md`
* `prompt_files.py`

这有两个问题：

第一，**它们可能不是同等“活着”的 prompt 源**。
你们已经吃过一次“精致的死代码”的亏，这次很可能再写出“精致的死提示”。

第二，**它们会逐渐漂移**。
尤其你们现在自己文档里就已经不完全一致了：

* P3 只强调 `submit/status`
* P4 才强调 `verify/retry/fail`
* W3 的标题写“all roles”，但依赖里又不包含 P2

这说明 prompt 面其实还没有真正统一。

### 我认为更合适的解法

先加一个新任务，不是改文案，而是做：

**P0-prompt-reachability / prompt source map**

它要回答两个问题：

1. 最终 Foreman prompt 到底由哪些源拼出来
2. Worker assignment prompt 到底由哪些源拼出来

只有确认某段内容确实进入最终 assembled prompt，改它才有意义。

然后我会把 P1/P3/P4 改成：

* 新建一个**单一 canonical workflow guidance fragment**
* system prompt / capability / help / preamble 都从这个 fragment 生成或 include
* 不再手工四处写类似但不完全一样的说明

这样做会牺牲一点“并行改 4 个文件”的表面速度，但换来更高的一致性和更低的回归率。我认为这个取舍是值得的。

---

### 5) 现有 verification 太弱，很多是“文案存在性测试”，不是行为测试

例如：

* P1/P2/P3/P4 基本都是 `grep`
* W2 是 inline python 手调 helper
* W1 用 `pytest -k verify`，测试选择器过于模糊
* W3 的验收是“确认 workflow appears”，这太弱了

这些测试很容易出现“文件里有词，但真实行为没变”的假阳性。

### 我认为更合适的解法

#### 对 prompt 类任务

不要 `grep` 源文件，要测**渲染结果**：

* Foreman: render 出最终 prompt，断言包含明确命令和优先级
* Worker: render 出 assignment prompt，断言包含精确 completion recipe
* 还要断言 `cccc_task` 被降级为看板/展示，而不是 workflow 真相源

#### 对 runtime 类任务

不要只看最终 completed，要断言**中间状态和调用证据**：

* 经过 `verifying`
* verify handler 被调用一次
* 失败时走失败分支

#### 对 test command 本身

我建议 Ralph 不要长期接受自由文本 shell string 作为唯一 verification 描述。更合理的是改成**结构化 verification spec**，例如：

* `kind: pytest`
* `target: tests/integration/test_task_complete_verify.py::test_pass`
* `kind: python`
* `module: ...`
* `expr: ...`

这样 Ralph 才有可能做 preflight：

* 文件是否存在
* pytest 能否 collect
* python import 是否存在

否则 `valid=true` 的含义会被高估。

---

### 6) 当前 Wave 结构并没有真正实现“最大并行度”

现在表面上是：

* P1/P2/P3/P4 并行
* W2 因为和 P2 同文件冲突而自动串行

但这其实暴露了另一个设计问题：

> **prompt 文案和 runtime 逻辑被塞在同一文件里了。**

结果是：

* P2 只是改 worker prompt，却占住了 `workflow_orchestrator.py`
* W2 要修运行时 wiring，也必须抢同一个文件
* 并行度其实是被文件布局，而不是被真实依赖限制住的

### 我认为更合适的解法

把 worker prompt 模板从 `workflow_orchestrator.py` 抽到资源文件或模板文件里，让代码只负责填充变量。

这样：

* P2 改 prompt 模板
* W2 改 orchestrator / init / context wiring
* 两者就能真正并行

所以我会说：
**当前计划不是依赖设计得不够好，而是代码分层还不够好。**

---

### 7) M-1 目前只修了一半：修了“默认路径”，没修“替代路径”

你们现在把 M-1 定义成：

> 核心工作流仍绑定 MCP

但实际上它至少应拆成两个子问题：

* **M-1a**：prompt 默认引导 MCP，而不是 workflow CLI
* **M-1b**：MCP 仍然拥有 workflow 状态变更能力

现计划主要修的是 M-1a。
如果 M-1b 还存在，那系统只是从“模型常走 MCP”变成“模型通常走 CLI，但 MCP 仍能改状态”。

### 我认为更合适的解法

不要一上来物理删除 MCP，那样风险太高。更稳的是：

第一步：

* `cccc_task` 的 workflow-mutating 能力全部改成委托给统一 backend API
* 或者直接报 deprecation error

第二步：

* 只保留 kanban / read-only / display 类功能

第三步：

* 等一轮稳定后再物理移除

这比“prompt 上去掉 MCP”更像真正解决 M-1。

---

### 8) CLI-only 的 scope 可以接受，但要满足两个前提

我不反对这轮只做 CLI。
从“先跑通一条完整路径”的原则看，这是合理的。

但它成立有两个前提：

1. **HTTP/MCP 当前不是生产上的活跃状态写路径**
2. 即使它们还在，也必须：

   * 要么只读
   * 要么委托给同一个 backend transition API

如果这两个前提不成立，那“这轮不管 HTTP”会留下 split-brain。

### 我的判断

* **作为验收范围，CLI-only 合理**
* **作为架构边界，CLI-only 不够**

---

## 我会怎么重排这份计划

我不会按现有波次原样执行，我会改成下面这种结构。

### Wave A：先修 authority，不先修文案

1. **A1-state-transition-authority**

   * 引入唯一 `complete_task()` / `TaskCompletionRequested`
   * 只有它能推进到 `verifying`
   * `message_send` 不能改状态
   * MCP mutating path 要么委托，要么禁用

2. **A2-project-context-authority**

   * `project_root` 在 group/workflow submit 时注册
   * `get_orchestrator(group_id)` 不再要求业务侧到处传 root
   * cold-start path 真正可达

这两个任务做完，系统才真正“不会再错”。

### Wave B：再修 prompt surface，而且只保留一个真来源

3. **B1-prompt-reachability-map**

   * 确认哪些 prompt 片段真的进入最终 Foreman/Worker prompt

4. **B2-canonical-workflow-guidance**

   * 抽一个统一 guidance fragment
   * system prompt / capability / preamble / help 从它生成

5. **B3-worker-completion-recipe**

   * Worker prompt 给出 copy-paste 级别的完成步骤
   * 最好包含 `--json`
   * 最好给出 task_id / changed files 示例

### Wave C：最后做验证，不只测 happy path

6. **C1-integration-pass-and-fail**

   * `task complete` 成功和失败两支都测

7. **C2-no-bypass**

   * `message_send` 不会完成任务
   * MCP mutating path 不会绕过 verify

8. **C3-cold-start-e2e**

   * fresh daemon + temp repo + real CLI
   * `submit -> assign -> complete -> verifying -> done/fail`

---

## 我认为最该补的验证断言

如果你们不想大改计划，至少把下面这些断言补进去：

### 对 W1

不要只断言最后 done，要断言：

* event history 里出现 `verifying`
* verify handler 被调用
* fail 分支也存在
* `message_send` 不会触发状态变化

### 对 W2

不要直接调 helper，要断言：

* fresh path 下 orchestrator 被创建
* `project_root` 来自 group/workflow 上下文，不是测试代码硬塞进去
* verify 在正确 cwd 运行

### 对 W3

不要只查 `workflow` 字样，要断言：

* Foreman prompt 有 `workflow submit/status/retry/fail`
* Worker prompt 有 `task complete`
* `cccc_task` 被明确降级
* 关键 workflow 指导位于不会被截断的 prompt 前缀，而不是帮助文档尾部

### 对 E1

最好拆成两个测试：

* `test_workflow_e2e_verify_pass`
* `test_workflow_e2e_verify_fail`

这样比一个“大而全”测试更稳，也更利于定位。

---

## 对 Ralph 本身，我会补这几条规则

### 1) `valid` 应区分“结构合法”和“语义可信”

现在的 `valid=true` 容易让人误读成“计划靠谱”。
更合适的是输出：

* `structurally_valid: true`
* `semantic_risks: [...]`

### 2) 增加 `acceptance ↔ verification` 一致性检查

比如 acceptance 写“rendered prompt contains...”，verification 却只是 `grep` 源文件，这应该至少给 warning。

### 3) 增加 verification preflight

尤其对 pytest：

* 文件存在
* test target 可 collect

对 python：

* import target 存在

### 4) 增加 `forbidden_flows`

你们现在只有 positive flow，没有 negative flow。
建议支持这种声明：

* `message_send_must_not_complete_task`
* `mcp_must_not_bypass_verify`

这类问题只靠 positive flow 覆盖是不够的。

### 5) 为 required issues 增加“最低验证等级”

例如：

* R-2 至少要有 e2e
* R-3 至少要有 integration
* M-1 不能只靠 unit prompt grep 覆盖

### 6) role-based rules 该启用了

既然 `role` 已经存在，就别只当装饰：

* `leaf` 不应成为 critical flow 的唯一验证者
* `integration` 至少覆盖 2 个任务/边界
* `verification` 任务如果改 prod code，要 warning

### 7) `suggest` 不该继续用单遍贪心

如果 ready task 数量通常只有十几个到几十个，完全可以在 ready set 上做：

* 最大独立集 / 最大基数 batch
* 同时用 “能解锁多少下游任务” 做 tie-break

这会比现在的顺序贪心更符合“最大并行度”。

---

## 我最怀疑遗漏的 claimed_paths

没有代码库我不能下结论，但我会优先怀疑这几类文件被漏 claim 了：

* `cccc task complete` 的**真实 handler/parser 文件**
  它未必在 `workflow_cmds.py`
* group/session/context 持久化文件
  真正决定 `project_root` 从哪里来
* prompt loader / assembler / cache 文件
  决定 P3/P4 到底是不是“活提示”
* MCP `cccc_task` / `cccc_message_send` 的 handler
  决定旧旁路是否还活着
* verify service / state transition enum / event model 文件
  决定 verify gate 是否只是“被调用”，还是“真的推进状态”

换句话说，**当前 critical_entrypoints 更像是“端点列表”，还不是“胶水层列表”。**

---

## 最后给一个明确结论

我的结论不是“这方案错了”，而是：

**方向对，但当前版本仍然偏“入口修复”，还没上升到“权威边界修复”。**

我最建议你们立刻补的，不是更多文案，而是这四件事：

1. **把任务完成收口到唯一 backend transition API**
2. **把 `project_root` 从“调用方参数”提升为“group 权威上下文”**
3. **加入 anti-bypass 测试，证明旧旁路死了**
4. **把 prompt 指导收敛到一个 canonical source，而不是四处改文案**

如果这四件事补上，这份计划就会从“高质量修补”升级成“真正不容易复发的修复”。

如果你愿意，我下一条可以直接按这个思路，把 `plans/fix-cccc-workflow.yaml` 重写成一个更稳的 v2 版本。
