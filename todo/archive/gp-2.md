我先给结论：这份文档对**问题根因**的判断基本是成立的，尤其是“死代码、接线错误、状态分裂、静态验证掩盖运行时断裂”这几个判断很准；而且把目标收束到“最小闭环”“HTTP/CLI 为主”“Worker 报完成不等于完成”“并行单元按功能切片而不是按文件”也是对的。真正需要调整的，不是方向，而是**落地顺序**和**改动粒度**：现在的实施规划里，仍然有几处容易再次掉进“先重构、后验证”的坑。 

**一、我认为应该继续强化的方案**

第一，**R-5 的调用路径修复应该被提升为第一优先级中的第一刀**，甚至可以先于大部分 Phase 开始做。因为文档已经明确指出，当前闭环断点不是抽象层不够，而是 `task_event` 走错了入口，导致 `on_task_completed/on_task_failed`、通知、batch 推进全部不触发。这个问题一旦不修，后面无论是状态统一、prompt 接线还是冲突检测，都还是搭在断路器上。更合适的做法是：先做一个“最小补丁集”——修 handler 调用路径、让 daemon 启动时真的创建 Ralph、让一次 completed 事件至少能推进到 verifying。只要这三步一通，系统就从“死代码堆”变成“可观察的坏系统”，后续问题才能被真实暴露出来。

第二，**“Worker 完成信号必须脱离 prompt 自觉性”这个方向要再往前推**。文档里已经指出，不同 runtime 对 MCP 的使用倾向不同，导致 Foreman 不能靠 inbox 轮询判断任务完成；同时项目负责人也明确说 MCP 不是核心路径。这里更合适的解法不是继续强化“prompt 里要求 Worker 回报”，而是把“完成事件”下沉到 runner / daemon 基础设施：比如 Worker 执行包装器在命令退出时自动上报 `running -> verifying` 事件，LLM 的消息只作为 evidence 补充，而不是唯一完成信号。这样才能真正消除 runtime 差异。

第三，**“API Contract Phase”这个提议是对的，但最好不要做成一个又厚又独立的新大阶段**。文档已经证明前后端并行时最大的问题是契约飘移。更合适的办法是把契约变成每个功能切片的强制输入，而不是额外开一个人工讨论阶段：也就是在 `TaskRef` 里或同级对象里要求 `interface_contract` / `schema_ref` / `example_io` 必填。这样 Foreman 在出 task 时就顺手把契约带上，而不是先开一轮“Contract Phase”，再开一轮真正开发。否则流程会更重。

**二、我会明确提出质疑的地方**

最值得质疑的是 **Phase 0“新建统一状态层”**。这个方案的目标没有问题，但风险很高：文档自己就提醒过，最怕“消除三处写入点，结果变成第四处写入点”。现在的规划是新建 `WorkflowStateStore`，再同步改 orchestrator、Ralph、reporter、HTTP handler；这很像一次“小型重构性替换”，而项目负责人已经明确反对“先把模型设计完美再动手”这一类路径。我的质疑是：如果还没先跑通最小闭环，就直接引入新的权威状态层，很可能再次发生“接口设计很完整，但没人真正按那条路径运行”。更合适的做法不是“一次性切换真源”，而是**先做 ledger-based authoritative projection**：先指定一个现有入口作为唯一写入口，例如 orchestrator + ledger 事件流，然后让 Ralph 和 reporter 暂时只读这个投影；等闭环跑通后，再把 Context/旧内存状态慢慢下线。也就是用绞杀者模式，不用大爆炸替换。

第二个我会质疑的是 **把 MCP bridge 仍然放在 P0**。文档前半部分确实把“R-1 缺 MCP 工具”列成 Critical，但后面的需求澄清又明确说 MCP 是可选保留，核心路径是 HTTP + CLI，而且项目负责人从一开始就强调“去掉 MCP”。这两部分是有张力的。我的看法是：如果当前的目标是恢复最小闭环，那新建 `cccc_workflow` MCP 工具不该是 P0，而应该降级成兼容层。否则团队很容易又把精力投入到“让 Foreman 能通过 MCP 做 Ralph 操作”，而不是“让 Ralph 在 daemon 内部真运行起来”。更合适的策略是：**P0 只保证 HTTP API + CLI 全链路可用，MCP 只做 thin adapter 或完全延后**。

第三个值得质疑的是 **Phase 2 的验证逻辑仍然有“把静态检查包装成验证”的风险**。文档已经明确批评过上一轮把 `py_compile` / `tsc` 当验收标准，但新方案里的 `verify_completion()` 第一层依然先做 changed files 的 `py_compile`，第二层跑 `verification_command`，第三层再比对 `expected_output`。问题在于：`expected_output` 的“actual”从哪来、怎么采集、输出归一化规则是什么、超时怎么处理、副作用怎么隔离，文档里还没定义。于是很可能落地时第一层和第二层能写出来，第三层因为抽象不清继续空转，最后系统又退化成“编译 + 命令退出码”。更合适的做法是：把验证器做成**任务类型驱动**而不是统一拼装三步。比如 API 任务固定用 HTTP probe，前端任务固定用页面快照/构建产物检查，纯代码任务固定用 targeted tests。这样“actual output”的来源才是明确的。

第四个我会质疑的是 **Phase 3 capability prompt 全链路切换的时机**。文档自己已经指出这里存在兼容风险：`delivery.py` 三处调用、`Actor` 模型适配、CLI `cccc prompt`、测试、`CCCC_PREAMBLE.md` 都会受影响。对于一个当前连最小闭环都没跑通的系统，这类 prompt 基础设施切换很容易形成“又一个大面积变更面”。更合适的方式是两步走：先在当前 `render_system_prompt()` 中**最小注入**验证门控和功能切片规则，等 HTTP 闭环稳定后，再统一切 capability YAML。换句话说，先 patch 行为，再重构 prompt 管线。

第五个我会质疑的是 **Phase 6 hot reload 的优先级**。文档也写了，它主要是“优化工作流本身开发时有效”。但从 Phase 7 的成功标准看，热重载不是闭环成立的必要条件；反而它会引入新的状态恢复噪音，让团队很难区分“热重载恢复错了”还是“工作流本身错了”。更合适的做法是：把 hot reload 放到第一次端到端通过之后，作为开发体验增强，而不是主实施路径的一环。

**三、我认为更合适的总体实施方法**

我建议把原来的 0-7 阶段，改成“先打通，再统一，再优化”的顺序。

先加一个 **Phase -1：可执行冒烟场景**。不是最后才做 `cccc test-workflow --scenario ...`，而是一开始就做一个最小冒烟命令：单 workflow、两三个 task、一个 worker completed、一个 verification pass、一个后继任务解锁。文档已经明确说“验证基础设施应先于功能开发”，所以这个命令不该放在 Phase 7，而该成为后续所有 Phase 的回归门。

然后做 **Phase A：最小闭环修复**。只修四件事：daemon 初始化 Ralph、`task_event -> orchestrator.apply_task_event`、`running -> verifying -> completed/failed` 真流转、HTTP 路由能观察到状态变化。这一阶段不要碰 prompt 全切换，不要碰 MCP bridge，不要做 hot reload。目标只有一个：系统从“断路”变成“能跑一圈”。这也最符合文档里“先跑通再扩展”的原则。

再做 **Phase B：完成信号与验证器固化**。这里把 runtime 不可靠、Worker 不按 MCP 回报的问题收口到 runner/daemon 事件模型；同时把验证器从“统一三步拼装”改成“按任务类型选择验证模板”。这样 verifying 才不会沦为空状态。

接着才是 **Phase C：状态收口**。这时再逐步引入统一状态层，但我建议采用兼容迁移：先让 orchestrator 写 ledger projection，Ralph / reporter / routes 读 projection；等 projection 稳定后，再下线旧写点。不要一上来就让所有组件同时改写 `WorkflowStateStore`。

最后再做 **Phase D：prompt 管线、契约强化、可选兼容层**。包括 capability YAML 统一接线、`scope_policy`、技术规格偏离上报、API 契约模板、如果确实还需要的话再补 MCP adapter。这样顺序更稳。

**四、对端到端验证方案的进一步改进**

文档里的 Phase 7 场景有一个很好的目标，但我会质疑它**过于开放**：让 Foreman “自行选择一个中等复杂度前后端项目”去实现，这很适合做演示，却不适合做回归门。因为模型随机性太大，失败时你无法判断是 workflow 机制坏了，还是模型恰好选了一个坑很多的项目。更合适的方案是做两层验证：

先有一个**确定性基准场景**，例如固定书签 CRUD、小型全栈模板、给定 contract 和验收命令，专门用于回归；
再有一个**开放探索场景**，保留你现在这段提示词，用来检验 Foreman 的自主规划能力。

前者解决“能不能稳定复现”；后者解决“真实使用时好不好用”。这两层都需要，不能只要后者。

**五、最后的判断**

如果只问“原方案是不是方向正确”，我的回答是：**大方向正确，执行顺序不够克制**。
如果只问“最该警惕什么”，我的回答是：**不要把 Phase 0 和 Phase 3 做成新的大重构中心**。文档自己最有价值的洞见，其实不是 `WorkflowStateStore`、不是 capability YAML，而是这句：**不可运行的代码，无论计划多精细，都只是假进展。** 所以更合适的路线是：先用最小补丁让系统真的转起来，再去谈统一状态、统一 prompt、统一兼容层。

你要的话，我可以下一步把这些意见整理成一版**“修订后的实施规划（按新 Phase 重排）”**。
