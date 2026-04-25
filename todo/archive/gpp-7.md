我先给一个主判断：

**最合适的方向，不是把 Serena 变成 Ralph 的“第二个大脑”，而是把它做成 Ralph 的“代码事实层”。**
Ralph 继续负责结构校验、调度、verify gate；Serena 只负责提供**确定性的代码事实**：符号是否存在、谁引用谁、一个文件里有哪些公开入口、某个删除/改接口会波及哪些静态调用点。这样最贴合你现在的边界：去掉 MCP、Ralph 保持无状态、MVP 先走 `ralph validate --semantic`，并且正好补到文档里列出的那批“Ralph 知道文件，但不知道符号/引用链”的缺口。

## 1. 集成形态：逻辑上 sidecar，落地上先嵌入式 provider

我不建议“直接把 Serena API 散着调用进 Ralph 规则里”，也不建议第一步就上一个重 daemon 化的独立服务。

更稳的形态是：

```text
ralph.core                # 纯结构规则、suggest、verify，不碰 Serena
  ^
  |
semantic rule bridge      # 把代码事实翻译成 Ralph 的 ValidationIssue
  ^
  |
SemanticProvider          # 抽象接口
  ^
  |
SerenaProvider            # 用 Serena Python API 实现
```

也就是：

* **逻辑边界按 sidecar 设计**：Ralph 只依赖一个 `SemanticProvider` 接口，不依赖 Serena 具体实现。
* **MVP 先用进程内 provider**：`ralph validate --semantic` 时临时初始化 Serena/LSP，跑完就释放。
* **后续再把 provider 外置**：如果启动 pyright 开销开始影响体验，再把它换成 `ralph-semanticd` 这类长生命周期 sidecar，但规则层不用改。

这样有三个好处：

第一，**Ralph 核心仍然纯**。语义查询是一个可选附加层，而不是把 validate 变成“半个 agent”。
第二，**失败隔离好**。LSP 起不来、索引不完整，不会拖垮结构校验。
第三，**便于逐步放量**。你先做 `validate --semantic`，以后再把同一套语义事实接到 `suggest` 或 `verify`。

我还建议加一条硬原则：

**Serena 在 Ralph 里只用查询能力，不用编辑能力。**
`find_symbol / get_symbols_overview / find_referencing_symbols / search_for_pattern` 可以接；`replace_symbol_body / rename_symbol / safe_delete_symbol` 这些能力可以借它的分析逻辑，但不要让 Ralph 自己去改代码。否则 Ralph 的角色边界会被冲掉。

---

## 2. 能力优先级：先补 validate，不要一开始就动 suggest/verify

文档里最关键的事实是：你现在真正痛的不是“调度不够聪明”，而是**计划结构过了，但代码事实根本没核实**。所以优先级应该按“先让 plan 更真实，再让调度更聪明”排。

### 第一批，MVP 必做

我会先做这 3 个：

**A. 符号存在性验证**
对应你文档里的 RV-18。
任务明确声明要改某个函数/类/方法，如果 Serena 找不到，就直接报错。

建议新规则：

* `E_SYMBOL_TARGET_MISSING`
* `W_SYMBOL_TARGET_AMBIGUOUS`

这是最稳、最确定、最容易让 Foreman 受益的一项。

**B. 删除/重命名的静态引用检查**
这比泛泛的“死代码验证”更实用。
如果 task 声称 delete/rename 某符号，Serena 发现还有静态引用，就应该阻止。

建议新规则：

* `E_DELETE_SYMBOL_STILL_REFERENCED`
* `E_RENAME_SYMBOL_REFS_OUTSIDE_SCOPE`

这类正好解决“删了函数但副作用链没处理”的问题。

**C. 跨文件原子性检查（先做窄版）**
但第一版只盯**高风险操作**：`delete / rename / modify_interface`，不要一上来对所有 `modify_body` 做 blast radius。

建议新规则：

* `W_INTERFACE_CHANGE_REFS_OUTSIDE_CLAIM`
* `W_STATIC_BLAST_RADIUS_LARGE`

它直接针对你总结的那个核心教训：**按文件拆任务会做出精致的死代码**。
如果一个任务改接口，静态上有 40 个调用点，但 plan 只 claim 了 2 个文件，那至少应该被亮黄灯。

### 第二批，再做

**D. 自动依赖推断（warning）**
这是 validate 阶段很好用的“隐式依赖提示”，但不要自动改 plan。
规则名可类似：

* `W_IMPLICIT_SYMBOL_DEPENDENCY`

**E. 符号级冲突检测**
这是 `suggest` 很诱人，但我建议延后。原因很简单：
调度层一旦误判，代价比 validate 多一个数量级。
第一阶段只把它做成 validate warning，不作为 scheduler hard blocker。

### 第三批，锦上添花

**F. 验证范围优化**
用 Serena 推荐相关测试，很有价值，但只能做**快反馈建议**，不能替代最终验证。

**G. 调用链权重 / risk score**
可以作为排序参考，但不是 correctness 核心。

---

## 3. plan.yaml 扩展：需要，但要“稀疏、可选、只标高风险符号”

我认为**需要扩展**，但不是为了让 Foreman 把每个私有 helper 都列出来。

因为如果只靠 `claimed_paths` 自动推断，Serena 只能回答“这些文件里大概有哪些符号”，却回答不了：
**这次任务到底打算动哪个符号、是改函数体、改接口，还是删掉它。**

所以我的建议不是直接用你现在的 `symbol_changes` 原样，而是稍微收一下，做成一个可选的 `semantic` 块：

```yaml
tasks:
  - id: T1
    claimed_paths:
      - src/cccc/daemon/foreman/workflow_orchestrator.py

    semantic:
      mode: advisory   # off | advisory | strict
      symbols:
        - relative_path: src/cccc/daemon/foreman/workflow_orchestrator.py
          name_path: WorkflowOrchestrator/assign_ready_batch
          op: modify_body   # create | modify_body | modify_interface | delete | rename

        - relative_path: src/cccc/contracts/v1/ralph_ipc.py
          name_path: ReadyBatchSuggestion
          op: modify_interface
```

### 这个设计我建议保留的点

* **显式声明 symbol target**：这是 Serena 能变成“规则引擎”而不是“文本猜测器”的关键。
* **path + name_path 同时给**：比 Python 模块路径字符串更稳，也更贴 Serena 的原生查询模型。
* **op 要保留**：它决定严重度边界。`modify_body` 和 `delete` 不是一回事。

### 我建议你改的点

**1）把 `modify_signature` 扩成 `modify_interface`**
因为你后面会遇到的不只是函数签名，还有：

* dataclass 字段变化
* 常量/协议/类型别名变化
* class public method 集变化

`modify_interface` 更通用，也更贴近 Ralph 的计划层语义。

**2）v1 不要加 `symbol_references`**
先别让 Foreman 手填“我要检查哪些引用”。
引用集合本来就是 Serena 最擅长算的东西，应该**算出来**，不应该**填进去**。

**3）只要求高风险任务写 semantic.symbols**
哪些算高风险？

* delete
* rename
* 改公开接口
* 跨边界集成任务
* 文档里那些历史上经常出事的入口链路

普通 leaf task 只改内部实现时，可以不写；这时 Serena 只做 advisory，不做 hard gate。

### 向后兼容怎么做

很简单：

* 没有 `semantic` 字段：沿用现有 Ralph 行为。
* 有 `semantic.mode: advisory`：只出 warning/hint。
* 有 `semantic.mode: strict`：允许部分规则升成 error。

这样你完全可以渐进迁移，不会把 Foreman 一次性压垮。

---

## 4. 确定性边界：在 Python 里，“发现了”比“没发现”更可靠

这个边界最好一句话定死：

**Serena 在 Python 里，正证据强，负证据弱。**

也就是：

* **“找到了一个符号/引用”**，通常是强事实。
* **“没找到”**，很多时候只是 best-effort，尤其遇到动态导入、反射、`getattr`、注册表、monkey patch。

所以 severity 我会这样分。

### 可以升到 error 的

前提是：**任务显式声明了目标符号，而且查询是 exact 的。**

**error 级：**

1. `modify_body / modify_interface / delete / rename` 指向的目标符号不存在
2. `delete` 的目标符号存在静态引用
3. `rename` 的目标符号存在静态引用，但 task scope 明显覆盖不到
4. 同一个 task 声称修改的 symbol 不在其 `claimed_paths` 内

这些都是“计划声称 A，但代码事实不是 A”。

### 最好先做 warning 的

1. `modify_interface` 后发现大量静态调用点在任务范围外
2. 两个任务之间存在潜在符号级隐式依赖
3. 文件里还有多个公开入口未被 task 的 semantic 目标覆盖
4. 发现 blast radius 很大（例如 fanout 很高）
5. 基于引用图推荐测试范围

这些都很有价值，但不够“必须阻断”。

### 不要靠它做 hard gate 的

1. “没有任何引用，所以一定可安全删除”
2. “没有发现冲突，所以一定可以并行”
3. “没有发现测试，所以不用测”

这些在 Python 里都太危险了。

所以我的建议是：

* **Serena 只用于增加 hard blocker，不用于减少 hard blocker。**
* 也就是说，文件级 `claimed_paths` 冲突仍然是硬边界；符号级分析只能额外加 warning/block，不能拿来放松现有调度规则。

这一条非常重要，不然你会为了“更聪明的并行”把调度安全性换掉。

---

## 5. 分层模型：不是三层，是更准确的四层

你文档里写成“三层校验模型”，但实际上更准确地说是四层：

### 第 1 层：结构层（Ralph core）

回答：

* 计划结构是否自洽？
* 依赖图是否安全？
* 验证骨架是否存在？
* claimed_paths / covers / contracts 是否合理？

**不读代码。**

### 第 2 层：代码事实层（Serena-backed Ralph semantic）

回答：

* 这个 symbol 在不在？
* 谁引用它？
* 这个文件有哪些公开入口？
* 某个 delete/rename/interface change 的静态影响面有多大？

**只产出事实，不做业务判断。**

### 第 3 层：语义审查层（LLM Agent）

回答：

* 这样改是否真的符合目标行为？
* 这些静态证据说明的风险，在业务上要不要阻断？
* 验证命令是否真的能证明 acceptance？

**只处理前两层不能确定的东西。**

### 第 4 层：运行时验证层（verify / E2E）

回答：

* 这条真实路径到底通没通？
* 禁止流程是不是确实被挡住了？

**最后裁决行为成立与否。**

### 怎么避免层间重复

关键不是“每层都少做点”，而是**前一层输出要结构化**，后一层只接 unresolved items。

比如第 2 层输出：

```json
{
  "facts": [
    {"type": "symbol_missing", "task": "T1", "symbol": "..."},
    {"type": "static_refs_found", "task": "T2", "count": 14, "files": [...]},
    {"type": "dynamic_zone", "path": "src/plugins/registry.py"}
  ]
}
```

然后：

* Ralph 直接把 `symbol_missing` 变成 error/warning
* Agent 只看 `dynamic_zone`、`blast_radius`、`acceptance still ambiguous`
* verify/E2E 根本不关心这些事实，只关心跑出来的结果

这样你不会让 Agent 再去重复“符号在不在”这种机械工作。
这也是你文档里“把一部分 Codex 才能发现的问题，转成 Ralph 规则”的最好落地方式。

---

## 6. 风险和陷阱：主要有三个，都是可控的

### 风险 1：LSP 假阴性

这是最大风险。处理方式不是“假装它没问题”，而是**在输出里显式带不完备标记**。

例如：

* `W_SEMANTIC_PARTIAL_DYNAMIC_IMPORT`
* `W_SEMANTIC_PARTIAL_REFLECTION_ZONE`

一旦命中这些区域，相关结论只能降级成 warning/hint。
不要把“没找到引用”当证明。

### 风险 2：符号级检查假阳性太多

这通常发生在你把所有改动都按“改接口”处理时。

解决办法很简单：**op 语义分层**。

* `modify_body`：只看 risk，不看覆盖完整性
* `modify_interface`：看静态调用点
* `delete / rename`：最严格

这样可以大幅降低“明明只是改实现，却被要求全项目覆盖”的噪音。

### 风险 3：Foreman 负担变重

如果你要求每个 task 都写 10 个 symbol，计划会迅速失控。

所以一定要坚持这条：
**semantic 注解只标高风险、跨边界、公开契约相关符号。**

再进一步，我建议后面补一个辅助命令，不必一开始就做，但很值：

```bash
ralph validate plan.yaml --semantic --suggest-symbols
```

它根据 `claimed_paths` + `get_symbols_overview` 给出候选 symbol，让 Foreman 选，而不是纯手写。
这样 Serena 不只是“审查器”，还可以变成**计划标注的辅助器**。

---

## 我会怎么落第一步

如果你现在只做一条最值的路径，我建议就是下面这套：

1. 新增 `task.semantic.symbols[]`，可选。
2. 只做 `ralph validate --semantic`，先不碰 daemon、suggest、verify。
3. 第一批只上 3 条规则：

   * `E_SYMBOL_TARGET_MISSING`
   * `E_DELETE_SYMBOL_STILL_REFERENCED`
   * `W_INTERFACE_CHANGE_REFS_OUTSIDE_SCOPE`
4. 结果里加一个 `semantic_confidence` / `partial_reason` 字段。
5. 文件级调度规则不变；符号级结果只做 validate warning，不直接改 batch。

这样做的好处是：

* 和你现有 Ralph 边界最一致
* 最容易把一部分 “Codex 才能发现的代码事实问题” 转成规则
* 不会因为 Serena 接入而把 Ralph 变成新的复杂执行系统
* 真正先跑通了一条路径，而不是一上来同时改 validate/suggest/verify

一句话概括：
**先让 Serena 帮 Ralph 看清“代码里到底有什么”，再谈“这些任务该怎么并行、该怎么更聪明地验收”。**

如果你愿意，我下一步可以直接按这个思路给你写一版更具体的接口草案：包括 `SemanticProvider` 的 Python 接口、建议新增的 `ValidationIssue` 代码表，以及 `plan.yaml` 的最小 schema。
