# Ralph v5 审查汇总报告（合并版）

> 日期：2026-03-31
> 汇总范围：
> - `todo/gedt-5.md`
> - `todo/gedt-v5-adversrial.md`
> - `todo/gp-5.md`
> - `todo/gpp-5.md`
> - Codex 本轮审查（对话结论，未单独落盘）
>
> 纳入标准：
> 1. **可直接采纳**：已有足够文档/代码锚点支撑，可直接改规范、调优先级或进入实施。
> 2. **待进一步确认**：方向有价值，但还需要补设计、补样例或补验证后再落地。

---

## 一、汇总结论

- **可直接采纳**：8 项
- **待进一步确认**：8 项
- **本轮不纳入结论**：2 项

本报告只保留对 v5 方案真正有收敛价值的结论，不重复已经被现有代码覆盖的担忧，也不把缺乏文档支撑的最坏路径推演当成既成事实。

---

## 二、可直接采纳

### A1. `verification` 必须收敛为单一真相源

**来源**：Codex

**结论**：
v5 不能一边在计划层校验 `Plan.verification.command`，一边在运行时执行 `TaskRef.verification_command`，否则 `validate` 与真实执行会分叉。

**依据**：
- 计划模型使用结构化 `verification.command`：`src/cccc/ralph/models.py`
- 运行时任务契约仍使用 `verification_command`：`src/cccc/contracts/v1/ralph_ipc.py`
- 运行时验证实际执行的是 `task_ref.verification_command`：`src/cccc/daemon/foreman/ralph_service.py`
- 当前 CLI `ralph validate` 只走 `validate(plan)`：`src/cccc/ralph/cli.py`

**采纳建议**：
- 方案层明确“单一真相源”决策。
- 优先方案：runtime 直接消费结构化 `verification.command`。
- 次优方案：在 plan -> TaskRef 投影时做显式转换，并增加 round-trip 一致性测试，禁止两套字段继续独立演化。

### A2. RV-2 不能只看“当前文件系统”，必须合并“计划写入意图”

**来源**：`gpp-5`、`gedt-v5-adversrial`

**结论**：
如果 `validate` 发生在任务执行前，就不能仅因目标文件/符号“当前不存在”而直接报错；否则合法的新建文件、新建测试、新增符号任务会被误杀。

**依据**：
- 工作流明确是“先 validate，再执行”：`todo/问题清单-v5-ralph.md`
- `claimed_paths` 定义的是任务声称将修改的路径：`todo/问题清单-v5-ralph.md`
- RV-2 当前设计把文件存在性/符号存在性直接作为 error 条件：`todo/ralph-v5-implementation-spec.md`

**采纳建议**：
- 对 RV-2 引入“projected state / planned state”判断。
- 只有当目标当前不存在，且当前任务或其依赖闭包中也没人 claim 对应路径时，才报 `E_*`。
- 如果目标当前不存在，但已经被当前任务或上游任务 claim，降为 `hint` 或写入 `review_request.cannot_validate`。

### A3. RV-2 需要处理 wrapper / complex shell，不能留下低成本逃逸面

**来源**：`gedt-5`、`gedt-v5-adversrial`、`gp-5`、`gpp-5`、Codex

**结论**：
当前“复杂 shell 直接跳过、降为 hint”的设计过于宽松，真实命令又常被 `env`、`timeout`、`uv run`、`poetry run`、`python -m` 包裹；如果不做归一化和递归解析，RV-2 很容易被一层 wrapper 绕过。

**依据**：
- 规范明确把复杂 shell 记为 `W_VERIFICATION_COMPLEX_SHELL_SKIPPED`：`todo/ralph-v5-implementation-spec.md`
- 运行时仍用 `shell=True` 原样执行验证命令：`src/cccc/daemon/foreman/ralph_service.py`

**采纳建议**：
- 在形状匹配前增加 wrapper unwrap：
  - `env` / 临时环境变量
  - `timeout`
  - `uv run`
  - `poetry run`
  - `python -m`
- 对拆不出来的 opaque 命令，不应默认当“无害黑盒”处理。
- 至少对 `unit/integration/e2e` 级验证提高严格度：无法静态理解时进入 `review_request`，必要时升级为 warning/error。

### A4. RV-1 应从“未 claim 测试”改成“测试所有权 / 验证覆盖缺失”

**来源**：`gedt-5`、`gedt-v5-adversrial`、`gp-5`、`gpp-5`

**结论**：
直接把“关联测试文件未 claim”当成主要问题会污染 `claimed_paths` 的语义。`claimed_paths` 既表示修改意图，也参与并行冲突检测，不应逼着任务为了消警报去 claim 大量并未修改的测试文件。

**依据**：
- `claimed_paths` 在文档中定义为“该任务声称要修改的文件路径”：`todo/问题清单-v5-ralph.md`
- batch approval 会拒绝冲突写集：`src/cccc/kernel/workflow_state_engine.py`
- RV-1 当前设计直接检查“测试文件是否被任何 task claim”：`todo/ralph-v5-implementation-spec.md`

**采纳建议**：
- 将 RV-1 的主语义改成：
  - 发现关联测试；
  - 但当前 verification 未覆盖，或全计划没有明确测试所有权安排。
- 允许“源改动任务”和“测试适配任务”拆开。
- 只有在更强条件下才保留 warning，例如：
  - 测试已被当前 verification 明确执行；
  - 但全计划无人负责该测试的维护。

### A5. WF-NEW-3 之前必须先补 task-scoped 事件 / heartbeat 契约

**来源**：`gedt-v5-adversrial`、`gp-5`、`gpp-5`、Codex

**结论**：
“分配后 N 秒无 ledger 事件就报警”这个 MVP 过于粗糙。当前系统没有任务级 progress/heartbeat 事件，只有终态事件和内存态 actor status，直接做 silent/stalled 检测会高噪声。

**依据**：
- 文档当前 MVP 只说“无 ledger 事件则报警”：`todo/问题清单-v5-ralph.md`
- `TaskEvent` 只有 `completed` / `failed` 两种：`src/cccc/contracts/v1/ralph_ipc.py`
- `ActorStatus` 虽带 `current_task_id` / `progress_pct`，但目前只写进 `_RALPH_STATE` 内存：`src/cccc/daemon/ralph_ipc_handler.py`
- 现有状态机只有 started / reported_completed / failed / verification 结果，没有 heartbeat：`src/cccc/kernel/workflow_state_engine.py`

**采纳建议**：
- 先补最小任务事件契约：
  - `task_assigned`
  - `task_started`
  - `task_progress` 或 `heartbeat`
  - `task_completed`
  - `task_failed`
- 再基于任务级事件拆分三类检测：
  - actor offline
  - task silent
  - task stalled

### A6. Composition root 不能只靠 planner 手工预填 `critical_entrypoints`

**来源**：`gp-5`、Codex

**结论**：
v5 如果继续依赖计划生成器手工枚举 composition root，再复用现有 `E_CRITICAL_ENTRYPOINT_UNOWNED`，会复现 v4 那类“结构上过关、实际没有 wiring”的问题。

**依据**：
- v4 已明确暴露“没有任务负责 daemon startup wiring”：`todo/问题清单-v5-ralph.md`
- v5 仍声明“不新增 CCCC-specific core rule，只靠 planner discipline + critical_entrypoints”：`todo/ralph-v5-implementation-spec.md`
- 当前 validator 只能检查“已声明”的 critical entrypoints 是否被 claim：`src/cccc/ralph/validator.py`

**采纳建议**：
- 不把 CCCC 路径硬编码进 Ralph core。
- 但需要增加 repo-local policy 入口，例如：
  - `ralph_policy.yaml`
  - `ralph/policies/cccc.py`
  - 或模板生成时自动注入默认 composition roots

### A7. `project_root` 解析顺序要调整，不能默认等于 plan 所在目录

**来源**：`gedt-5`、`gpp-5`

**结论**：
如果 plan 放在 `.cccc/plans/`、`tmp/` 或其他生成目录，直接把 plan 所在目录当 `project_root` 会让 filesystem 规则产生大量假阴性/假阳性。

**依据**：
- 规范当前写法是“`project_root` 默认取 plan 所在目录”：`todo/问题清单-v5-ralph.md`、`todo/ralph-v5-implementation-spec.md`

**采纳建议**：
- 解析优先级改为：
  1. CLI 显式 `--project-root`
  2. 配置
  3. git root
  4. 最后才 fallback 到 plan 所在目录
- CLI 输出中打印“本次使用的 `project_root`”和“filesystem 校验是否启用”。

### A8. `E_COVERS_UNKNOWN_TASK` / `E_COVERS_WITHOUT_DEP_ORDER` 应前移到更早波次

**来源**：`gedt-5`、`gpp-5`

**结论**：
这两条规则是确定性、低噪声、低成本的结构规则，应早于 RV-3 / RV-4 / 早期 checkpoint 这类更启发式的规则落地。

**依据**：
- 当前规范把两条规则放在 Wave 2：`todo/ralph-v5-implementation-spec.md`
- 这两条本质只是集合/图闭包运算，不依赖文件系统，也不依赖启发式推断。

**采纳建议**：
- 将 `E_COVERS_UNKNOWN_TASK`、`E_COVERS_WITHOUT_DEP_ORDER` 提前到 Wave 1 或 Wave 1.5。
- 先把强不变量补齐，再叠加 noise 更高的 workspace / heuristic 规则。

---

## 三、待进一步确认

### B1. RV-3 是否应改成“证据分层”模型

**来源**：`gp-5`、`gpp-5`

**价值**：
当前 `W_COVERS_CLAIM_UNVERIFIABLE` 很容易把“黑盒 integration/e2e 测试没在命令里显式点名路径”误判为“无法覆盖”。

**需确认的问题**：
- 是否引入强/中/弱证据分层：
  - 强：`covers.paths`、明确测试节点、直接 import
  - 中：critical flow 对齐、contract 对齐
  - 弱：命令字符串或文件名弱相关
- integration/e2e 在什么条件下默认降为 hint 或转入 `review_request`

### B2. 早期集成 checkpoint 的触发条件是否应从绝对阈值改成图指标

**来源**：`gedt-5`、`gp-5`、`gpp-5`

**价值**：
当前 `len(tasks) >= 5 + all verifier are sink + min_depth >= 2` 的规则偏刚性，可能漏掉深链，也可能误伤浅图。

**需确认的问题**：
- 是否改用：
  - 图最长路径比例
  - fan-in / fan-out 风险
  - 最早 cross-task verifier 在 critical path 上的位置
- 需要先拿一批真实计划样本跑对比，观察误报/漏报变化。

### B3. `filesystem_validator` 是否要在致命结构错误后短路

**来源**：`gedt-5`

**价值**：
先跑纯结构，再决定是否继续做 filesystem 检查，有利于避免在破损 DAG 或缺字段条件下继续下钻。

**需确认的问题**：
- 哪些 error 应视为“fatal enough to short-circuit”：
  - `E_DEP_CYCLE`
  - `E_MISSING_CLAIMED_PATHS`
  - `E_MISSING_VERIFICATION`
  - 还是更窄范围
- 是否会因此丢失本可独立报出的 workspace 错误

### B4. `python -c "from X import Y"` 分析器如何处理标准库 / 第三方包

**来源**：`gedt-v5-adversrial`

**价值**：
如果 AST 解析默认只会走 repo-local 文件，就可能把合法的 stdlib / site-packages import 错报为模块缺失。

**需确认的问题**：
- repo-local module：继续 AST / re-export 检查
- 非 repo-local module：
  - 用 `importlib.util.find_spec`
  - 还是直接降级为 `cannot_validate`
- 是否允许环境依赖差异带来的噪声进入 `warning`

### B5. 是否要给 `ValidationIssue` 增加 `layer / confidence / suggested_fix`

**来源**：`gpp-5`

**价值**：
结构性错误、workspace 启发式、运行时观测结果混在同一 `severity` 体系里，长期会稀释 warning/hint 的可信度。

**需确认的问题**：
- 当前 `ValidationIssue` 模型只有 `code / severity / message / task_ids / evidence`：`src/cccc/ralph/models.py`
- 新增字段会不会导致 CLI、JSON 输出、测试和下游消费方同步改动过大

### B6. `review_request` sidecar 是否应提前到 Wave 1.5

**来源**：`gp-5`、`gpp-5`

**价值**：
如果 Ralph 与 Codex 的互补性已经在 v4/v5 讨论中被反复验证，那么极简 sidecar 越早上线，审查收益越早释放。

**需确认的问题**：
- Wave 1.5 是否只输出最小字段：
  - `cannot_validate`
  - `opaque_commands`
  - `related_tests`
  - `focus_paths`
  - `focus_tasks`
- 还是维持 Wave 4，避免同时引入过多接口面

### B7. `filesystem_validator` 是否需要共享 `WorkspaceIndex`

**来源**：`gpp-5`

**价值**：
Wave 1 之后会叠加多条 workspace 规则；如果每条规则都独立扫盘、独立 parse AST，性能和复杂度会快速恶化。

**需确认的问题**：
- 是否抽出统一缓存：
  - path exists
  - module map
  - pytest node map
  - AST cache
- 还是先按规则分散实现，待规则稳定后再收敛

### B8. RV-1 是否需要在 direct import 之外增加更弱的低成本召回

**来源**：`gedt-5`

**价值**：
只做 direct import 检查会漏掉一部分常见项目结构下的关联测试。

**需确认的问题**：
- 是否增加“路径镜像推导”
- 是否增加“核心符号名弱搜索”
- 这些召回是否只进入 hint / `review_request`，而不进入 warning

---

## 四、本轮不纳入结论

### X1. “WF-NEW-3 会自动重派并造成脑裂写坏文件”

**来源**：`gedt-v5-adversrial`

**不纳入原因**：
当前规范写的是“报警”，不是“自动重派”或“自动踢出后重分配”。这条担忧有工程直觉价值，但按现有文档证据，severity 被打高了。

### X2. “并行写冲突需要新增 `E_CONCURRENT_WRITE_CONFLICT`”

**来源**：`gedt-5`

**不纳入原因**：
现有批次批准流程已经拒绝冲突写集：`src/cccc/kernel/workflow_state_engine.py`。这不是 v5 新增缺口，最多是现有保护是否还要前移到 plan validate 的问题。

---

## 五、建议回贴到 v5 规范的最小改动清单

如果只做最小收敛，优先改以下 6 条：

1. 明确 `verification` 单一真相源，消除 plan/runtime 双字段分叉。
2. RV-2 改为“当前文件系统 + 计划写入意图”联合判断。
3. 为 RV-2 增加 wrapper unwrap，收紧 complex shell 的放行条件。
4. 重写 RV-1 语义，避免把“关联测试”直接等同于“必须 claim 测试文件”。
5. 将 `E_COVERS_UNKNOWN_TASK` / `E_COVERS_WITHOUT_DEP_ORDER` 前移。
6. 在 WF-NEW-3 之前先补 task-scoped heartbeat / progress 事件契约。

这 6 条改完，v5 的主要风险会从“规则越来越多但核心边界仍可分叉”收敛到“先把强不变量和关键观测面补齐，再叠加启发式规则”。
