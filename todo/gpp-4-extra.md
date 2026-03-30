结论先说：

**Ralph 这轮不需要“先停下来重构”才能继续执行计划。**
就你贴出来的这份 plan 而言，Ralph 现在已经够资格做两件事：**计划体检** 和 **保守调度**。
但它还不够资格被当成“全自动最优调度器”。所以答案是：

* **要不要改 Ralph？要，但不是阻塞当前计划的那种改。**
* **当前并行化方案是否合理？总体合理，而且偏安全优先；但不要把它理解成严格的三波次流水线。**

---

## 一、Ralph 现在要不要改

### 不需要立刻改的部分

我**不建议**为了追求更多并行度，去放宽 Ralph 现在的 `claimed_paths_conflict` 规则。

你这次的历史教训恰恰说明，当前最怕的不是“少并行一点”，而是“又并行出一堆精致死代码”。
所以 **同文件写冲突直接串行** 这个策略现在是对的，尤其是 `workflow_orchestrator.py` 这种核心胶水文件。

也就是说：

* **P2 和 W2 不能并行，不是 Ralph 太保守，而是计划本身把 prompt 和 runtime glue 放进了同一个文件。**
* 真要提升并行度，优先应该是**拆文件/拆模板**，不是降低 Ralph 的冲突敏感度。

---

### 值得尽快补的 4 个改动

这四个改动我认为是 Ralph 的高价值 v1.1：

#### 1) verification 预检

这是最该补的。你自己文档里已经承认过一次：

> Ralph validate 说 valid，但 verification_command 实际不可执行。

所以 Ralph 至少要能做一点轻量 preflight：

* `pytest path::test` 能不能 collect 到
* `python -c "from x import y"` 能不能 import
* shell 命令里引用的文件是否存在

不用真的执行测试，但至少不能再让“明显不存在”的命令混进 valid plan。

#### 2) 区分“硬阻塞”和“本批次淘汰”

现在 `blocked` 把两种完全不同的情况混在一起了：

* `depends_on:*` 这种是**硬阻塞**
* `claimed_paths_conflict:batch` 这种其实只是**本轮 batch 没被选中**

像 W2 现在不是“没法做”，而是“这一批先选了 P2，所以把它延后”。
这个语义差别很大，建议 Ralph 输出改成三类：

* `ready_now`
* `waiting_on_dependencies`
* `deferred_this_batch_due_to_conflict`

这样人不会误以为 W2 跟 E1 一样是“根本还不能动”。

#### 3) 给 ready 任务排序，而不只是列集合

当前 ready 集合对“有 4 个 worker”很好用，但如果你只有 2 个 worker，Ralph 没告诉你该先开哪两个。

我建议加一个简单排序依据：

* 解锁下游任务数
* 关键路径长度
* 是否覆盖 critical issue / critical flow

按这张图看：

```text
P2 -> W1 -> E1
P1 -> W3 -> E1
P3 -> W3 -> E1
P4 -> W3 -> E1
W2 -------> E1

P2 与 W2 同文件冲突
```

在 `P2` 和 `W2` 二选一时，**P2 明显更该优先**，因为它会解锁 W1。
所以当前 suggest 的选择方向是对的，但最好把这个“为什么”明确输出出来。

#### 4) 支持 negative / forbidden flow

现在 Ralph 只检查正向流，比如：

* worker complete triggers verify
* daemon wires ralph

但这次真正容易复发的问题还有反向流：

* `cccc_message_send` **不能**把 task 标成完成
* `cccc_task` **不能**绕过 verify gate

建议支持类似：

* `forbidden_flows`
* `must_not_change_state_via`

否则 Ralph 只能证明“新路径存在”，不能证明“旧旁路已封死”。

---

## 二、当前并行化方案是否合理

### 结论

**合理，而且是保守合理。**

尤其是初始 suggest 里这批：

* P1
* P2
* P3
* P4

我认为这是当前计划下**更优的首批选择**。

因为唯一明显的替代方案是把 `W2` 放进来、把 `P2` 换出去，但那样虽然 batch 大小还是 4，**却会让 W1 继续锁死**。
所以从“解锁下游能力”看，选 `P2` 明显优于选 `W2`。

---

### 但不要把它执行成“严格 Wave 1 全做完，再进 Wave 2”

这点很重要。

从你现在的依赖图看，真正的结构不是硬三波，而是一个**动态 DAG**。
更合理的执行方式是：**每完成一个任务就重新 suggest**，不要等整波结束。

更具体地说：

#### 情况 A：P2 先完成

那就不必等 P1/P3/P4 全部结束。
此时应立刻重跑 suggest，通常会出现：

* W1 ready
* W2 ready（前提是 P2 已不再 running）

也就是说，**W1/W2 可以提前启动**。

#### 情况 B：P1/P3/P4 先完成

那也不必等 P2。
因为 W3 只依赖 P1/P3/P4，所以这时 **W3 可以先启动**。

所以正确理解不是：

* Wave 1 → Wave 2 → Wave 3

而是：

* **先跑首批 ready**
* **谁先完成，就解锁谁的下游**
* **持续滚动重排**

---

## 三、我唯一会重点追问的并行化风险

### W1 可能隐含依赖 W2

从你计划文本看，W1 现在只显式依赖 P2。
这在“结构上”说得通，但在“测试实际上怎么跑”上，可能有隐藏风险。

因为 W1 的验收写的是完整链路：

`task complete -> daemon IPC -> apply_task_event -> verify_completion -> state advance`

如果这条测试链路走的是 **cold-start daemon 路径**，那它很可能已经隐含要求：

* orchestrator 能正确初始化
* `project_root` 已经被正确解析
* RalphService 已可用

这部分其实就是 W2 的主题。

所以这里有两种更稳的做法，二选一：

1. **把 W1 的测试限定为 warm-path integration**
   也就是测试“verify gate 链条本身”，不把 cold-start/init 责任塞进去。
   那它就可以继续和 W2 并行。

2. **如果 W1 的测试一定走 cold-start 真链路，那 W1 应显式 depends_on W2**
   不然依赖图会偏乐观。

这点要看你们现有 `test_smoke_workflow.py -k verify` 到底怎么构造。

---

## 四、我对 Ralph 的总体判断

我的判断是：

**Ralph 当前已经够用来防止“结构性胡来”，但还不够用来证明“执行上稳妥”。**

所以现在最合适的策略不是大改 Ralph，而是：

* **继续执行当前计划**
* 但同时尽快给 Ralph 补上：

  * verification preflight
  * blocked 语义拆分
  * ready 排序/解锁评分
  * forbidden flow 检查

---

## 五、一句话版本

* **要不要改 Ralph？要，但不是为了让当前计划继续不了；而是为了提高计划结果的可信度和调度解释力。**
* **当前并行化方案合理吗？合理，且首批选择是对的；但应按“动态重排”执行，不应僵化按 Wave 整批推进。**
* **最值得现在确认的一点，是 W1 的验证是否隐含依赖 W2。**

下一条我可以直接按这个判断，把你这份 plan 重排成一个“动态 DAG 执行版”，顺手把 Ralph 应补的 4 个点写成具体规则。
