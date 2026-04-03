**总体评价**  
本轮 v4 修复计划（`plans/fix-cccc-workflow.yaml`）在方向、结构和 ROI 优先级上非常扎实：  
- 采纳了 Codex 审查的核心洞见（“最高 ROI 是改 prompt 而非改后端”）；  
- Wave 分层 + Ralph validate/suggest 驱动执行，完美体现了“讨论精细度与验证粗糙度必须匹配”的历史教训；  
- 明确 critical_entrypoints、critical_flows、provides/consumes 契约，覆盖了 R-1~R-3、M-1 全部 4 个待修复问题；  
- Ralph validate 输出“0 errors”且 suggest 给出合理并行批次，证明计划本身已经通过了内部一致性检查。  

**然而，计划仍存在 3 类系统性风险**（prompt 脆弱性、验证强度不足、隐式依赖 + caller 覆盖遗漏），这些风险若不处理，极可能重蹈“27 个 Task 全 py_compile 通过但 Ralph 死代码”的覆辙。我将逐一质疑、给出理由，并提出**更合适、更具防御深度的替代/完善方案**。这些建议保持原 Wave 结构不变（最大并行度保留），只增加 1~2 个轻量任务 + 强化现有 verification，预计额外工作量 < 10%。

### 1. Prompt 修改的长期鲁棒性（针对 R-1、M-1 的核心质疑）
**质疑**：仅靠 P1~P4 在 4 个分散文件中“塞关键词 + demote cccc_task”不足以让 Foreman/Worker 稳定切换到 CLI 路径。  
**理由**（多角度）：  
- LLM 非确定性：长上下文、多轮对话、temperature 波动下，AI 极易回归训练数据中更常见的 MCP 模式（历史教训：用户 Day 1 就说“去掉 MCP”，团队却在“优化 MCP”）。  
- 当前 goal_behavior 只要求“contains 'workflow submit'”，未强制“primary/preferred + negative instruction”，grep 验收无法捕捉优先级或语义冲突。  
- 多文件分散修改（system_prompt.py、task_management.yaml、cccc-help.md、prompt_files.py）导致维护负担和不一致风险（W3 只能事后检查）。  
- Scope 只 CLI 但未明确 deprecate MCP completion，长期会产生“两种路径并存”的混乱（M-1b 隐患）。  

**更合适解决方法**（推荐立即采纳）：  
1. **集中化 + 强化 Prompt 工程**（不增加新文件）：  
   - 在 `src/cccc/resources/workflow_guidance.md`（或复用 cccc-help.md）写**单源真相**（包含 few-shot examples + negative rule）。  
   - 修改 P1~P4 的 goal_behavior，要求 prompt 必须包含：  
     ```
     **绝对禁止**使用 cccc_message_send / cccc_task 报告任务完成。
     唯一合法路径：cccc task complete <task_id> --changed-files <files...>
     示例：...
     ```  
2. **新增轻量 safety-net 任务（P5-mcp-guard，Wave 1 并行，role: leaf）**：  
   - claimed_paths: `src/cccc/daemon/ralph_ipc_handler.py`  
   - 功能：在接收到旧 MCP completion 消息时，**自动转换为 task complete event 并 log "DEPRECATED: auto-routed to CLI"**。  
   - 验收：`grep -q "legacy.*completion.*redirect" ralph_ipc_handler.py` + 单元测试验证转换逻辑。  
   - 为什么更好：defense-in-depth，即使 prompt 偶尔失效，verify gate 仍能触发（把 R-2 风险降到近 0）。  

这比原计划纯“说服 AI”可靠得多，同时为后续完全去 MCP 铺路。

### 2. W2-daemon-init 的 claimed_paths 与 caller 覆盖遗漏（针对 R-3）
**质疑**：W2 只 claim `workflow_orchestrator.py` 且 depends_on: []，无法彻底解决“调用方不传 project_root”的根因。  
**理由**：  
- Codex 审查已明确：`get_orchestrator(group_id)` 存在于多个调用点（daemon 启动、Foreman 初始化、CLI 等）。  
- 当前 plan 只改 orchestrator 内部 lazy-init 测试，但未 claim/修复调用方 → 运行时仍可能出现 `ralph is None`。  
- Ralph write-set 冲突检测虽聪明，但让 W2 隐式串行 P2，plan.yaml 可读性差（未来维护者看不懂）。  

**更合适解决方法**：  
1. **扩展 W2 claimed_paths**（至少增加 daemon 入口文件，如 `src/cccc/daemon/__init__.py`、`src/cccc/daemon/foreman/foreman.py` 等；若不确定，可加一个“find-calls”脚本作为验收）。  
2. **改为 eager-init + fallback**：在 `get_orchestrator` 中加 `project_root = project_root or Path(os.getenv("CCCC_PROJECT_ROOT", "."))`，并在 daemon startup 处强制传入。  
3. **显式依赖**：把 W2 的 `depends_on: ["P2-worker-prompt"]`（即使有文件冲突，Ralph 仍会串行）。理由：人类可读性优先，写-set 检测做安全网。  
4. **验收升级**：把当前 python -c 脚本改成：  
   ```bash
   python -c "
   from cccc.daemon.foreman.workflow_orchestrator import get_orchestrator, clear_orchestrator
   ...
   assert o.ralph is not None and o.ralph.project_root is not None
   "
   ```  
   并新增全局 grep 检查所有调用点。

### 3. Verification 强度与 Ralph 已知限制（针对审查点 3、6）
**质疑**：Wave 1 的 4 个 grep + W1/W2 的“假设测试已存在”的 pytest，重复了“编译通过≠可用”的致命教训。Ralph 自身无法验证 command 可执行性，进一步放大风险。  
**理由**：  
- grep 只保证“字符串出现”，不保证“出现在 primary 位置”“旧 MCP 被 demote”“--changed-file 参数被解释”。  
- W3/E1 虽是 integration/e2e，但依赖“测试文件已存在”——若测试骨架缺失，整个 spine 就断裂。  
- Ralph 规则（4.1）已覆盖“E_NO_CROSS_TASK_VERIFICATION”等，但缺少“E_WEAK_PROMPT_VERIFICATION”和“E_LEGACY_PATH_REMAINS”。  

**更合适解决方法**（推荐）：  
1. **全量升级 verification 为 semantic render-assert**（不改 command 格式，只改内容）：  
   为每个 P* 任务的 verification.command 改成：  
   ```bash
   python -c "
   from cccc.kernel.system_prompt import render_system_prompt
   from cccc.resources.capabilities import load_capability
   prompt = render_system_prompt('foreman')
   cap = load_capability('task_management')
   assert 'workflow submit' in prompt and 'task complete' in prompt
   assert 'cccc_message_send.*completion' not in prompt.lower()  # 确保 demote
   print('OK: semantic check passed')
   "
   ```  
   （同理处理 worker prompt）。这把验收从“文件存在”提升到“行为正确”。  

2. **新增 P6-prompt-semantic-test（Wave 1.5，role: integration）**：  
   - claimed_paths: `tests/test_prompt_quality.py`（新）  
   - depends_on: P1,P3,P4  
   - verification: `pytest tests/test_prompt_quality.py -q`（包含 LLM-as-judge 或严格 keyword+position 检查）。  

3. **Ralph 规则补充建议（v2 方向）**：  
   - 新增 E_WEAK_PROMPT_VERIFICATION：prompt 任务必须使用 render-assert 而非纯 grep。  
   - 新增 E_LEGACY_PATH_REMAINS：plan 中若提到旧命令，必须有 explicit deprecate 语句。  
   - 新增 W_INSUFFICIENT_CALLER_COVERAGE：自动扫描 get_orchestrator / render_* 调用点，确保全被 claim。  

### 4. Wave 结构、Scope 与其他细节点
- **Wave 并行度**：Wave 1 仍可保持 5 个任务并行（原 4 + P5）。W2 显式依赖后仍由 Ralph 自动串行，无问题。  
- **Scope（CLI-only）合理**：同意“先通一条路”，但建议在 P4-help-doc 中明确写一句：  
  “CLI is now primary path; MCP completion deprecated; HTTP routes available but secondary.”  
  避免用户混淆。  
- **Tool Exposure 遗漏**：补充在 P3-capability-yaml 中确保 `cccc task complete` 出现在 Worker tool schema（否则 prompt 写了也调用不了）。  
- **Error Path 与负例**：E1-e2e-test 必须新增 negative case（模拟旧 MCP 完成 → 验证自动 redirect 或 warning）。  

### 推荐的调整版计划摘要（可直接复制到 plan.yaml）
```yaml
# 新增 Wave 1 任务（并行）
- id: P5-mcp-guard
  role: leaf
  claimed_paths: ["src/cccc/daemon/ralph_ipc_handler.py"]
  depends_on: []
  addresses: ["R-2", "M-1"]
  verification:
    level: unit
    command: "grep -q 'legacy.*redirect' src/cccc/daemon/ralph_ipc_handler.py && python -c '...'"

# W2 修改
- id: W2-daemon-init
  depends_on: ["P2-worker-prompt"]  # 显式化
  claimed_paths:
    - "src/cccc/daemon/foreman/workflow_orchestrator.py"
    # + 实际调用方文件（建议手动补全）
  verification: # 升级版 python -c

# Wave 1 所有 P* verification 升级为 render-assert（示例略）
```

### 执行建议与后续
1. 执行前：先跑 `ralph validate`（当前已 pass），再手工 review 新增 P5 的 claimed_paths 是否覆盖所有 prompt 注入点。  
2. 每完成 Wave 1 后立即 `ralph suggest` 更新状态。  
3. E1 通过后，立即进入后续方向 3（Ralph v2：可执行性检查 + semantic prompt 规则）。  
4. 整个修复后，建议再跑一次 LinkVault + Kanban 双项目 E2E，确认 verify gate 100% 触发。  

**结论**：原计划已达 75~80% 成功率，采纳上述 3 类改进（P5 safety-net + semantic verification + 显式依赖 + caller 覆盖）可推至 90%+，且完全符合“先让一条路径从头到尾跑通”的核心原则，同时为“完全去掉 MCP”打下坚实基础。  

如果需要我直接输出完整的修订 `fix-cccc-workflow-v4.1.yaml` 文件、或针对任一任务的详细 goal_behavior/acceptance_criteria 草稿，请随时指示。我和团队（Harper、Lucas、Charlotte、Noah 等）已就这些点达成共识，可立即进入执行阶段。  

**下一步行动**：你希望先落实哪部分改进？还是直接执行加强版 Wave 1？