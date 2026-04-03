# Ralph v5 改进实施规范

> 日期：2026-03-31
> 来源：Claude + Codex 四轮讨论共识
> 状态：**已被 `问题清单-v5-ralph.md` §五 取代**（经 5 源审查后修订，Wave 结构/RV-1 语义/RV-2 projected state/验证字段统一等均有重大变更）
> 前置：v4 已归档，Ralph 基础架构 + 12 类结构规则已运行

---

## 一、架构决策

### 验证器分层

当前 `validator.py` 是纯 `Plan -> ValidationReport`，无副作用，CLI 和测试都依赖此性质。
RV-1/RV-2 需要读项目文件系统（AST 解析、文件存在性检查），属于新类别："plan + filesystem" 校验。

**决策：新增 `filesystem_validator.py`，`validator.py` 负责聚合。**

```
src/cccc/ralph/
├── validator.py              # 纯结构校验：Plan -> ValidationReport（现有）
├── filesystem_validator.py   # 文件系统校验：Plan + project_root -> list[ValidationIssue]（新增）
└── models.py                 # 数据模型（现有）
```

- `validator.py`：保留现有纯结构校验 `validate(plan)`
- `validator.py`：新增聚合入口 `validate_with_project(plan, *, project_root: Path)`
- `filesystem_validator.py`：暴露 `validate_filesystem(plan, *, project_root: Path) -> list[ValidationIssue]`
- CLI `ralph validate`：调用 `validate_with_project()`，`project_root` 默认取 plan 所在目录或显式参数
- **不做**"没传 project_root 就静默跳过 FS 校验"——纯结构校验和带项目上下文校验是两个显式入口

### AST 解析错误处理

当 `filesystem_validator.py` 尝试 AST 解析源文件遇到语法错误时：
- **(a) Skip + hint**：跳过 AST 相关检查，记录 `cannot parse file X; skipped AST-based symbol check`
- 不升级为 error（语法正确性是 Ralph 运行时内建 py_compile 的职责）
- 不静默吞掉

---

## 二、实施波次

### Wave 1（并行实施）

RV-2 和 RV-1 互相独立，可并行实现。**若只能先合一个，优先 RV-2。**

#### RV-2：验证命令静态预检（10 个诊断码）

目标：在计划校验阶段预检 `verification_command`，拦截"命令本身指向不存在对象"的假验证。

**实现方式**：`shlex.split()` 解析命令，按形状匹配白名单，逐条静态检查。

| # | 形状 | 检测方式 | 检查内容 | 失败结果 | 诊断码 |
|---|------|---------|---------|---------|--------|
| 1 | `python -m py_compile path.py` | `shlex` 解析后匹配 `python -m py_compile` | 文件存在且是 `.py` | error | `E_VERIFICATION_PYCOMPILE_TARGET_MISSING` |
| 2 | `python -c "from X import Y"` | `python -c` + AST 必须是单个 `ImportFrom`，禁止 `Call` | 模块 X 可解析；Y 在模块顶层存在，或包 `__init__.py` 明确 re-export（一跳） | error | `E_VERIFICATION_IMPORT_MODULE_MISSING` / `E_VERIFICATION_IMPORT_SYMBOL_MISSING` |
| 3 | `pytest tests/foo.py` | `shlex` 匹配 `pytest` 或 `python -m pytest`，首个非 flag 参数 | 文件存在 | error | `E_VERIFICATION_PYTEST_TARGET_MISSING` |
| 4 | `pytest tests/foo.py::test_fn` | 同上，node id 解析 `file::name` | 文件存在；顶层函数或类存在 | error | `E_VERIFICATION_PYTEST_NODE_MISSING` |
| 5 | `pytest tests/foo.py::Class::method` | 同上，node id 解析 `file::Class::method` | 文件存在；类和方法存在（参数化后缀 `[...]` 先剥掉） | error | `E_VERIFICATION_PYTEST_NODE_MISSING` |
| 6 | Shell 复合命令（`&&`, `\|\|`, `;`, `\|`, 重定向, `cd ... && ...`） | token 中出现 shell operator | 不做静态预检 | hint | `W_VERIFICATION_COMPLEX_SHELL_SKIPPED` |
| 7 | 平凡命令（`true`, `:`, `echo "ok"`, `printf ok`） | 精确匹配 trivial 命令族 | 判定为可疑弱验证 | warning | `W_VERIFICATION_TRIVIAL_COMMAND` |
| 8 | `python -m py_compile`（与 Ralph 内建重复） | 检测到 verification_command 只是 py_compile | 重复 Ralph 内建检查，增量覆盖为零 | warning | `W_VERIFICATION_REDUNDANT_PYCOMPILE` |
| 9 | `python -c` 含执行语义（method call、属性链等） | `python -c` 但 AST 不属于 import-only 白名单 | 不检查方法存在性，视为 opaque | warning | `W_VERIFICATION_PYTHON_C_OPAQUE` |
| 10 | 其他未知形状 | fallback | 不报错，声明无法静态验证 | hint | `W_VERIFICATION_SHAPE_UNKNOWN` |

**明确 out-of-scope：**
- `grep` 系命令：变体过多（`-q`, `-r`, `-E`, `--include`, stdin, glob），不单列错误码，走 fallback
- `python -c "import X; X.method()"` 的方法存在性检查：v5 不做
- dry-run sandbox：v5 不做（环境依赖/import 副作用/venv 差异噪声大），可作后续增强

#### RV-1：未 claim 测试文件检测（3 个诊断码）

目标：当任务 claim 了源文件，检测与之相关的测试文件是否也被某个任务 claim。

**实现方式：两阶段——grep 召回 + AST 判定**

1. 对 `claimed_paths` 中的每个 Python 源文件，提取 module 名/文件 stem
2. 用 grep/regex 在 `tests/` 下扫描候选测试文件（按 module 名、import 关键字）
3. 对候选文件做 AST 解析，确认是否有直接 `import`/`from ... import`
4. 检查该测试文件是否在计划中任何 task 的 `claimed_paths` 中

**分级报警：**

| 情况 | 严重度 | 诊断码 |
|------|--------|--------|
| `tests/**/test_*.py` 直接导入被 claim 的源文件，但测试文件未被任何 task claim | warning | `W_UNCLAIMED_TEST_FOR_SOURCE` |
| `conftest.py` 导入被 claim 的源文件，但未被 claim | hint | `W_UNCLAIMED_CONFTEST_FOR_SOURCE` |
| 发现动态导入（`importlib.import_module`, `__import__`, 动态模块名拼接），无法可靠判定 | hint | `W_DYNAMIC_TEST_IMPORT_OPAQUE` |

**scope 限制：**
- 只检查直接 import + 一跳 `__init__.py` re-export
- **不做** transitive call-chain / import graph（"测试通过 public API 间接打到该模块"）
- **不做** 运行时/动态导入推断、monkeypatch/fixture 注入间接关系
- `conftest.py` 在 verification 是 `pytest tests/` 这类广覆盖命令时，severity 升级为 warning
- RV-1 定位为 **低成本召回型 warning**，不是完整行为依赖分析

---

### Wave 2（Wave 1 稳定后）

内部顺序：先做 `covers.tasks` 图谱规则（E_COVERS_UNKNOWN_TASK, E_COVERS_WITHOUT_DEP_ORDER），再做依赖它们的 RV-4 降级、RV-3、早期 checkpoint。

#### `covers.tasks` 完整性规则（2 个诊断码）

| 诊断码 | 规则 | 严重度 |
|--------|------|--------|
| `E_COVERS_UNKNOWN_TASK` | `covers.tasks` 中出现未知 task id | error |
| `E_COVERS_WITHOUT_DEP_ORDER` | `covers.tasks` 中的 task 必须在当前任务的**自反传递依赖闭包**内（允许覆盖自己）。不设 integration 例外。 | error |

**传递闭包计算**：从任务的 `depends_on` 递归展开。对典型计划规模（10-30 tasks）复杂度可接受。

#### RV-4：`W_VERIFICATION_BEHAVIOR_MISMATCH` 降级（行为变更，无新码）

若任务 T 被某个下游 `integration/e2e` 任务合法地 `covers.tasks` 包含，则从 warning 降为 hint。

#### RV-3：`W_COVERS_CLAIM_UNVERIFIABLE`（1 个诊断码）

仅在 `covers.tasks` 完整性通过后评估。若 A 声称 covers B，但 A 的 `verification.command` 静态引用与 A 的 `claimed_paths` 都无法接触到 B 的 `claimed_paths`，报 warning。

#### 早期集成检查点（1 个诊断码）

| 诊断码 | 规则 | 严重度 |
|--------|------|--------|
| `W_NO_EARLY_INTEGRATION_CHECKPOINT` | 见下方定义 | warning |

**定义：**
- `checkpoint`：`verification.level in {integration, e2e}` 且 `len(covers.tasks) >= 2` 且该任务不是 sink（有下游任务依赖它）
- `cross-task verifier`：`verification.level in {integration, e2e}` 且 `len(covers.tasks) >= 2`
- `task_depth(t)`：从任一 root 到 t 的最长依赖链长度，root 深度为 0

**触发条件（全部满足才报 warning）：**
1. `len(plan.tasks) >= 5`
2. 至少存在一个 cross-task verifier
3. 所有 cross-task verifier 都是 sink（终点叶子）
4. `min(task_depth(v) for v in cross_task_verifiers) >= 2`

这样 "3 leaf + 1 final e2e" 不会报；宽而浅的 fan-in 也不会报；真正"很晚才首次汇合验证"的计划才报。

---

### Wave 3（独立阶段）

#### WF-NEW-3：静默/停滞 agent 检测

**架构**：push 采样 + pull 判定混合

- Actor 继续 push `ActorStatus.updated_at`（现有）
- Ralph/automation 定时 pull `_RALPH_STATE + workflow assignments + ledger` 做离线/停滞判定
- 最小实现落点：现有 `sweep_stalled_tasks()` + `engine.py:807` 空骨架 `_run_heartbeat_sweep()`

**v5 scope：仅做 silent/stalled agent 检测**
- task 分配后 N 秒无 ledger 事件 → 报警
- **不做** path deviation（agent 用 `cccc send` 直接分配而非等 workflow）
- **不做** state inconsistency（worker 报 complete 但 task 非 running）
- 后两项需要更强的事件契约，否则误报高

---

### Wave 4（后续）

| 项目 | 描述 |
|------|------|
| `review_request` sidecar | Ralph 在 ValidationReport 之外产出 `review_request.yaml`（`cannot_validate`, `risk_codes`, `focus_paths`, `focus_tasks`, `focus_questions`, `evidence`）。v5 是 sidecar 文件，Codex 消费但 Ralph **不解析** Codex 输出。结构化闭环（Ralph 读 Codex 结果回写验证状态）是 **v6**。 |
| RO-1 | Flow segment ownership — 关键流每段是否有人负责 |
| RO-2 | Schema 契约匹配 — 超越名字匹配，检查类型兼容性 |
| RO-3 | Role-based rules — 按 role 强化 integration/verification 任务检查 |
| RO-4 | Ready 排序 — 按解锁下游数量排优先级 |
| RV-5 | 语义依赖推断 — goal_behavior 关键词与 plan 外文件交叉检查 |

---

## 三、Composition Root 覆盖策略

**v5 不新增 CCCC-specific 的 core rule。**

在 CCCC 中，composition root = 对象实例化、handler 注册、CLI/tool surface 装配发生的文件：
- `workflow_orchestrator.py`（实例化 WorkflowEngine + RalphService）
- `ralph_ipc_handler.py`（task_event 接入 orchestrator 主路径）
- `cli/main.py`（注册 workflow/task complete）
- `daemon/server.py`
- `ports/mcp/toolspecs.py`

**v5 做法**：plan-generation discipline + 现有 `E_CRITICAL_ENTRYPOINT_UNOWNED` 规则。
计划生成器负责将这些 root 预填进 `critical_entrypoints`，Ralph 用现有规则检查。

---

## 四、诊断码总表

### Wave 1（17 个新码中的 13 个）

| 码 | 来源 | 严重度 | 类型 |
|----|------|--------|------|
| `E_VERIFICATION_PYCOMPILE_TARGET_MISSING` | RV-2 | error | filesystem |
| `E_VERIFICATION_IMPORT_MODULE_MISSING` | RV-2 | error | filesystem |
| `E_VERIFICATION_IMPORT_SYMBOL_MISSING` | RV-2 | error | filesystem |
| `E_VERIFICATION_PYTEST_TARGET_MISSING` | RV-2 | error | filesystem |
| `E_VERIFICATION_PYTEST_NODE_MISSING` | RV-2 | error | filesystem |
| `W_VERIFICATION_COMPLEX_SHELL_SKIPPED` | RV-2 | hint | filesystem |
| `W_VERIFICATION_TRIVIAL_COMMAND` | RV-2 | warning | filesystem |
| `W_VERIFICATION_REDUNDANT_PYCOMPILE` | RV-2 | warning | filesystem |
| `W_VERIFICATION_PYTHON_C_OPAQUE` | RV-2 | warning | filesystem |
| `W_VERIFICATION_SHAPE_UNKNOWN` | RV-2 | hint | filesystem |
| `W_UNCLAIMED_TEST_FOR_SOURCE` | RV-1 | warning | filesystem |
| `W_UNCLAIMED_CONFTEST_FOR_SOURCE` | RV-1 | hint | filesystem |
| `W_DYNAMIC_TEST_IMPORT_OPAQUE` | RV-1 | hint | filesystem |

### Wave 2（4 个新码 + 1 行为变更）

| 码 | 来源 | 严重度 | 类型 |
|----|------|--------|------|
| `E_COVERS_UNKNOWN_TASK` | 新增 | error | structural |
| `E_COVERS_WITHOUT_DEP_ORDER` | 新增 | error | structural |
| `W_NO_EARLY_INTEGRATION_CHECKPOINT` | 新增 | warning | structural |
| `W_COVERS_CLAIM_UNVERIFIABLE` | RV-3 | warning | structural |
| `W_VERIFICATION_BEHAVIOR_MISMATCH` 降级 | RV-4 | (行为变更) | structural |

**总计：17 个新诊断码 + 1 个行为变更**

---

## 五、关键设计约束（来自 findings 实践教训）

| Finding | 对应设计决策 |
|---------|-------------|
| #1 compile≠functional | `W_VERIFICATION_REDUNDANT_PYCOMPILE` — 拦截只做 py_compile 的假验证 |
| #2 文件拆分创建死代码 | `W_NO_EARLY_INTEGRATION_CHECKPOINT` — 检测"全并行无早期集成"的计划 |
| #11 Ralph+Codex 互补 | `review_request` sidecar — Ralph 显式输出"我检查不到的区域"给 Codex |
| #13 结构校验≠无缺陷 | 新增 filesystem 校验层 — 从"只看 plan 结构"扩展到"看 plan 引用的真实对象" |

---

## 六、不做清单（v5 明确 out-of-scope）

- grep 命令静态预检（变体过多）
- `python -c` 中方法存在性检查
- dry-run sandbox 执行
- transitive test dependency（通过 public API 间接测试）
- Codex 审查结果的结构化回写（v6）
- CCCC-specific composition root 硬编码规则
- Path deviation / state inconsistency 运行时检测（需更强事件契约）
