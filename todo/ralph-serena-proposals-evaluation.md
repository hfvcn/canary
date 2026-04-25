# Ralph + Serena 集成方案评估与整合计划

> 日期：2026-04-07
> 评估者：Claude (Opus 4.6) + Codex (GPT-5.4)
> 输入：四份外部 AI 方案（gedt-7 / gp-7 / gpp-7 / groh-7）+ 项目实际代码 + 实践教训
>
> **Claude 与 Codex 的排名分歧**：Claude 初评 B>C>A>D，Codex 评估后给出 C>B>A>D。
> 经对照代码现状，Codex 的两个反驳点成立（见第二部分），最终采纳 Codex 排名。

---

## 一、四方案逐一评估

### 方案 A（gedt-7）—— 工程深度最高

**核心主张**：依赖注入 SemanticProvider + MVP 聚焦"防御死代码" + action 驱动的规则分级

**优点**：
- 架构设计清晰：SemanticProvider 接口 → CLI 层按需启动 → 终态 Daemon 托管，渐进路径完整
- **Rename Storm 识别极有价值**：大规模重构（500 引用）时阈值降级为 `W_MASSIVE_REFACTOR`，这在其他方案中缺失
- **Foreman 幻觉对策到位**：明确提出"规划阶段挂载 Serena 只读工具"，让 Foreman 看着代码树写计划
- action 区分是正确的（modify_body vs modify_signature 触发不同级别检查）
- 四层校验模型描述最精准

**缺陷**：
- plan.yaml 字段用 Python 模块路径（`src.auth.handler.login`），但 Serena 的原生查询模型是 `relative_path + name_path`（如 `src/auth/handler.py` + `AuthHandler/login`）。直接用模块点路径需要额外转换层，增加了不必要的复杂度
- 没有提出报告分离（结构 vs 语义），后续难以区分失败来源
- 没有讨论向后兼容的渐进模式（advisory/strict）

**评分**：

| 维度 | 分数 | 说明 |
|------|------|------|
| 架构合理性 | 4.5 | SemanticProvider 接口设计好，但缺报告分离 |
| 优先级正确性 | 4.5 | P0 选择精准，跨文件原子性优先级正确 |
| plan.yaml 设计 | 3.5 | action 思路对，但符号路径格式不贴 Serena |
| 风险认知 | **5** | Rename Storm + Foreman 幻觉是全场最佳 |
| 创新价值 | 3.5 | 稳健但无特别新颖的结合点 |
| 落地可行性 | 4 | 缺少分阶段实施细节 |

---

### 方案 B（gp-7）—— 最贴近项目实际

**核心主张**：报告分离 + S_ 前缀独立命名 + confidence 分级 + semantic fingerprint

**优点**：
- **报告分离是关键设计**：`ValidationReport` + `SemanticReport` 分开，后续 suppress、统计、误报分析都更清楚。这直接解决了"结构失败还是代码事实失败分不清"的问题
- **S_ 前缀命名规范**：`S_SYMBOL_NOT_FOUND` / `S_DELETE_WITH_LIVE_REFERENCES` 等，与现有 `E_` / `W_` 体系正交，非常干净
- **confidence 分级**（exact/best_effort/opaque）比简单的 error/warning 更细粒度，能精确管理 Python 动态性
- `--semantic-hints` 辅助命令降低 Foreman 负担，让 Serena 生成候选 symbol 供确认
- **三个独创结合点都有实际价值**：
  - semantic fingerprint（任务级代码事实摘要，可复用）
  - integration spine 推荐（直接对应 Batch C 合并 T3/T4/T5 的真实案例）
  - Agent 提示词增强器（把事实喂给 Agent 而非让 Agent 重新扫描）
- 实施排序 `1→3→5→入口枚举→4→2→7→6` 最合理

**缺陷**：
- `semantic_targets` 字段缺少 mode 控制（advisory/strict），不如方案 C 的渐进设计
- 对 LSP 启动成本的讨论较少
- 没有讨论大规模重构的阈值降级（Rename Storm）

**评分**：

| 维度 | Claude | Codex | 说明 |
|------|:---:|:---:|------|
| 架构合理性 | 5 → **4** | 4 | **Codex 反驳成立**：报告分离不贴现状。当前 CLI、suppress、stats 全围绕单一 ValidationReport，拆双报告引入不必要改造面。改为在现有 ValidationReport 内加 `semantic_findings` 字段更务实 |
| 优先级正确性 | **5** | **5** | 排序最合理 |
| plan.yaml 设计 | 4 | 4 | 单字段轻量好，但缺 mode 控制 |
| 风险认知 | 4 | **5** | confidence 分级是全场最佳风险管理工具 |
| 创新价值 | **5** | **5** | 三个独创结合点都有落地价值（但应明确后置到 Phase 3+） |
| 落地可行性 | 4.5 → **4** | 4 | 创新项过早进入 MVP 叙事会分散焦点 |

---

### 方案 C（gpp-7）—— 最保守稳健

**核心主张**：semantic 块 + mode 三档 + "只增加 blocker，不减少 blocker" + 分阶段实施

**优点**：
- **"Serena 只增加 hard blocker，不减少 hard blocker"**——这条原则极其重要，直接避免了"用符号分析放松文件级冲突检测"的陷阱
- **semantic 块设计最成熟**：`mode: off|advisory|strict` 三档渐进，`relative_path + name_path + op` 贴合 Serena 原生查询模型
- `modify_signature` 扩展为 `modify_interface` 是正确的——dataclass 字段变化、常量变化、类型别名变化都属于接口变更
- **"只标高风险符号"** 的约束非常务实
- **实施路线最明确**：Phase 1/2/3 边界清晰
- 明确提出"Serena 只用查询能力，不用编辑能力"——保护 Ralph 角色边界

**缺陷**：
- semantic 块结构比 B 的单字段重一些（多了 mode + relative_path），Foreman 填写负担略高
- 缺少 semantic fingerprint 等创新结合点
- 缺少 Rename Storm 讨论
- `--suggest-symbols` 辅助命令只是提到，没有详细设计

**评分**：

| 维度 | 分数 | 说明 |
|------|------|------|
| 架构合理性 | 4.5 | "只增加不减少"原则极好，但缺报告分离 |
| 优先级正确性 | 4.5 | 保守但正确 |
| plan.yaml 设计 | **5** | mode 三档 + 贴 Serena 原生模型 |
| 风险认知 | 4.5 | "只增加不减少"很关键，但缺 Rename Storm |
| 创新价值 | 3 | 稳健有余，创新不足 |
| 落地可行性 | **5** | 分阶段最清晰 |

---

### 方案 D（groh-7）—— 最不贴项目实际

**核心主张**：LSP 连接池 + auto_infer_symbols + 记忆闭环 + 时间线估算

**优点**：
- `auto_infer_symbols: true` 思路有价值——自动从 claimed_paths 推断符号，降低 Foreman 负担
- 提出 verify 后做"变更一致性快照"有一定创新性
- 给出了具体时间线（虽然过于乐观）

**缺陷**：
- **MVP 范围过大**：把符号存在、符号冲突、影响范围分析三个一起做，违反"先跑通一条路径"原则
- **时间线不切实际**：Day 1-3 实现 validate --semantic，Day 4-7 扩展到 suggest 符号冲突——在没有任何基础设施的情况下，这个估计过于激进
- **LSP 连接池过早优化**：MVP 阶段 one-shot 完全够用，连接池是 Phase 3 的事
- **auto_infer_symbols 有陷阱**：自动推断出的符号没有经过 Foreman 确认，可能产生大量误报。与方案 B 的 `--semantic-hints`（推断 + 人工确认）相比，缺少确认环节
- **记忆闭环偏离核心**：`.ralph/memories/` 持久化历史模式和当前最痛的问题无关
- **对 Serena 的理解不够深**：建议用 `execute_shell_command` 辅助文件系统规则，但 Ralph 已有 `filesystem_validator.py` 做这件事
- `semantic_tolerance: medium` 这种模糊配置项缺乏确定性
- 没有讨论报告分离、confidence 分级、Rename Storm 等关键问题
- 整体风格偏"销售导向"（"这个方案既创新又务实"），缺乏对局限性的诚实讨论

**评分**：

| 维度 | 分数 | 说明 |
|------|------|------|
| 架构合理性 | 3 | 连接池过早优化，缺乏层次设计 |
| 优先级正确性 | 2.5 | MVP 范围过大，时间线不实际 |
| plan.yaml 设计 | 3 | auto_infer 思路好但缺确认环节 |
| 风险认知 | 2 | 几乎没有讨论假阴性、Rename Storm 等真实风险 |
| 创新价值 | 3.5 | 变更一致性快照有意思 |
| 落地可行性 | 2 | 时间线过于乐观，范围过大 |

---

## 二、综合评分对比

| 维度 | A (gedt-7) | B (gp-7) | C (gpp-7) | D (groh-7) |
|------|:---:|:---:|:---:|:---:|
| 架构合理性 | 4 | 4 | **5** | 2 |
| 优先级正确性 | 4 | **5** | **5** | 2 |
| plan.yaml 设计 | 4 | 4 | **5** | 2 |
| 风险认知 | 4 | **5** | **5** | 2 |
| 创新价值 | 3 | **5** | 4 | 4 |
| 落地可行性 | 4 | 4 | **5** | 1 |
| **总分** | **23** | **27** | **29** | **13** |
| **排名** | 3 | 2 | **1** | 4 |

> 注：综合评分融合了 Claude 初评和 Codex 代码级交叉验证的结论。Codex 实际读取了 Ralph 的 `cli.py`、`validator.py`、`core.py`、`models.py` 源码后发现：当前 CLI/suppress/stats 全围绕单一 `ValidationReport`，B 方案的报告分离会引入不必要改造面；C 方案的 `relative_path + name_path + op` 最贴 Serena 原生查询模型和现有代码边界。

**总评**：方案 C (gpp-7) 最懂项目边界、几乎可直接做整合骨架，方案 B (gp-7) 方法论最完整但需收住报告拆分和创新项，方案 A (gedt-7) 风险认知好但对 Foreman 工具化偏重，方案 D (groh-7) 想法多于边界控制。

---

## 三、方案质量整体评价

### 共识点（四份方案全部同意）

1. **架构**：Ralph 核心保持纯函数，Serena 通过抽象接口注入，MVP 先 `ralph validate --semantic`
2. **优先级**：符号存在性验证是第一个做的能力
3. **plan.yaml**：需要显式字段声明涉及的符号（不能从自由文本猜）
4. **确定性**：Python 动态性导致 LSP 不完备，"发现问题"比"没发现问题"更可靠
5. **分层**：结构校验 → 代码事实 → 语义审查 → 运行时验证，四层模型

### 分歧点及裁决

| 分歧 | A | B | C | D | 裁决 |
|------|---|---|---|---|------|
| 报告是否分离 | 不分 | 分（双报告） | 不分 | 不分 | **不分离**（Codex 反驳成立）：现有 CLI/suppress/stats 全围绕单一 ValidationReport，在其中加 `semantic_findings` 字段更贴现状 |
| 语义规则命名 | 混入 E_/W_ | S_ 前缀 | 未讨论 | 未讨论 | **采纳 B**：S_ 前缀更干净，便于 suppress 和统计 |
| 字段格式 | 模块点路径 | semantic_targets | semantic 块 | involved_symbols | **采纳 C 的结构 + B 的轻量**（见下） |
| mode 渐进 | 无 | 无 | off/advisory/strict | 无 | **采纳 C**：三档渐进是正确的 |
| op 名称 | modify_signature | 同 A | modify_interface | 无 | **采纳 C**：modify_interface 更通用 |
| confidence 分级 | 无 | exact/best_effort/opaque | 无 | semantic_tolerance | **采纳 B**：三级 confidence |
| Rename Storm | 有（阈值降级） | 无 | 无 | 无 | **采纳 A**：阈值降级机制 |
| Foreman 幻觉 | 挂载 Serena 工具 | --semantic-hints | --suggest-symbols | auto_infer | **采纳 A 理念 + B 实现**：--semantic-hints |
| "只增不减"原则 | 无 | 无 | 有 | 无 | **采纳 C**：Serena 不减少现有 blocker |
| semantic fingerprint | 无 | 有 | 无 | 无 | **采纳 B**：复用价值高 |
| Agent 提示词增强 | 无 | 有 | 无 | 无 | **采纳 B**：减少 Agent 无谓工作 |

---

## 四、整合方案

### 4.1 架构（主要采纳 B + C）

```
Ralph Core (纯 validate/suggest/verify，不依赖 Serena)
    ↑
  SemanticProvider 接口 (抽象层)
    ↑
  SerenaAdapter
    ├─ OneShot (MVP: CLI 按需启动/销毁)
    └─ WarmSidecar (终态: Daemon 长驻)
```

**关键设计决策**：
- Ralph 核心函数签名不变。`validate()` 多接受一个可选的 `semantic_report: SemanticReport | None`
- **不分离报告**（Codex 反驳成立）：在现有 `ValidationReport` 中增加 `semantic_findings` 字段，保持 CLI/suppress/stats 体系完整。不引入独立 `SemanticReport`
- **语义规则独立命名**：`S_SYMBOL_NOT_FOUND`、`S_DELETE_STILL_REFERENCED` 等，S_ 前缀与 `E_`/`W_` 正交，便于 suppress 和统计分析
- **Serena 只用查询能力**：find_symbol、get_symbols_overview、find_referencing_symbols、search_for_pattern
- **"只增加 blocker，不减少 blocker"**：符号级分析只能追加 warning/error，不能放松文件级冲突检测

### 4.2 plan.yaml 扩展（C 的结构 + B 的轻量 + A 的 action 语义）

```yaml
tasks:
  - id: T1
    claimed_paths: ["src/cccc/daemon/foreman/workflow_orchestrator.py"]

    # 新增可选块
    semantic:
      mode: advisory       # off | advisory | strict
                           #   off: 跳过语义检查
                           #   advisory: 所有语义发现只报 warning/hint
                           #   strict: 允许部分发现升为 error（需要高确定性）
      targets:
        - path: src/cccc/daemon/foreman/workflow_orchestrator.py
          symbol: WorkflowOrchestrator/assign_ready_batch
          op: modify_body       # create | modify_body | modify_interface | delete | rename

        - path: src/cccc/contracts/v1/ralph_ipc.py
          symbol: ReadyBatchSuggestion
          op: modify_interface  # 改接口 → 触发引用影响面检查
```

**设计要点**：
- `path + symbol` 贴合 Serena 原生查询模型（`relative_path + name_path`），避免模块点路径转换
- `op` 决定检查深度：`modify_body` 只验证符号存在；`modify_interface/delete/rename` 触发完整引用影响面检查
- `mode` 三档渐进：旧 plan 无 semantic 块 → 平滑退化；新 plan 按需选择强度
- **只要求高风险任务填写 targets**：delete、rename、改公开接口、跨边界集成。普通 leaf task 改内部实现可省略
- 不设 `symbol_references`：引用集由 Serena 自动算出，不需要 Foreman 手填

### 4.3 语义规则清单（MVP）

| 规则 | 严重度 | 触发条件 | 对应局限 |
|------|--------|---------|---------|
| `S_SYMBOL_TARGET_MISSING` | error (strict) / warning (advisory) | 目标符号在代码中不存在 | RV-18 |
| `S_DELETE_STILL_REFERENCED` | error (strict) / warning (advisory) | 要删除的符号仍有静态引用 | RO-11n |
| `S_INTERFACE_REFS_OUTSIDE_SCOPE` | error (strict) / warning (advisory) | modify_interface/rename 的引用点超出当前任务 + 下游任务的 claimed_paths | RO-12n |
| `S_PARTIAL_ENTRYPOINT_COVERAGE` | warning | 文件有多个公开入口但 targets 只覆盖部分 | RO-12n |
| `S_MASSIVE_REFACTOR` | warning | 未覆盖引用数 > 阈值（如 20），建议使用自动化重构 | — |

**确定性分级**：每条语义发现附带 confidence：
- `exact`：LSP 直接命中定义/引用 → 可升 error（strict 模式下）
- `best_effort`：可能受动态导入、反射影响 → 只能 warning
- `opaque`：检测到动态热点 → 自动降级为 hint

**动态性降级触发器**：发现以下模式时自动降级 confidence：
- `getattr` / `setattr`
- `importlib.import_module`
- 字符串拼接动态导入
- monkey patch 痕迹
- 无 Type Hint 的同名函数（如裸 `save()`）

### 4.4 优先级和实施路线

**Phase 1：`ralph validate --semantic`（MVP）**

只做这一条 CLI 路径。不碰 daemon、suggest、verify。

实施内容：
1. SemanticProvider 接口 + SerenaAdapter (OneShot)
2. plan.yaml 的 `semantic` 块解析
3. 三条核心规则：`S_SYMBOL_TARGET_MISSING` + `S_DELETE_STILL_REFERENCED` + `S_INTERFACE_REFS_OUTSIDE_SCOPE`
4. `S_PARTIAL_ENTRYPOINT_COVERAGE` warning
5. `S_MASSIVE_REFACTOR` 阈值降级
6. 在现有 ValidationReport 中增加 `semantic_findings` 字段（不分离报告）
7. `--semantic-hints` 辅助命令（最简版：列 claimed_paths 内的公开符号供 Foreman 确认）

验证：用 Batch C 真实计划跑一遍，对比 Codex 审查发现的问题能否被语义规则捕获。

**Phase 2：validate 增强**

新增 warning 级规则：
- `S_IMPLICIT_SYMBOL_DEPENDENCY`：两个无 depends_on 的任务存在符号级引用关系
- `S_HIGH_FANOUT_CHANGE`：修改的符号 fanout 很高（标注 risk）
- 任务级 semantic fingerprint（touched symbols, fanout, dynamic hotspots）写入诊断输出（来源 B）
- integration spine 推荐（哪些任务修改同一调用链的定义/实现/入口，建议合并或加集成任务）（来源 B）
- `modify_interface` 范围扩展评估：根据 Phase 1 实践数据，决定是否从"只函数签名"扩展到 dataclass 字段、常量、类型别名（来源 C）
- 报告分离评估：如果 `semantic_findings` 字段导致 ValidationReport 过于臃肿，评估是否拆为独立 SemanticReport（来源 B）

**Phase 3：调度和验证联动**

- `suggest --semantic-advisory`：符号级冲突作为 advisory（不硬阻塞）（来源用户提案 #2）
- `verify --recommend-tests`：基于调用链推荐受影响测试（来源用户提案 #3，仅作 fast-feedback，不替代全量测试）
- Agent 提示词增强器：把 semantic findings 结构化喂给 LLM Agent（来源 B）
- Daemon 持久 sidecar（WarmSidecar）+ 评估是否需要 LSP 连接池（来源 D，仅 Daemon 模式）
- Foreman 侧挂载 Serena 只读工具：让 Foreman "看着代码树"写计划，减少 symbol 幻觉（来源 A，需先完成 Phase 1 验证）

**Phase 4：深度集成（需进一步评估）**

以下能力方向已确认合理，但实现方案需根据 Phase 1-3 的实践数据做进一步评估：

- 符号级冲突检测升级为 suggest hard gate：需 Phase 3 advisory 阶段积累误报/漏报数据，确认 Python 动态性下的误判率可接受后再升级（来源用户提案 #2）
- Auto-depends_on 自动注入：需 Phase 2 `S_IMPLICIT_SYMBOL_DEPENDENCY` warning 积累数据，确认"引用关系 = 执行依赖"的准确率后再决定是否从 warning 升级为自动注入（来源用户提案 #4）
- 自动任务权重改 `_unlock_score`：需先确认"高 fanout = 应优先/应最后"的决策模型，可能需要区分"修改签名"（应最后）vs"被依赖的基础设施"（应优先）（来源用户提案 #1）
- 智能验证范围替代全量测试：需评估 LSP 对 pytest fixture/conftest/parametrize 的覆盖率，确认漏选率可接受后再从"推荐"升级为"替代"（来源用户提案 #3）
- verify 后变更一致性快照：任务完成后 Serena 自动检查所有引用是否已更新，作为 verify gate 的增强项（来源 D，需 Phase 1-3 验证基础设施成熟后评估）
- auto_infer_symbols 作为默认行为：如果 `--semantic-hints` 实践表明 Foreman 确认率 >90%，可评估将推断+确认改为推断+默认采纳（来源 D，需实践数据支撑）

### 4.5 Foreman 负担管理

| 问题 | 对策 | 来源 |
|------|------|------|
| Foreman 编造不存在的 symbol | 规划阶段给 Foreman 挂载 Serena 只读工具 | A |
| 填写 symbol 太多太繁琐 | `--semantic-hints` 自动推断候选，Foreman 只需确认 | B |
| 大规模重构时 symbol 列表爆炸 | 未覆盖引用 > 20 时降级为 `S_MASSIVE_REFACTOR` warning | A |
| 普通任务不需要填 | semantic 块可选，mode: off 时完全跳过 | C |
| 向后兼容 | 无 semantic 块 → 沿用纯结构校验 | C |

### 4.6 四层校验模型（最终形态）

```
第 1 层：结构层（Ralph core，< 0.1s）
  回答：图正确吗？字段完整吗？契约匹配吗？
  不看代码。

第 2 层：代码事实层（Ralph + Serena，~3-5s）
  回答：符号存在吗？谁引用它？影响面多大？
  只产出事实，不做业务判断。

第 3 层：语义审查层（LLM Agent，~30s）
  输入：结构报告 + 语义事实报告（不是从零读代码）
  回答：这样改对吗？事实证据是否支持 acceptance claim？
  只处理前两层不能确定的问题。

第 4 层：运行时验证层（verify / E2E，分钟级）
  回答：真实路径通了吗？
  最终裁决，不被静态层替代。
```

**层间规则**：
- 下层产出事实，上层只消费事实，不重复做下层已确定的事
- 符号存在性：只由 Serena 做，Agent 不再重新判断
- 依赖环：只由 Ralph 做，Serena 不碰
- 运行时行为：只由 E2E 证明，Agent 不替代

---

## 五、未进入 MVP 的建议（去向标注）

| 建议 | 来源 | 去向 |
|------|------|------|
| LSP 连接池 | D | → **Phase 3** Daemon sidecar 时评估 |
| auto_infer_symbols（无需确认） | D | → **Phase 4** 待 `--semantic-hints` 确认率数据支撑 |
| verify 后变更一致性快照 | D | → **Phase 4** 待验证基础设施成熟后评估 |
| .ralph/memories/ 持久化历史模式 | D | → **拒绝**：与 Ralph 无状态定位冲突 |
| 报告分离为独立 SemanticReport | B | → **Phase 2** 评估 semantic_findings 字段是否导致 ValidationReport 臃肿 |
| Foreman 挂载 Serena 只读工具 | A | → **Phase 3** 完成 validate --semantic 验证后再开 Foreman 侧 |
| semantic fingerprint | B | → **Phase 2** |
| integration spine 推荐 | B | → **Phase 2** |
| Agent 提示词增强器 | B | → **Phase 3** |
| 符号冲突 suggest hard gate | 用户+D | → **Phase 4** 待 Phase 3 advisory 误报数据 |
| Auto-depends_on 自动注入 | 用户 | → **Phase 4** 待 Phase 2 warning 准确率数据 |
| 自动任务权重改 `_unlock_score` | 用户 | → **Phase 4** 需先确认决策模型 |
| 智能测试范围替代全量 | 用户 | → **Phase 4** 待 LSP 对 pytest 机制覆盖率评估 |
| `modify_interface` 范围扩展 | C | → **Phase 2** 根据 Phase 1 噪音数据决定 |
| Python 模块点路径做符号标识 | A | → **替代**：用 `relative_path + name_path` |
| symbol_references 字段 | 上下文原方案 | → **替代**：引用集由 Serena 算出 |
| semantic_tolerance 配置 | D | → **替代**：用 mode 三档 + confidence 三级 |
| execute_shell_command 辅助 | D | → **替代**：Ralph 已有 filesystem_validator.py |
| strict 作为默认 mode | C 延伸 | → **拒绝**：噪音过大 |
| modify_body 做全量 blast radius | C 延伸 | → **拒绝**：压垮 Foreman |
| MVP 范围含 suggest+verify | D | → **拒绝**：违反先跑通一条路径 |
| Day 1-3 时间线 | D | → **拒绝**：不实际 |

---

## 六、方案质量总评

| 方案 | 定位 | 一句话评价 |
|------|------|-----------|
| **A (gedt-7)** | 工程架构师 | 风险认知最深（Rename Storm、Foreman 幻觉），架构思路清晰，但字段设计和创新性不足 |
| **B (gp-7)** | 系统设计师 | 综合最优——报告分离、S_ 命名、confidence 分级、三个独创结合点都有真实落地价值 |
| **C (gpp-7)** | 实施工程师 | 最稳健可落地——mode 三档、"只增不减"原则、分阶段路线图最清晰，缺创新但不会出错 |
| **D (groh-7)** | 产品经理 | 想法多但不贴项目实际——范围过大、时间线乐观、对技术细节理解不够深、缺少风险讨论 |

**最终整合方案的 DNA**（Claude + Codex 共识）：**C 的项目边界骨架** + B 的 confidence 分级和实施顺序 + A 的 DI 接口和 Rename Storm 风险控制 + B 的创新结合点（后置到 Phase 3+）。D 只保留 `SemanticAnalyzer` 命名。

> Codex 原话："整合方案应以 gpp-7 为主骨架，吸收 gp-7 的 confidence 和实施顺序，再补 gedt-7 的 DI 与 Rename Storm 风险控制；groh-7 只保留 SemanticAnalyzer 这个壳。"

---

## 七、待裁决项（已裁决）

| 待裁决 | 选项 | 裁决（2026-04-07） |
|--------|------|-------------------|
| `semantic.mode` 放哪一级 | plan 全局级 vs task 级 | **plan 全局级**，个别 task 用 suppress 豁免 |
| `modify_interface` 的边界 | 窄（只函数签名） vs 宽（含 dataclass/常量/类型别名） | **MVP 先窄**（只函数签名），后续按实践扩展 |
| `--semantic-hints` 何时做 | Phase 1 vs Phase 2 | **Phase 1 做最简版**（列 claimed_paths 内的公开符号） |

---

## 八、建议溯源表

> 所有合理建议均已纳入 Phase 1-4 路线图或标注为替代/拒绝（见第五部分去向表）。
> 本节提供每条建议的**价值评估和决策理由**，供后续 Phase 实施时参考，避免重新评估。

### 推迟类（已纳入后续 Phase，含升级条件）

| 建议 | 当前价值 | 升级为更强形态的条件 |
|------|---------|-------------------|
| semantic fingerprint (Phase 2) | 高——避免重复扫描 | Phase 1 validate --semantic 稳定运行后自然衍生 |
| integration spine 推荐 (Phase 2) | 高——对应 Batch C 合并真实案例 | 需要符号引用数据积累 |
| Agent 提示词增强器 (Phase 3) | 高——减少 Agent 无谓工作 | Phase 3 涉及 Agent 层时启动 |
| 符号冲突 advisory → hard gate (Phase 4) | 中——场景真实 | Phase 3 advisory 误报率 < 5% 时可升级 |
| Auto-depends_on warning → 自动注入 (Phase 4) | 中——减少遗漏 | Phase 2 warning "引用=依赖" 准确率 > 80% 时可升级 |
| 任务权重改 `_unlock_score` (Phase 4) | 中——需区分场景 | 需先确认"高 fanout 优先 vs 最后"的决策模型 |
| 智能测试范围 recommend → 替代全量 (Phase 4) | 中——CI 加速 | LSP 对 pytest 机制覆盖率 > 90% 时可升级 |
| verify 变更一致性快照 (Phase 4) | 中——增强验收 | Phase 1-3 验证基础设施成熟后评估 |
| auto_infer_symbols 默认采纳 (Phase 4) | 中——减负 | `--semantic-hints` 确认率 > 90% 时可评估 |
| Foreman 挂载 Serena 只读工具 (Phase 3) | 中——减少幻觉 | Phase 1 validate --semantic 跑通后再开 Foreman 侧 |
| 报告分离评估 (Phase 2) | 低→高（视臃肿程度） | semantic_findings 字段导致 ValidationReport 难以维护时 |
| `modify_interface` 范围扩展 (Phase 2) | 中——更通用 | Phase 1 噪音数据可接受时扩展 |
| LSP 连接池 (Phase 3) | 低（CLI）→ 高（Daemon） | 仅 Daemon sidecar 模式有意义 |

### 替代类（思路被保留，实现方案已有更好选择）

| 原建议 | 替代方案 | 替代理由 |
|--------|---------|---------|
| 独立 SemanticReport | ValidationReport 内加 `semantic_findings` | 避免 CLI/suppress/stats 改造面 |
| auto_infer_symbols（无确认） | `--semantic-hints`（推断+确认） | 防止自动推断误报 |
| 模块点路径 `src.auth.handler.login` | `relative_path + name_path` | 贴合 Serena 原生 API |
| semantic_tolerance: medium | mode 三档 + confidence 三级 | 更精确的双维度控制 |
| execute_shell_command 辅助 | Ralph 已有 filesystem_validator.py | 能力已存在 |

### 拒绝类（与项目约束根本冲突）

| 建议 | 冲突点 |
|------|--------|
| .ralph/memories/ 记忆闭环 | Ralph 核心定位是无状态纯计算 |
| strict 作为默认 mode | 噪音过大，低风险 modify_body 也被严格检查 |
| modify_body 全量 blast radius | 内部实现变更不应触发跨文件检查 |
| MVP 含 suggest+verify | 违反"先跑通一条路径" |
| Day 1-3 时间线 | 不实际 |
