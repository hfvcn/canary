根据你提供的记录，当前项目的核心问题不是单个功能未修，而是“完成”的判定标准错了：大量事项停在“代码存在 + 单测通过”，但没有证明主路径调用、运行时条件满足、E2E 行为改变，甚至失败时还会静默回退。蓝图原本要求的是“模块化拆分 → 接口约束 → 黑盒输入输出验收 → Task/批次/全局分层验收”，但现实缺了中间层，所以假完成会反复逃逸。

## 总目标

把项目验收标准从：

`代码写了 → 单测过了 → 归档完成`

改成：

`主路径可达 → 运行时真实执行 → 行为证据可复现 → 失败不静默降级 → 才能归档完成`

后续改进应分四层推进：先封住假完成归档口，再修 AF/模型选择/复盘三条具体链路，然后补 Ralph 检查规则，最后实现蓝图缺失的模块化中间层。

---

## P0：立即止血，禁止继续“假完成归档”

### 1. 重新定义“完成”

所有已完成项必须降级为以下三种状态之一：

| 状态                 | 含义                     | 是否可归档    |
| ------------------ | ---------------------- | -------- |
| implemented        | 代码已写、测试通过              | 不可归档     |
| integrated         | 主路径已调用，有 call-chain 证据 | 不可单独归档   |
| behavior-verified  | E2E 或主路径命令证明行为改变       | 可归档      |
| no-silent-fallback | 失败时会阻断或发出可观测信号         | 高风险项必须满足 |

归档必须附带具体证据，不接受“已验证”“E2E 确认”这类文字。证据至少包含：命令、输出摘要、日志位置、事件 ID、E2E transcript 或 review 文件路径。

### 2. 建立“假完成隔离区”

把 AF 引擎、模型选择、评价闭环、WORKFLOW_EVALUATION、suppress_codes、DG-1~4 这些曾经反复假完成的项目全部移入 `false-completion-quarantine` 清单。每一项必须重新证明：

`原始症状是否消失`

例如 AF 不能只证明 `execute_bundle` 被调用，而要证明真实 E2E 里 `execution_engine != legacy`，并且 worker terminal 回流后才完成。

### 3. 修改归档检查

`flow_improvement_check.py` 不应只查“行为确认”关键词，而要强制检查证据字段：

```yaml
behavior_evidence:
  command: "..."
  expected: "..."
  actual: "..."
  artifact: "path/to/log-or-transcript"
  checked_at: "..."
```

没有这个结构化证据，不能从 active checklist 移入 full tracker。

---

## P1：修闭三条当前最关键的运行链路

### 1. AF 引擎：从“能启动”改为“完整闭环执行”

当前 AF 已从完全未执行推进到能激活，但仍暴露 `auto_complete_after_send=True` 的 fire-and-forget 问题，导致派发后没有等待真实 worker terminal 和 verification gate，容易进入 override→dispatch→fail 死循环。

改进要求：

| 项目                | 改法                                                 | 验收                                                    |
| ----------------- | -------------------------------------------------- | ----------------------------------------------------- |
| worker 完成权        | AF node 不能在 send 后自动 complete，必须等待 terminal event  | 日志显示 dispatch → worker terminal → verification passed |
| fallback          | 所有 AF→legacy 回退必须发事件和 warning/error                | ledger 中有 fallback reason                             |
| verification gate | AF completed 不等于 CCCC task completed               | 只有 verification gate 通过才 emit task complete           |
| runtime readiness | `_af_runtime_ready()` 必须验证真实 pool/actor/gateway 可用 | 不允许 env var 单独代表可用                                    |
| E2E 证据            | 跑一条真实 workflow                                     | 输出中明确出现 AF execution done，且无 silent legacy            |

这条线的退出标准：真实 E2E 中 AF 跑完整任务，worker terminal 回流，verification gate 通过，workflow completed 之后能从 ledger 追溯完整事件链。

### 2. 模型选择：从“Guide 建议”改为“流程消费”

问题不是 guide 没写，而是 Foreman/actor 创建路径没有稳定消费模型评价结果；之前还出现过“写了 rating，但创建 worker 时不读 rating”的断链。

改进要求：

| 项目          | 改法                                                                                                | 验收                                      |
| ----------- | ------------------------------------------------------------------------------------------------- | --------------------------------------- |
| 读端闭合        | `actor add` 默认路径先调用 `model suggest` 或同等选择函数                                                       | actor 创建日志包含 model_selection_decision   |
| 数据修正        | codex 覆盖 backend/general/code execution 等执行类 task type；claude 收窄到 review/frontend/aesthetic 等适用场景 | `cccc model suggest backend` 返回 codex   |
| enabled 过滤  | disabled model 不参与候选                                                                              | 测试覆盖 enabled=false                      |
| override 留痕 | 显式 `--runtime claude` 不硬拦，但必须记录 override reason                                                   | 复盘可审计                                   |
| E2E 验证      | 跑实际 workflow，看 worker runtime 分布                                                                  | 默认执行 worker 应主要为 codex，claude 用于审查或特定场景 |

注意：这里不建议靠 system prompt 强化“请用 codex”。应让模型选择流程本身成为 actor 创建路径的数据来源。

### 3. WORKFLOW_EVALUATION 和复盘：从“章节存在”改为“内容实质”

之前的问题是 `_check_placeholder_content()` 存在但未被调用，WORKFLOW_EVALUATION 可以生成空章节后直接完成。

改进要求：

| 项目         | 改法                                                             | 验收                          |
| ---------- | -------------------------------------------------------------- | --------------------------- |
| 内容检查前置     | 在 `workflow.completed` 之前检查 evaluation 内容                      | 空章节阻断 completed             |
| 八维复盘强制     | runtime 选择、agent 数量、安全审查、review 证据、Foreman 自评、prompt 改进等维度必须出现 | 缺任一维度失败                     |
| rating 真执行 | 不只查 “rating” 字样，要查 registry 时间戳和 model usage 记录                | registry 有本轮更新              |
| 复盘影响下一轮    | 评价结果必须被模型选择或 agent 规划读取                                        | 下一轮 `model suggest` 能体现评分变化 |

---

## P2：补 Ralph 检查规则，优先解决 DG-1~4

这是 ROI 最高的部分，因为它能一次性阻断同类假完成，而不是每次靠人工追问。

| 优先级  | 规则                                | 要解决的问题                | 初版实现方式                                                                         |
| ---- | --------------------------------- | --------------------- | ------------------------------------------------------------------------------ |
| P2-1 | DG-1 active-path reachability     | 代码改在非活跃路径，行为不变        | 从 configured entrypoint 建静态 call graph，结合 AF/legacy 当前分支判断 claimed symbol 是否可达 |
| P2-2 | suppress_codes 白名单化               | 被检查者自己关闭关键 warning    | 禁止 suppress 三类假完成相关 warning                                                    |
| P2-3 | DG-3 observable-fallback          | 静默回退 legacy           | 检测 fallback/return False/except-pass 是否有 event 或 warning+ 日志                   |
| P2-4 | behavior evidence command         | pytest 过但行为没变         | plan 中必须包含主路径命令，例如 `cccc model suggest backend`、daemon log grep                |
| P2-5 | DG-2 semantic-default consistency | 默认值改一处漏一处             | 扫描同语义默认值，如 runtime/model fallback                                              |
| P2-6 | DG-4 guard-ordering               | check 放在副作用之后         | 检测 gate/check 是否位于 emit/commit/write 之前                                        |
| P2-7 | review adoption check             | Codex review 提了问题但未采纳 | 每条 review finding 必须有 accepted/rejected/deferred 状态和原因                         |

尤其要把以下三个 warning 改成不可随意 suppress：

`W_VERIFICATION_BEHAVIOR_MISMATCH`
`W_INTEGRATION_NO_PRODUCTION_CALL_EVIDENCE`
`W_INTEGRATION_TASK_SHALLOW_VERIFICATION`

这些正是假完成逃逸的最后防线。

---

## P3：补齐蓝图缺失的“中间层”

蓝图真正能解决假完成的关键，是在 pytest 和人工 E2E 之间增加模块级、Task 级、批次级验收。当前现实是“大任务直接交给 worker 整体做，只跑 pytest”，缺了“拆”和“拼接”两步。

### 1. 引入 ModuleSpec

每个 Task 先被 Foreman 拆成多个 Module，每个 Module 必须有固定结构：

```yaml
module_id: auth.login_token
purpose: "生成登录 token"
provides:
  - function: issue_token
consumes:
  - password_verifier.verify
input_schema:
  username: string
  password: string
output_schema:
  token: string
  expiry: datetime
mock_inputs:
  - username: "alice"
    password: "correct-password"
expected_outputs:
  - token: "<non-empty>"
    expiry: "<future datetime>"
integration_target:
  file: "auth/service.py"
acceptance:
  - "给定 mock input，输出符合 schema"
  - "模块不得直接访问真实外部服务"
```

### 2. Worker 黑盒验收

Worker 不再只拿“实现 auth 模块”这种大任务，而是拿：

`任务需求 + 接口规范 + mock input + expected output`

验收时不看 worker 内部过程，只看：

`给定输入 → 是否输出预期结果 → 是否遵守接口`

这能直接拦住“函数存在但没接入”“复盘章节有标题没内容”“模型选择写了不读”等问题。

### 3. Task 级拼接验收

模块完成后，必须进入拼接阶段：

`Module A output → Module B input → Task verify gate`

这里要检查：

接口 schema 是否匹配；
provides/consumes 是否闭合；
mock 数据能否贯穿；
真实入口是否调用新模块；
verification gate 是否跑的是拼接后的路径。

### 4. 批次级 E2E

Ralph 已经能做 Task 间 DAG 和批次建议，但批次完成后缺少独立行为断言。应新增 batch E2E manifest：

```yaml
batch_e2e:
  commands:
    - "cccc model suggest backend"
    - "cccc workflow run sample-af-task"
  assertions:
    - "model_runtime == codex"
    - "execution_engine == af"
    - "workflow.completed emitted only after verification_passed"
```

这个批次 E2E 不受 plan suppress_codes 控制，用来防止“plan 自己把检查关掉”。

---

## P4：调整 Solve Flow / E2E Flow 的关口

### Solve Flow

当前 Step 5 只看 pytest 退出码，应改成：

| 步骤                  | 改进                                                       |
| ------------------- | -------------------------------------------------------- |
| Step 1 理解           | 必须输出“原始症状、当前假设、待验证主路径”                                   |
| Step 2 计划           | plan 必须包含 behavior_evidence commands                     |
| Step 3 Codex review | 增加 call-chain、fallback、guard-ordering、default-drift 四类审查 |
| Step 4 gaps         | 不只记录缺口，还要生成 detection rule 草案                            |
| Step 5 execute      | pytest + 主路径命令 + 日志断言全部通过                                |
| Step 6 guide        | guide 只能记录规则，不能作为行为生效证据                                  |

### E2E Flow

当前 E2E 很多步骤只查文件和关键词，应改成：

| 步骤                   | 改进                                          |
| -------------------- | ------------------------------------------- |
| Step 4 review        | 检查 WORKFLOW_EVALUATION 每个章节的实质内容            |
| Step 6 improvement   | 已验证项必须引用具体证据文件                              |
| Step 7 retrospective | 检查八维复盘是否完整，并验证 rating 是否真的写入和被读取            |
| 全局                   | 自动断言 AF 是否执行、模型选择是否符合预期、是否有 silent fallback |

---

## 建议实施顺序

第一阶段先做 P0 + P1。目标是停止继续制造假完成，并让 AF、模型选择、复盘三条主链路真的闭合。

第二阶段做 P2。目标是把这次人工发现的问题转成 Ralph 自动规则，尤其是 DG-1、DG-3 和 suppress_codes 白名单化。

第三阶段做 P3。目标是回到蓝图：让 Foreman 不再直接把大任务丢给 Worker，而是拆成 ModuleSpec，用 mock I/O 做黑盒验收，再拼接成 Task。

第四阶段做 P4。目标是让 solve flow 和 E2E flow 不再依赖“看起来完成”，而是每一步都有行为证据。

---

## 最终验收标准

后续版本只有同时满足以下条件，才算真正改进完成：

1. 新增模块必须能从当前默认 entrypoint 追到真实调用链。
2. 所有 fallback 必须有可观测事件或 warning/error 日志。
3. 所有 high-risk 修复必须有行为证据命令，不只跑 pytest。
4. 已完成归档项必须引用具体日志、transcript 或命令输出。
5. AF E2E 中不再静默 legacy，worker terminal 回流后才完成。
6. 模型选择 E2E 中，默认执行类 worker 能通过 registry/rating 流程选到 codex。
7. WORKFLOW_EVALUATION 和 retrospective 不能靠标题、关键词、文件大小过关。
8. 一个真实 Task 能被拆成至少两个 Module，用 mock I/O 黑盒验收，再拼接通过 Task verify gate。

核心判断标准只有一个：不要再问“代码写了吗”，而要问“原始症状在真实主路径里消失了吗”。
