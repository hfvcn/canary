根据 2026-06-06 的项目问题汇总，你当前的问题不应再按“修 AF、修模型选择、修复盘”这类单点 bug 处理，而应按“验收体系失效”处理。现状的核心偏差是：项目把“代码存在 + 单元测试通过”当作完成，但蓝图真正要求的是“主路径行为改变 + 黑盒输入输出验收 + 分层集成验证 + 失败不静默降级”。文档里已经把这个差距归纳为 Layer 3 到 Layer 6/7 的断层：当前归档停在代码和测试层，真正完成应看到 E2E 行为改变，并且失败时阻断或产生可观测信号。 

## 总体改进方向

后续计划应分成三条主线：

第一，先改“完成定义”。任何涉及运行时、集成、模型选择、调度、复盘、评价闭环的任务，不允许再以“代码写了、测试绿了、文档更新了”归档。完成必须提供主路径证据，例如实际 CLI 输出、daemon 日志、ledger event、E2E transcript、归档证据文件。

第二，补齐 Ralph/Flow 的强制检查能力。当前最关键的盲区是：validate 能看到文件和 import，但不能判断修改是否落在当前活跃执行路径；能看到 fallback 代码，但不能要求 fallback 有事件或告警；能看到 gate 函数，但不能判断 gate 是否在副作用之前执行。文档中列出的 DG-1 到 DG-4 应作为下一轮最高优先级的规则补齐。

第三，回到蓝图，把缺失的“中间层”补上。蓝图要求的是 Task 内模块拆分、接口规范、模拟输入输出、模块拼接、批次级 E2E；现实是大任务直接交给 Worker，最后只跑 pytest。假完成反复出现，正是因为缺少这层黑盒验收和拼接验收。

---

# M0：立即止血，冻结“假完成”归档入口

目标：先阻止新的假完成继续进入 full tracker。

需要改的规则：

| 改动            | 具体要求                                                                                              | 通过条件                                        |
| ------------- | ------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| 归档状态分层        | 把状态拆成 `implemented`、`path-connected`、`runtime-ready`、`behavior-verified`、`fail-closed`、`archived` | 只有 `behavior-verified` 或 `fail-closed` 可以归档 |
| 禁止浅层 verified | `pytest passed` 只能证明 implemented，不能证明 completed                                                   | 归档项必须附行为证据                                  |
| 行为证据定位化       | 每个归档项必须写明命令、输出片段、日志文件、ledger event 或 transcript 位置                                                | 不能只写“E2E 行为确认”这类关键词                         |
| 保留原始症状        | 每个修复项必须记录“最初失败现象”                                                                                 | 验证时必须回到这个症状复测                               |
| 阻止自我抑制        | 与假完成直接相关的 warning 不允许被 `suppress_codes` 关闭                                                        | `ralph validate` 对这些 code 保持 warning/error  |

第一批应设为不可 suppress 的 code：

`W_VERIFICATION_BEHAVIOR_MISMATCH`

`W_INTEGRATION_NO_PRODUCTION_CALL_EVIDENCE`

`W_INTEGRATION_TASK_SHALLOW_VERIFICATION`

这些正是文档中指出的假完成最后防线，但当前可以被 plan 自己关闭。

归档模板建议改成：

```yaml
issue_id:
  original_symptom:
  claimed_fix:
  changed_paths:
  active_entrypoint:
  active_path_trace:
  runtime_conditions:
  verification_commands:
  expected_behavior:
  observed_behavior:
  fallback_behavior:
  evidence_locations:
  regression_test:
  archive_decision:
```

没有这份 evidence bundle，不允许从短清单移入 full archive。

---

# M1：优先补 Ralph/Flow 检查规则

目标：把 Codex 能人工发现的问题，固化成 Ralph 自动规则。

## 1. DG-1：active-path reachability

这是最高优先级。规则要判断：task 声称修复运行时行为时，修改的 symbol 是否从当前默认 entrypoint 可达。不能只检查 import 或测试 cover。

应覆盖这些场景：

| 场景                                  | 应触发的问题                    |
| ----------------------------------- | ------------------------- |
| 新函数写好了，但 orchestrator 没调用           | `fix-on-dormant-path`     |
| AF 路径改了，但当前默认仍走 legacy              | `inactive-engine-path`    |
| 只改 compile path，execute path 没变     | `compile-without-execute` |
| guide 改了，但运行时代码不读                   | `doc-only-behavior-claim` |
| record/write 端有了，但 read/consume 端没有 | `write-without-consumer`  |

验收用例应包括一个“AF 组件存在但主路径不调用”的 fixture。这个 fixture 必须让 `ralph validate` 失败，而不是只靠 Codex review 发现。

## 2. DG-3：observable-fallback

所有 fallback、return False、except-pass、silent degrade，都必须产生可观测信号。

要求：

```text
fallback 分支必须满足至少一个：
1. ledger event
2. >= WARNING 日志
3. workflow 状态标记
4. 显式 fail-closed
```

对于 AF，不能再出现 `CCCC_AF_ENGINE_ENABLED=1` 但实际静默回到 legacy 的情况。若 AF 不可用，要么阻断，要么发出明确事件，例如：

```text
af.execution_unavailable
af.runtime_not_ready
af.fallback_to_legacy_explicit
```

文档中已经指出 AF fallback 只靠 debug/warning、不阻断、不告警 Foreman，是导致“默认启用但实际 legacy”的关键逃逸点。

## 3. DG-4：guard-ordering

声称“阻断 X”的检查，必须在 X 的副作用之前执行。

典型规则：

| 声称阻断的对象                | gate 必须位于               |
| ---------------------- | ----------------------- |
| `workflow.completed`   | emit completed event 之前 |
| 写入 archive             | archive commit 之前       |
| actor dispatch         | dispatch side effect 之前 |
| model rating 生效        | registry write/read 之前  |
| WORKFLOW_EVALUATION 完成 | terminal event 之前       |

这能防止 `_check_section_substantive` 这类函数“存在但放在 workflow.completed 之后”，导致门形同虚设。文档中也明确把 guard 在副作用下游列为 validate 当前无法检测的缺口。

## 4. DG-2：semantic-default consistency

同一语义默认值不能散落在多个文件里各自硬编码。模型 runtime 默认值就是例子：一个地方改成 codex，另一个地方仍是 claude，会造成默认值漂移。

建议建立 registry：

```yaml
semantic_defaults:
  executor_runtime:
    canonical: codex
    allowed_overrides:
      - security_review
      - frontend_aesthetic_review
    definitions:
      - agent_pool.py
      - assignment_actor_registration.py
      - actor_cli.py
```

当某个 task 修改其中一个定义点时，Ralph 必须提示其它同语义定义点也要检查。

## 5. verification 行为证据门

plan 的 verification 不能只写：

```bash
pytest ...
```

涉及运行时行为的 task，必须至少包含一个主路径命令，例如：

```bash
cccc model suggest backend
cccc workflow run ...
grep "execution_engine: af" daemon.log
grep "[af] execution done" daemon.log
cccc group events <group_id>
```

Solve Flow 的 Step 5 当前只看 Codex 输出和 pytest 退出码，这正是 Layer 3 假完成的入口。

---

# M2：闭合三条当前主路径问题

## A. AF 引擎：从“能启动”改成“正确完成”

AF 当前不再只是未接入问题，v59 之后已经暴露出新的 AF-07：AF 激活后出现 fire-and-forget / auto-complete 死循环。后续目标不是“让 AF 默认开关为 1”，而是让 AF 成为真实可用的默认执行路径。

需要完成：

1. 禁止 `auto_complete_after_send=True` 把“已发送”当“已完成”。
2. AF node completion 必须等待 worker terminal event。
3. `execute_bundle` 必须产生可审计的 ledger trace。
4. attempt_id、lease、terminal 回流、重复派发保护必须作为 AF runtime invariant。
5. legacy fallback 必须显式配置或显式事件化。
6. 每次 E2E 报告必须显示 `execution_engine: af` 或明确的 fallback reason。
7. 若 AF 启用但不可用，默认应 fail-closed，而不是自动降级 legacy。

验收命令必须能证明：

```text
CCCC_AF_ENGINE_ENABLED=1
workflow started
execution_engine: af
[af] dispatch started
[af] worker terminal received
[af] verification passed
[af] execution done
no duplicate dispatch
no silent legacy fallback
```

文档记录显示，AF 线索经历了“组件写好但未调用”“加 env var 但路径没变”“compile 但不 execute”“接线 bug 修复后又暴露 auto-complete 死循环”等多轮假完成，因此这一项必须用真实 daemon/E2E 证据关闭。

## B. 模型选择：不要再靠 guide 文本，必须让选择链路生效

当前问题不是 guide 没写“codex 默认”，而是 Foreman 可以忽略 guide，且真实 actor 创建路径不一定消费 model registry / rating。文档里已经指出 guide 文本建议不是约束，Foreman 可以显式 `--runtime claude`，同时代码 fallback 也曾偏向 claude。

改进方向：

1. `cccc model suggest` 成为 actor 创建前的标准读端。
2. `select_model_for_task` 必须读取 `enabled`、`strengths`、`best_for`、`foreman_rating`、`cost_tier`。
3. task type 与 strengths 的命名空间要统一，例如 `backend`、`general_execution`、`code_change`、`security_review`。
4. codex 作为默认执行 runtime，claude 只作为审查、复杂推理、前端审美等例外。
5. Foreman 手动传 `--runtime claude` 不必强行禁止，但必须记录 override reason 和 selector-bypass event。
6. E2E 复盘必须统计实际 actor runtime 分布，并说明每个 override 是否合理。

验收标准：

```text
cccc model suggest backend        -> codex
cccc model suggest general        -> codex
cccc model suggest code_review    -> codex 或 reviewer policy 指定模型
cccc model suggest security_review -> claude 或指定 security reviewer
disabled model 不进入候选
actor creation event 包含 selected_by=model_selector 或 override_reason
```

这条线不能再通过“guide 已更新”关闭，必须通过实际 `model suggest` 输出和 actor runtime 分布关闭。

## C. WORKFLOW_EVALUATION / 复盘：空章节必须阻断 workflow.completed

当前复盘和 evaluation 的问题本质也是“函数存在但未接入”。文档指出 `_check_placeholder_content()` 存在但未被调用，`_workflow_evaluation_feedback_lines()` 只生成标题和空行，随后 workflow.completed 直接触发。

改进要求：

1. `_check_placeholder_content()` 或 `_check_section_substantive()` 必须在 `workflow.completed` 之前执行。
2. 空章节、只有标题、只有关键词、只有模板句，均不得通过。
3. Step 7 复盘必须覆盖固定维度：

   * runtime 选择是否合理；
   * codex / claude 分工是否符合策略；
   * agent 数量是否导致串行化；
   * security reviewer 是否真正执行安全任务；
   * reviewer 是否留下可审计证据；
   * Foreman 决策是否正确；
   * model rating 是否写入且被后续读取；
   * 对 guide / prompt / Ralph rule 的改进建议。
4. `record_model_usage()` 不只写 registry，还要能影响下一次 model selection。
5. E2E check 不再只看关键词，而要检查每个维度有实质文本和证据引用。

验收标准：

```text
空 WORKFLOW_EVALUATION.md -> workflow.completed 被阻断
只有标题的复盘 -> step-7 check failed
有 rating 但无 runtime 分析 -> step-7 check failed
有 review 文件但未采纳/未解释 Codex findings -> review step failed
```

---

# M3：落地蓝图中间层：模块化拆分 + 接口 + 黑盒验收

这是最关键的结构性改进。当前所有检查都在“计划层”和“最后 E2E 层”之间缺一层。蓝图里的中间层应变成真实数据结构和执行流程，而不是文档描述。

建议新增 `module_specs`：

```yaml
tasks:
  - id: T1
    goal: ...
    modules:
      - id: T1.M1
        purpose:
        interface:
          provides:
            name:
            input_schema:
            output_schema:
          consumes:
            - name:
              schema:
        mock_inputs:
          - name:
            value:
        expected_outputs:
          - name:
            value:
        black_box_tests:
          - command:
            expected:
        integration_contract:
          upstream:
          downstream:
        completion_evidence:
          required:
            - module_io_passed
            - schema_contract_passed
            - self_test_fresh
```

新的执行层级：

| 层级       | 谁负责                  | 验收方式                             | 不允许通过的情况         |
| -------- | -------------------- | -------------------------------- | ---------------- |
| Module 级 | Worker               | 给定 mock input，输出 expected output | 只提交代码、无 I/O 证据   |
| Task 级   | Foreman / Ralph      | 模块拼接 + consumes/provides 契约测试    | 模块各自通过但拼不上       |
| Batch 级  | Orchestrator / Ralph | 当前 frontier 全部完成后跑批次 E2E         | 单个 task 绿但批次行为不变 |
| Global 级 | E2E Flow             | 全流程场景验证                          | tracker 归档但症状仍复现 |

这样可以直接堵住当前几类假完成：

| 假完成类型                     | 蓝图中间层如何拦截                                 |
| ------------------------- | ----------------------------------------- |
| AF 组件写好但 orchestrator 不调用 | Task 级拼接验证失败                              |
| compile 了但没有 execute      | Module/Task 验收缺少 expected output          |
| model rating 只写不读         | Batch E2E 中 `model suggest` 输出不符合预期       |
| WORKFLOW_EVALUATION 空章节   | 黑盒输出对照失败                                  |
| 默认 runtime 改一处漏一处         | interface/default registry consistency 失败 |
| guide 改了但行为没变             | Batch E2E 行为断言失败                          |

Worker 的输入也要收窄。Worker 不应拿到“修整个系统”的大任务，而应拿到：

```text
模块目标
接口规范
模拟输入
预期输出
允许修改路径
禁止修改路径
验收命令
失败时上报格式
```

这会减少“自己理解需求、自己定义完成、自己写测试证明自己完成”的空间。

---

# M4：建立固定 E2E 回归场景

后续不要每轮临时设计 E2E。应建立一组固定“假完成回归场景”，每次 solve flow 结束后跑。

建议至少 6 个场景：

| 场景                       | 预期                                                                     |
| ------------------------ | ---------------------------------------------------------------------- |
| AF 默认启用                  | 日志显示 `execution_engine: af`，出现 `[af] execution done`，无 legacy fallback |
| AF runtime 缺失            | fail-closed 或明确 `af.execution_unavailable` event，不允许静默 legacy          |
| 模型选择 backend task        | `cccc model suggest backend -> codex`，actor runtime 主要为 codex          |
| Foreman override runtime | 允许但必须有 selector-bypass event 和复盘说明                                     |
| 空 WORKFLOW_EVALUATION    | workflow.completed 被阻断                                                 |
| 假集成 fixture              | 新模块存在但主路径不可达时，DG-1 失败                                                  |

每个场景输出一个 evidence bundle：

```yaml
scenario_id:
  command:
  expected:
  actual:
  pass:
  logs:
  events:
  regression_lock:
```

归档时引用 bundle，而不是引用自然语言结论。

---

# M5：改造 Solve Flow / E2E Flow 的通过条件

## Solve Flow

当前 Step 1 无检查，Step 5 只看 pytest，这是不够的。建议改成：

| Step                | 新增要求                                       |
| ------------------- | ------------------------------------------ |
| Step 1 Understand   | 必须产出“原始症状、活跃路径假设、需要证明的行为变化”                |
| Step 2 Plan         | plan 必须含 behavior verification，不得只含 pytest |
| Step 3 Codex Review | review findings 必须被采纳、显式拒绝或登记为 deferred    |
| Step 4 Gaps         | 缺口必须生成 validate rule 或 flow check 任务       |
| Step 5 Execute      | 必须跑主路径证据命令                                 |
| Step 6 Guide        | guide 只能记录已由规则/证据证明的内容，不能作为完成依据            |

## E2E Flow

当前 E2E Flow 多处只看文件存在、关键词和大小。建议改成：

| Step                 | 改动                                                              |
| -------------------- | --------------------------------------------------------------- |
| Step 4 Review        | WORKFLOW_EVALUATION 必须实质化，空章节失败                                 |
| Step 6 Improvement   | verified 项必须引用 evidence bundle                                  |
| Step 7 Retrospective | 必须检查 runtime、team、reviewer、rating read/write、Foreman 自评         |
| Step 8 Cleanup       | cleanup 之外还要确认没有 orphan actor / repeated dispatch / stale lease |

---

# 推荐优先级

按 ROI 和阻断假完成能力排序：

1. **先做 M0：归档冻结 + evidence bundle + suppress 白名单化。**
   这是止血层，立刻减少新假完成进入 tracker。

2. **再做 M1 的 DG-1 和 DG-3。**
   DG-1 能拦住“代码写了但主路径不可达”；DG-3 能拦住“失败静默回退”。这两个覆盖 AF、模型选择、评价闭环的大部分逃逸模式。

3. **并行修 M2 的 AF-07、模型选择读端、评价阻断。**
   这三条是当前实际 E2E 暴露的问题，必须用真实路径证据关闭。

4. **随后推进 M3 蓝图中间层。**
   先从一个 task 类型试点，例如 model selection 或 WORKFLOW_EVALUATION，建立 module spec、mock I/O、expected output、拼接测试，再推广到 AF 和通用任务。

5. **最后固化 M4/M5。**
   把 E2E 场景和 Flow 通过条件变成长期回归机制，避免每次靠用户追问才发现问题。

---

# 后续执行的完成标准

后续每个问题只有满足以下条件，才算完成：

```text
1. 原始症状被重新复现或明确记录；
2. 修改点从当前默认 entrypoint 可达；
3. 运行时条件在 E2E 环境中满足；
4. 主路径行为发生可观察变化；
5. fallback 不静默；
6. 失败用例会失败，修复后会通过；
7. 归档项引用具体 evidence bundle；
8. Codex review 发现已采纳、拒绝或转成 tracker item。
```

核心原则：以后不要再问“代码有没有写完”，只问“原始症状是否在真实主路径中消失”。这才与蓝图的黑盒验收和分层集成设计一致。
