我整体同意文档把问题归因为“状态模型分裂 + 契约漂移”，但我觉得还少了一个更核心的根因：**系统没有明确的控制面单一事实源**。现在 actor 生命周期、workflow 进度、task assignment、workspace 写权限，分别散落在 route、daemon、store、UI 里，所以原方案里有些修复能止血，但也可能把这种分裂继续固化。下面我按“我赞成什么、我质疑什么、为什么、我认为更合适的方案是什么”来展开。 

## 1. Workflow Progress 这块，修 API 形状是必要的，但不能只修“表面形状”

### 我赞成

BUG-01 到 BUG-04 的方向是对的：`project_root` 必须补，idle 结构必须完整，前后端契约必须统一。

### 我质疑

原方案里有两个点我不建议直接照做。

第一，**不要把“无 orchestrator”简单伪装成 idle**。
原因是：
`idle`、`unavailable`、`misconfigured`、`daemon_not_running` 在排障语义上完全不同。前端确实需要一个“可渲染的空结构”，但这不等于语义上它就是 idle。把错误折叠成 idle，会让监控、告警、排障都失真。

第二，**不要把“扁平化返回”当成长期方案本身**。
如果这次只是把后端改成前端当前想要的形状，本质上还是“谁先出 bug，谁决定契约”。这次能修，下一次还会漂。

### 我认为更合适的方案

把 workflow progress 定义成**显式状态壳 + 固定 snapshot**：

```json
{
  "kind": "idle | running | stalled | unavailable | error",
  "reason_code": "no_active_orchestrator | project_root_missing | daemon_unreachable | ...",
  "snapshot": {
    "batches": {...},
    "tasks": {...},
    "duration": {...},
    "recent_events": [],
    "assignments": []
  },
  "workflow_id": "...",
  "active": false
}
```

这样前端永远只消费 `snapshot`，不会因为字段缺失崩；同时 `kind/reason_code` 保留真实语义，不会把“系统没起来”和“系统空闲”混为一谈。

### 落地建议

不要只在 `workflow.py` 里补 `project_root`，而是抽一个统一入口，比如 `resolve_group_runtime_context(group_id)`，所有 workflow 相关 op 都从这里拿：

* group active scope
* project_root
* orchestrator handle
* feature flags
* group runtime metadata

这样能避免今天修 progress，明天别的 route 又忘记传 `project_root`。

---

## 2. “新增 completed/failed 两个 op”能修 bug，但不是更好的总线设计

### 我赞成

你文档里提到 `workflow/task/completed` 没有真正推进 orchestrator 状态，这个判断很关键，确实是数据管线里更深的一层 bug。

### 我质疑

我不建议长期采用：

* `ralph_task_completed`
* `ralph_task_failed`

这两个新 op 作为长期接口。

原因很简单：今天是 completed/failed，明天就会继续长出：

* blocked
* heartbeat
* cancelled
* resumed
* retry_started

最后 IPC 层会变成一个“事件枚举散落”的系统，继续造成契约漂移。

### 我认为更合适的方案

做成一个统一入口：`ralph_task_event`

事件结构里至少要有：

* `assignment_id`
* `task_id`
* `actor_id`
* `attempt`
* `event_type`
* `timestamp`
* `idempotency_key`
* `lease_id/run_id`
* `payload`

然后 orchestrator 只暴露一个 `apply_task_event()`，内部做：

1. 幂等去重
2. 事件顺序校验
3. assignment 是否仍然有效
4. 状态迁移
5. snapshot 重建

### 为什么这比原方案更合适

因为你后面一旦引入 stalled、reassign、retry，这些都天然是“事件流”问题，而不是“再多开几个 op”问题。

更重要的是，**assignment_id / lease_id** 是你文档里还没写出来、但我认为必须补的一层。
没有这个，旧 worker 被 stop 以后，迟到的 completed 事件仍然可能覆盖新 assignment 的状态。
这会让你前面所有 stop、stalled、reassign 方案都留下后门。

---

## 3. Actor 的 hold_reason 比 stopped_by_foreman 更好，但仍然是补丁，不是状态机

### 我赞成

`hold_reason` 比 `stopped_by_foreman` 更合理，因为它至少表达了“为什么不能自动恢复”。

### 我质疑

但我不建议把：

* `enabled`
* `hold_reason`

继续作为 actor 生命周期的核心模型。

原因是现在 `enabled` 还在同时承载：

* 用户期望是否启用
* 调度层是否允许恢复
* 进程当前是否应该运行

这三个语义本来就不该混在一起。
只加 `hold_reason`，相当于在一个已经过载的字段模型上继续贴补丁。

### 我认为更合适的方案

把 actor 状态拆成三层：

* `desired_state`: `running | stopped`
* `runtime_state`: `starting | running | stopping | stopped | crashed`
* `admin_hold`: `none | manual | policy`

再补一个：

* `run_id` 或 `generation`

### 为什么这比原方案更合适

这样自动恢复只需要看一条清晰规则：

> 只有 `desired_state=running` 且 `admin_hold=none` 时，系统才允许拉起 actor。

而 `run_id/generation` 能解决另一个关键问题：

> stop/restart 之后，旧进程的迟到上报必须作废。

这点如果不补，WF-01 看似修了，实际上只是“多数时候不复活”，不是严格正确。

---

## 4. 我不建议把 single_writer 当成 Wave 2 的主方案

### 我赞成

你文档里对共享文件系统无冲突检测的判断是对的，必须尽快止血。

### 我质疑

我不同意“先 single_writer，后 claimed_paths”作为主要路线。

原因有两个：

第一，**single_writer 吞吐损失太大**。
它会把所有写任务都串行化，短期能稳，但很容易把工作流系统退化成“带 UI 的单工执行器”。

第二，**它并不能解决 dirty read**。
就算同一时刻只允许一个 writer，其他 worker 仍然可能去读这个 writer 正在改的半成品文件。
你文档里 WF-03 其实就是这个问题：不是只有“同时写”，还有“读到未发布中间态”。

### 我认为更合适的方案

我建议把 `claimed_paths` 提前，不要等到 Wave 3。

但不是一步到最细，而是分两级：

**第一层：现在就做粗粒度 write claims**

* task 必须声明 `write_set`
* 声明不出来的，默认 `write_set=["/"]`
* 允许 read-only task 并发
* 允许不冲突路径并发

**第二层：加 publish barrier**
worker 不直接把“进行中的中间态”暴露为全局事实，而是：

* 在临时工作区写
* 或者写完后统一 patch apply / atomic publish

### 为什么这比原方案更合适

因为它同时解决两个问题：

* 写冲突
* 脏读

而 single_writer 只能解决第一个的一部分。

### 关于 Git worktree

文档里把 Git worktree 否决掉，我理解“全链路一次性引入太重”的顾虑；但我不建议把它降得太后。
更现实的路线不是“现在完全不用”，而是：

* 短期：path claims + publish barrier
* 中期：对高风险写任务启用临时 worktree / patch merge
* 长期：writer 全量 worktree 化

这样复杂度是可控的，但方向是对的。

---

## 5. Heartbeat 不能只看 progress，要区分“活着”和“在推进”

### 我赞成

“不能依赖 worker 自己上报 blocker，必须有被动检测”这个判断完全正确。

### 我质疑

我不建议只用 `last_progress_at` 作为 stalled 判定基础。

原因是：

* 一个 worker 可能还活着，但长时间没产生业务进展
* 也可能进程已经死了，但系统最后一次状态还停在 running
* 还有一种情况是：worker 明确上报了 blocker，这不应该被混成 stalled

### 我认为更合适的方案

做双时钟：

* `last_seen_at`：runner/agent 心跳，表示“进程还活着”
* `last_progress_at`：task event、文件变更、显式进展，表示“任务在推进”

然后状态分开：

* `blocked`：worker 主动上报受阻
* `stalled`：worker 还活着，但长期无进展
* `offline/lost`：连心跳都断了
* `failed`：任务明确执行失败

### 为什么这比原方案更合适

因为它把“活性问题”和“推进问题”拆开了。
否则你会把“深度思考但没输出”的正常情况，和“进程已僵死”的异常情况，错误地归到同一类。

---

## 6. “system 身份”比扩 foreman 权限好，但 generic system 太大了

### 我赞成

不直接把 foreman actor 变成超权主体，这个方向我赞成。

### 我质疑

但我不建议简单引入一个泛化的 `by="system"` 并广泛放行。

原因是：
一旦 `system` 成了万能后门，后面任何权限问题都能被“先 system 兜一下”绕过去，审计上也会越来越难收束。

### 我认为更合适的方案

引入**受限服务主体**，不是泛 system：

* `principal_type = service`
* `principal_name = workflow_orchestrator`
* `requested_by = foreman_id`
* `reason = workflow_scheduler`
* `allowed_actions = [reassign_task, suspend_actor, retire_actor, ...]`
* `scope = group_id/workflow_id`

权限系统只对这个受限服务主体放行有限动作，不给“全局 system 超权”。

### 另外一个我会调整的点

`remove actor` 我不建议直接做“物理删除”。
更合适是：

* `retire/decommission actor`
* 默认 UI 隐藏 retired actor
* 审计和历史 assignment 继续保留

这样能同时解决“列表清爽”和“历史可追溯”。

---

## 7. Board/Workspace/Panorama 的修法，不要继续 prop drilling

### 我赞成

补 AppShell 的渲染分支是必须的，这个 bug 很直接。

### 我质疑

我不建议把 `tasks/loading/isDark/onOpenTask` 继续从 `App.tsx -> AppShell -> BoardTab` 一路传下去。

原因是这次 bug 的本质就是**tab 架构迁移时接线断了**。
如果继续用 prop drilling，下一次重构时还会再断一次。

### 我认为更合适的方案

把 AppShell 退回“纯壳层”，只负责 tab slot 和 lazy boundary。
每个 tab 自己做 container：

* `BoardTabContainer`
* `WorkspaceTabContainer`
* `PanoramaTabContainer`

它们自己从 store/selectors 取数据。
AppShell 不感知 `tasks` 的具体 shape，只感知 “当前 tab 是谁”。

再进一步，做一个 tab registry：

```ts
const TAB_REGISTRY = {
  chat: ChatTab,
  actor: ActorTab,
  workflow: WorkflowTab,
  board: BoardTabContainer,
  workspace: WorkspaceTabContainer,
  panorama: PanoramaTabContainer,
}
```

### 为什么这比原方案更合适

因为这样以后新增 tab、重构 tab、懒加载 tab，都只改 registry，不会再出现“按钮有了，但内容分支没接上”的情况。

### 还有一个更根本的点

`WorkspaceTaskInfo` 不要再手工补字段了。
既然你已经把共同根因归结为“契约漂移”，那前后端类型最好直接共享或生成：

* 后端 schema 生成 TS types
* 前端用 zod/OpenAPI 校验

否则这次补 `priority/waiting_on`，下次还会漏别的。

---

## 8. Model Registry 和 runtime 差异，不应该靠 prompt 纪律维持

### 我赞成

文档里指出“Foreman 未查 Model Registry 即分配模型”是流程引导不足，这个判断是对的。

### 我质疑

但我不建议把“inspect model registry before assigning”继续当成一条 prompt 纪律。

原因是：

* 它太依赖人和 prompt 的执行质量
* 一旦换 runtime，执行习惯又不同
* 这类规则本质上属于调度器策略，不应该寄托在自然语言提醒上

### 我认为更合适的方案

把模型分配做成**结构化能力匹配**：

任务声明：

* `task_kind = backend | frontend | review | refactor | debugging`
* `complexity`
* `latency_sensitivity`
* `cost_sensitivity`
* `required_capabilities`

模型注册表声明：

* `strengths`
* `weaknesses`
* `cost`
* `speed`
* `context_window`
* `preferred_task_kinds`

然后调度器做 score，Foreman 可以 override，但默认推荐不是靠“记得先看 registry”。

### 对 runtime-specific prompt 的看法

我也不建议只做“不同 runtime 不同提示词”。
更好的方法是先定义统一 worker contract：

* 输入是什么
* 能写哪些路径
* 需要产出什么
* 如何汇报 progress/blocker/completion

然后再为 Claude / Codex / Gemini 分别包一层 adapter prompt。
这样差异是被收敛的，不是被放大的。

---

## 9. Ralph 观察层不应该放到太后面

WF-10 在文档里被放得比较后，但我认为至少要把一个**最小观察层**提前。
原因是下面这些能力都依赖观察层：

* changed_files 可信记录
* path claims 冲突判断
* stalled 的被动检测
* completion 的验证
* dependency readiness

不需要一开始就把完整 Ralph 搭满，但至少要提前做：

* Git diff snapshot
* assignment 级 changed_files
* ready batch 的最小依赖检查
* completion 后的轻量 verification hook

否则前面很多调度策略都还是“盲调度”。

---

## 10. 我会把原来的波次顺序改成这样

### Phase A：先收敛契约和状态模型

先做这几个，不然后面修一个坏一个：

* `WorkflowProgressResponse` 统一壳模型
* `resolve_group_runtime_context()`
* actor 三层状态模型
* shared schema / TS 生成

### Phase B：统一任务事件入口

直接做：

* `ralph_task_event`
* `assignment_id/attempt/lease_id`
* 幂等和顺序校验
* orchestrator 内部状态迁移表

这是整个 workflow 正确性的基座。

### Phase C：调度约束前移

不要先 single_writer 再想别的，直接上：

* 粗粒度 `write_set`
* read/write claims
* publish barrier
* dual heartbeat
* blocked/stalled/offline 区分

### Phase D：权限和 actor 生命周期收口

做：

* service principal
* retire actor 替代 hard remove
* desired/runtime/admin_hold
* run_id/generation

### Phase E：前端接线回归

再做：

* tab registry
* container tab
* contract-based types
* board/workspace/panorama smoke tests

### Phase F：再往前走治理能力

最后再做：

* worktree 隔离
* capability-based model selection
* 更完整的 Ralph observer
* DnD、Panorama 等体验增强

---

## 11. 测试方面，我会比文档再加三类

文档里的最小测试集我基本认可，但还应该加三类“真正能防复发”的测试。

第一类是**状态迁移测试**。
不是只测函数返回值，而是测：

* 什么事件允许从什么状态到什么状态
* 什么事件必须被拒绝
* 旧 assignment 的迟到事件是否被丢弃

第二类是**并发/恢复测试**。
要覆盖：

* 两个 worker 声明重叠 write_set
* stop 后旧进程迟到 completion
* stalled 之后 reassign，再收到旧 assignee 的 progress
* daemon 重启后 actor hold / desired state 是否保留

第三类是**契约漂移测试**。
前后端共享 schema 后，CI 必须在以下情况直接失败：

* 后端响应字段变了，前端类型没更新
* 前端依赖字段新增了，后端 schema 没声明
* tab registry 有按钮但无渲染组件

---

## 结论

这份方案的方向总体是对的，尤其是：

* 找到了 `project_root` 和 progress 管线问题
* 注意到了 stop 会自动恢复的语义漏洞
* 意识到了多 worker 共用工作区的根本风险
* 也意识到了权限模型和观测层缺失

但我认为还应该把方案从“修一串 bug”提升成“收敛控制面模型”。
我最想改的四件事是：

1. 不把 `orchestrator_not_found` 简单伪装成 idle，而是显式区分 `idle / unavailable / error`
2. 不新增多个 task op，而是统一成 `ralph_task_event + assignment lease`
3. 不把 `hold_reason` 当最终答案，而是补成 actor 生命周期状态机
4. 不把 `single_writer` 当主路线，而是尽快上 `write claims + publish barrier`

如果只做原方案里的表层修复，系统会“能跑一些、也能显示一些”；
如果按我上面这套收敛，系统才会开始具备**可控、可审计、可并发、可恢复**的基础。
