我先给结论：这份 v5 方案的大方向是对的，尤其是把问题拆成**计划前静态校验、执行中观察、执行后验证**三层，这个架构判断基本成立。
但我有一个核心质疑：现在的 v5 很容易把 Ralph 从“低噪声、可信赖的结构校验器”推成“半语义、半文件系统、半运行时”的大杂烩；如果不先补一层**规则分层与置信度设计**，后面新增的 warning/hint 会很快失去公信力。以下意见都基于你给的 v5 方案文档。

## 一、我最建议先补的，不是某条规则，而是一层“诊断分层”

现在文档里所有新增项基本都只能落到 `error / warning / hint`。这不够。

更合适的做法是给 `ValidationIssue` 再加两类信息：

* `layer`: `structural / workspace / heuristic / runtime`
* `confidence`: `high / medium / low`
* 最好再加 `suggested_fix`

原因很简单：

* `E_COVERS_UNKNOWN_TASK` 这种是**确定性事实**
* `W_UNCLAIMED_TEST_FOR_SOURCE` 这种是**召回型启发式**
* `silent/stalled agent` 是**运行时证据**

这三类东西混在同一层 severity 里，最后就会变成“所有 warning 看起来都一样”，但实际上可信度完全不同。

**我认为更合适的解决方法**是：

1. **确定性规则**继续用 `error/warning`
2. **启发式规则**默认只做 hint 或进入 `review_request`
3. CLI/CI 默认只让 `error + high confidence` 阻塞
4. 所有规则都带 `suggested_fix`

这样 Ralph 才会一直是“可信裁判”，而不是“越来越吵的提醒器”。

---

## 二、我最强烈质疑的一点：RV-2 不能只拿“当前文件系统状态”判死刑

文档里 RV-2 的方向是对的：提前拦截假的 verification command。
但现在的设计有一个很大的潜在误报源：

> Ralph validate 发生在任务执行前，而 verification.command 很可能引用的是**任务将要创建**的文件、测试、类、函数。

比如：

* `pytest tests/test_new_feature.py`
* `python -c "from pkg.mod import NewClass"`

如果 `tests/test_new_feature.py` 或 `NewClass` 本来就是当前任务要新增的内容，那按“当前工作树”去检查，会把**合法计划**误判成 error。

### 我的质疑理由

你们的 RV-2 例子里，`from cccc.daemon.ralph_ipc_handler import RalphIPCHandler` 现在不存在，文档把它当成“假验收命令”示例。
但从机制上说，**静态校验器无法仅靠当前文件系统区分**：

* 这是假的引用
* 还是“即将由当前任务引入的新符号”

### 我认为更合适的做法

把 RV-2 从“当前文件系统检查”改成“**当前文件系统 + 计划写入意图**”联合判断：

* 只有当目标**当前不存在**，且**当前任务或其依赖闭包中也没人 claim 相关路径**时，才报 `E_*`
* 如果目标当前不存在，但**当前任务/上游任务 claim 了对应文件**，那就不要报 error，只能报：

  * hint，或者
  * 放进 `review_request.cannot_validate`

换句话说，RV-2 应该抓的是：

* **不可能成立的验证命令**

而不是：

* **当前尚未成立、但可能被任务创建的验证命令**

这是我觉得最关键的一条修正。

### 顺带再补两点

1. **白名单不够完整**
   现在至少还缺这些高频形状：

   * `pytest -q tests/foo.py`
   * `pytest tests/dir/`
   * `python -m pytest -q tests/foo.py::test_x`
   * 多个 import 但没有执行语义的 `python -c "import a; from b import c"`

2. **不要只靠 `shlex + 形状匹配`**
   更合适的实现方式是做成一组 analyzer：

   * `PyCompileAnalyzer`
   * `PytestAnalyzer`
   * `PythonImportAnalyzer`
   * 未来可扩展 runner wrapper（如 `uv run`, `poetry run`）

另外，`W_VERIFICATION_REDUNDANT_PYCOMPILE` 也建议更严格一点：
只有当自定义 py_compile 的目标集合基本等于任务自己 claim 的 Python 文件时，才算“零增量重复”；如果它编译了更广的范围，最多只能算 hint。

---

## 三、我对 RV-1 的保留意见比较大：它适合做“测试所有权提醒”，不适合做 P0 强 warning

文档把 RV-1 放到 P0，我不太赞同。

### 我的质疑理由

`tests/` 里直接 import 某个源文件，只能说明“测试和它有耦合”，**不能直接推出“这个任务应该 claim 这个测试文件”**。
而 `claimed_paths` 在 Ralph 里还有并行调度含义：它不仅是“谁负责”，还是“谁冲突”。

这会带来两个副作用：

1. **过度 claim 测试文件会降低并行度**
2. 很多测试文件是多个源模块共用的，规则容易把团队推向“为了消 warning 到处 claim tests”

### 我认为更合适的做法

把 RV-1 的语义从“漏 claim 测试”改成“**缺少测试所有权安排**”。

更好的满足条件应该是二选一：

* 该测试文件被某个任务 claim
* 或者存在一个**专门的下游 test-adaptation task** claim 它，并依赖相关源任务

也就是说，Ralph 不应该暗示“源任务自己必须 claim 测试”，而应该允许：

* 源改动任务
* 测试适配任务

分开设计。

### 更细一点的落法

* 默认 severity 我建议从 `warning` 降到 `hint`
* 只有当：

  * 测试文件被当前/下游 verification 明确执行
  * 且全计划里无人 claim 该测试文件
    才升成 `warning`

再进一步，如果你们愿意改 schema，我甚至建议新增一个**不参与调度冲突**的字段，比如：

* `related_test_paths`
* 或 `review_paths`

这样 RV-1 就不会逼着大家把“可能受影响的测试”都塞进 `claimed_paths` 里。

---

## 四、我对 RV-3 的质疑更明显：现在的“虚假覆盖声明”判法太像伪证明

文档里 RV-3 的想法是：

> 如果 A `covers.tasks` 包含 B，但 A 的 `verification.command` 不引用 B 的 claimed_paths，就报 `W_COVERS_CLAIM_UNVERIFIABLE`

这个方向我理解，但**当前证据链太弱**。

### 我的质疑理由

对 integration/e2e 来说，“不直接引用 B 的文件”根本不说明没覆盖到 B。
很多真正有效的集成验证，本来就是通过：

* 入口文件
* 运行时 wiring
* API/IPC
* 上游 contract

间接打到 B。

所以“命令字符串没点名 B 的 path”不能当成强证据。

### 我认为更合适的做法

这条规则不要直接建立在“command 字符串是否触达 B”上，而要建立在**更高层的证据**上：

只要满足下面任一项，就不该报：

* `covers.paths` 与 B 的 `claimed_paths` 有交集
* A 覆盖了某个包含 B 的 `critical_flow`
* A 消费了 B 的 contract
* A 是 integration/e2e，且 B 在其依赖闭包内

反过来说，只有在下面场景我才建议报：

* `verification.level` 只是 `compile/unit`
* A 宣称 covers B
* 又没有 path/flow/contract 级证据

即：
**RV-3 更适合做“低层验证声称跨任务覆盖”的质疑器，而不是“所有 integration/e2e 覆盖都要给你静态证明”的规则。**

我甚至建议它默认进 `review_request`，而不是直接做普通 warning。

---

## 五、`covers.tasks` 的依赖闭包约束，我赞成，而且我认为它应该前移

这一条我反而支持得比较明确。

### 结论

`E_COVERS_UNKNOWN_TASK` 和 `E_COVERS_WITHOUT_DEP_ORDER` 都应该尽早做，而且比 RV-1 更适合前移到 Wave 1。

### 理由

如果一个任务声称“我覆盖了 T5”，但它根本不依赖 T5，调度上就可能在 T5 完成前跑起来。
这不是“语义争议”，这是**模型自相矛盾**。

### 我对“会不会过严”的看法

在现有语义下，我认为**不会过严**。
如果真的有“我想把某任务列为审查关注对象，但它不在我的依赖链里”的合理场景，那说明你们需要的不是放松 `covers.tasks`，而是新增一个更软的字段，比如：

* `focus_tasks`
* `related_tasks`

也就是说：

* `covers.tasks` = 有调度/验证语义的强声明
* `focus_tasks` = 给审查器看的弱关联

不要把一个字段同时拿来做这两件事。

---

## 六、我不赞同用 `len(tasks) >= 5` 作为早期 checkpoint 的核心门槛

### 我的质疑理由

`len(tasks)` 不是复杂度，最多只是规模。
它会漏掉一个很危险的场景：

* 4 个任务串成一条深链
* 只有最后一个 sink 做 integration

这其实比“6 个宽而浅的 fan-in 任务 + 一个最终集成”更危险，但按现在规则反而可能不报。

### 我认为更合适的做法

把触发条件改成**图深度**，不要用任务总数做代理变量。

更合理的版本可以是：

* 计算 DAG 最长路径 `L`
* 找最早 cross-task verifier 的深度 `d_min`
* 只有当：

  * 所有 cross-task verifier 都是 sink
  * 且 `d_min` 已经落在最长路径的后半段
    才报 `W_NO_EARLY_INTEGRATION_CHECKPOINT`

简单说就是：

> 不是“任务多不多”，而是“首次跨任务汇合验证是不是来得太晚”。

这个标准比 `len(tasks) >= 5` 更贴近真实风险。

---

## 七、运行时 silent/stalled 检测，光看“有没有 ledger 事件”还不够

这一条方向对，但最小方案我觉得还可以再往前走半步。

### 我的质疑理由

“分配后 N 秒无 ledger 事件”太粗了，因为：

* agent 可能在认真读代码，但还没发事件
* 也可能产生了**无关事件**
* 甚至可能 actor 活着，但当前 task 根本没开始

### 更合适的最小方案

不需要解析 agent 输出，但我建议至少补一个极小的任务事件契约：

* `task_assigned`
* `task_started`
* `task_progress`（可选）
* `task_completed / task_failed`

然后结合现有 `ActorStatus.updated_at`，把问题拆成三类：

1. **actor offline**：heartbeat stale
2. **task silent**：assignment 后迟迟没有 `task_started`
3. **task stalled**：started 之后 actor 还活着，但 task 长时间无进展

这样比“只看 ledger 上有没有东西”更可解释，也更不容易误报。

---

## 八、我赞成 `filesystem_validator` 分层，但我质疑“默认 project_root=plan 所在目录”

分层本身是对的。
不过这里还有两个实现细节，我觉得比“拆不拆文件”更重要。

### 1）`project_root` 默认值不够稳

如果 plan 存在：

* `.cccc/plans/plan.yaml`
* `tmp/plan.yaml`
* 或外部生成目录

那“plan 所在目录”可能根本不是 repo root。

### 更合适的解析顺序

我建议：

1. CLI 显式 `--project-root`
2. 配置文件
3. git root
4. 最后才 fallback 到 plan 所在目录

而且 CLI 输出里最好明确打印：

* 当前使用的 `project_root`
* workspace 校验是否真的启用

### 2）不要把 `filesystem_validator.py` 做成一个新巨石模块

你们 Wave 1 之后就已经有一堆 workspace 规则了。
更合适的结构是：

* `WorkspaceIndex`：缓存 AST、module map、pytest node map、path exists
* 多个小规则函数复用这个 index

否则 RV-1、RV-2、后续规则会反复扫盘、反复 parse AST。

---

## 九、我会调整 Wave 顺序

如果是我排期，我会这样改：

### 我建议的 Wave 1

先做**确定性、低噪声、收益高**的：

* RV-2，但改成“当前工作树 + 计划意图”联合判断
* `E_COVERS_UNKNOWN_TASK`
* `E_COVERS_WITHOUT_DEP_ORDER`
* `W_VERIFICATION_REDUNDANT_PYCOMPILE`
* 最小版 role rules（很值得提前）

这里我会把 RV-1 从 P0 拿下来。

### 我建议加一个 Wave 1.5

把 `review_request` 的极简版提前，不要等 Wave 4。

因为你们已经证明了 Ralph + Codex 的互补性。
那就应该尽早给 Ralph 一个正式出口，把这些“我怀疑但我没法证明”的东西输出给审查器：

* `W_VERIFICATION_SHAPE_UNKNOWN`
* `W_DYNAMIC_TEST_IMPORT_OPAQUE`
* RV-3 这类低置信度覆盖质疑
* “目标当前不存在但可能由任务创建”的 verification target

这比继续往 validate 输出里塞 warning 更健康。

### 我建议的 Wave 2

* 运行时 `task_started + heartbeat + stalled` 检测
* revised 版早期 checkpoint
* RV-4 降级逻辑
* 最小 role-based rules

### 我建议的 Wave 3

* RV-1
* RV-3
* RO-1 的轻量版：flow touchpoints / bridge evidence

### 我建议继续后移

* RV-5 语义依赖推断

这个方向我会非常谨慎。
它很容易从“帮助审查”滑向“关键词碰瓷”。
在没有 `review_request`、没有规则精度数据之前，我不建议把它推进 Ralph core。

---

## 十、对文末 7 个审查问题，我的直接回答

1. **RV-2 白名单完备性**
   还不够。至少补：pytest 选项、目录目标、`python -m pytest` 变体、多 import 但无执行语义的 `python -c`。但更重要的不是补命令清单，而是做成可扩展 analyzer。

2. **RV-1 scope 是否太窄**
   作为召回型 hint，不算太窄；作为强 warning 或 P0 规则，就偏窄且偏粗暴。

3. **`covers.tasks` 传递闭包规则会不会过严**
   在当前语义下不会过严，我赞成做 hard error。若有更松的需求，应新增软字段，不要污染 `covers.tasks`。

4. **早期 checkpoint 规则是否合理**
   方向对，但 `len(tasks) >= 5` 不合理。应改为基于 DAG 最长路径和最早 cross-task verifier 深度。

5. **`filesystem_validator` 分层是否正确**
   正确，但真正关键的是：

   * project_root 解析策略
   * WorkspaceIndex 缓存
   * 规则不要只看“当前文件系统”，要看“当前 + 计划意图”

6. **Wave 排序是否合适**
   我会把 `covers.tasks` 两条 error 和 review_request-lite 前移，把 RV-1 后移。

7. **不做清单是否有误排除**
   大体合理。
   但我会把 `review_request` 的轻量版提早；相反，RV-5 我会更晚做。

---

一句话总结：
**v5 最值得做的，不是继续堆更多 heuristic，而是把确定性规则做硬、把启发式规则降噪、把无法静态证明的风险显式交给 review_request 和运行时证据。**
这样 Ralph 会越来越可信；否则它会越来越“聪明”，但也越来越不被人信。
