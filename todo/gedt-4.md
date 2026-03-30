将 `Ralph` 从深埋于 Daemon 的死代码，剥离成一个**独立、无状态、文件驱动的契约校验引擎**，这是 CCCC 项目在应对“AI 协作黑盒化”和“代码幻觉”上迈出的决定性一步。



但在对 `plans/fix-cccc-workflow.yaml` 进行深度“沙盘推演”后，我们发现了 **3 个会导致流水线必定失败或产生假阳性的致命逻辑漏洞**。

以下是对您提出的 8 个审查问题的逐项剖析，并在文末提供了可直接使用的 YAML 修正补丁。

---

### 🚨 一、 核心质疑与致命漏洞指出

#### 漏洞 1：W2-daemon-init 的验证是“掩耳盗铃”，且必定遭遇写权限拦截（致命）
* **关联问题**：Q2 (遗漏文件), Q3 (验证有效性)
* **漏洞剖析**：
  R-3 的根因是“调用方没有传 `project_root`”。然而：
  1. **验证造假**：W2 的验证命令 `get_orchestrator('ralph-test', project_root=Path('.'))` **手动传入了正确的参数**！这就好比“报告指出插头没插上，你的验证方式是自己拿个新插头插进插座证明有电”。这个测试完美绕过了真实的 Bug 现场，即使 Worker 根本没修好 Daemon，测试也会绿，完美重演上次的悲剧。
  2. **无权修复**：既然要修复“那些不传参数的调用方”，W2 的 `claimed_paths` 却**只有** `workflow_orchestrator.py`。真正的调用方肯定在 `src/cccc/daemon/ralph_ipc_handler.py` 或启动文件 `server.py` 里。Worker 在执行时，会因为没有 Claim 这些文件而被 Ralph 直接拒绝写入！

#### 漏洞 2：W1 与 W2 之间存在隐藏的竞态崩溃风险（致命）
* **关联问题**：Q4 (依赖关系)
* **漏洞剖析**：
  计划中 W1 和 W2 没有直接依赖关系。由于 P2 占用了 orchestrator 文件，Ralph 把 W2 阻塞。当 P2 完成后，W1 和 W2 会在 Wave 2 中被并行调度。
  但是，W1 负责验证 Verify Gate (`apply_task_event -> verify_completion`) 的完整链路，**这条链路强依赖于 Ralph 已经被成功初始化（即 W2 的目标）**。如果 W1 和 W2 并行跑，W1 的集成测试会因为 Ralph 尚未初始化而必定崩溃！

#### 漏洞 3：M-1 的“软防线”挡不住 AI 的历史惯性（高危）
* **关联问题**：Q1 (覆盖关键问题)
* **漏洞剖析**：
  P1~P4 试图通过 System Prompt 和 YAML 文档来“软引导” AI 走向 CLI。但大模型对具体的 Tool Schema 有极强的依赖惯性。只要 MCP 中的 `cccc_task` 工具依然允许接收 `status='completed'`，大模型在面临长上下文截断或复杂状态时，极易无视 Prompt 约束，抄近道去用老的 MCP 工具。
  **修复**：“去 MCP 依赖”不仅要修新路，还要**物理封死老路**。

#### 漏洞 4：幽灵测试文件与 CLI 路由遗漏（高危）
* **关联问题**：Q2 (遗漏文件)
* **漏洞剖析**：
  1. W1 的测试命令是 `pytest tests/e2e/test_smoke_workflow.py`。如果要接通 Verify Gate，Worker 极大概率需要修改这个测试文件。但该文件**不在 W1 的 `claimed_paths` 中**，导致 Worker 无权写入测试用例。
  2. W1 漏了 `src/cccc/cli/task_cmds.py`（通常 `cccc task complete` 的路由在这里，而不是 `workflow_cmds.py`）。
  3. W1 漏了 `workflow_orchestrator.py`（接通 Verify Gate 必然需要修改状态机代码）。

---

### 💡 二、 剩余审查问题的明确答复

**Q5: Wave 结构是否允许最大并行度？**
非常优秀。Wave 1 并发改 Prompt 是完美的。但在修复上述漏洞后，W1 会被推到 Wave 3（因为必须等待 W2 修好基建），这也是逻辑上最安全的拓扑。

**Q6: Ralph 的检查规则是否有遗漏？**
**有两大遗漏，建议在 Ralph v2 补齐**：
1. **`E_UNCLAIMED_TEST_FILE`**：静态正则扫描 `verification.command` 里的文件路径（如 `pytest tests/...`），如果该文件在 Git 中不存在且未被本任务 Claim，直接报错。这能防住上述“幽灵测试”漏洞。
2. **`W_TAUTOLOGY_TEST` (同义反复验证警告)**：如果 `role: integration` 的任务仅仅使用 `python -c "import..."` 直调底层函数（甚至硬编码传参），抛出警告，要求必须通过 CLI/API/IPC 边界触发测试。

**Q7: 计划的 scope（仅 CLI，不含 HTTP）是否合理？**
**极其合理。** 完全契合“Walking Skeleton（行走的骨架）”原则。在核心状态机（Truth Source）未闭环前，切忌去搞 HTTP 表现层，收敛变量是当前唯一正确的做法。

**Q8: 已知限制是否可接受？**
**完全可接受。** Ralph 当前的核心价值是“建立不可变的 YAML 契约”，强迫所有的“暗箱操作”显式化。验证命令不可执行的限制，正是目前需要 Claude/Codex 联合审查机制介入的绝佳理由。

---

### 🛠️ 三、 YAML 修复补丁 (Action Items)

为了让下一轮 E2E 顺利通关，请在执行前对 `plans/fix-cccc-workflow.yaml` 进行如下替换：

#### 补丁 1：强化 W2（认领真实调用方，拒绝伪测试）
```yaml
  - id: W2-daemon-init
    title: Ensure RalphService is initialized when workflow ops are triggered
    role: integration
    claimed_paths:
      - "src/cccc/daemon/foreman/workflow_orchestrator.py"
      - "src/cccc/daemon/ralph_ipc_handler.py"   # [新增] 必须认领真实 IPC 调用方
      - "src/cccc/daemon/server.py"              # [新增] 必须认领启动入口
    depends_on: ["P2-worker-prompt"]             # [显式声明] 避免与 P2 发生不可控的读写争抢
    addresses: ["R-3"]
    # ...
    verification:
      level: integration
      # [修改] 不再自己写死参数调用，必须通过真实 IPC / Daemon 启动来触发断言
      command: >
        python -c "
        import pytest;
        print('Validating caller context passes project_root...');
        pytest.main(['-q', 'tests/e2e/test_smoke_workflow.py::test_daemon_wires_ralph'])
        "
```

#### 补丁 2：强化 W1（修复依赖与文件漏报）
```yaml
  - id: W1-verify-gate
    # ...
    claimed_paths:
      - "src/cccc/daemon/ralph_ipc_handler.py"
      - "src/cccc/cli/workflow_cmds.py"
      - "src/cccc/cli/task_cmds.py"              # [新增] task 子命令路由
      - "src/cccc/daemon/foreman/workflow_orchestrator.py" # [新增] Verify Gate 的状态机载体
      - "tests/e2e/test_smoke_workflow.py"       # [新增] 必须认领测试文件才能写入
    depends_on: ["P2-worker-prompt", "W2-daemon-init"] # [修改] 必须等待 Ralph 初始化修好！
```

#### 补丁 3：新增 P5 任务（彻底封死 MCP 后门）
在 `Wave 1` 中插入这个任务，从物理层断绝 AI 走老路的可能：
```yaml
  - id: P5-mcp-hard-deprecation
    title: Hard deprecate completion via cccc_task MCP tool
    role: leaf
    claimed_paths:
      - "src/cccc/daemon/mcp_server.py"  # 假设这是 MCP Tool 定义文件
    depends_on: []
    addresses: ["M-1"]
    goal_behavior: >
      Modify the `cccc_task` MCP tool code. If it receives a status update to 'completed' 
      or 'failed', it MUST raise a hard ValueError: 
      "DEPRECATED: You MUST use the CLI 'cccc task complete' command instead."
    verification:
      level: unit
      command: "grep -i 'DEPRECATED' src/cccc/daemon/mcp_server.py"
```

**总结**：打上这三个补丁后，W1/W2 的竞态崩溃将被消除，伪测试被拔除，Write-set 权限被补全，MCP 老路被彻底封死。这套 V4 计划将具备极高的工程防腐韧性，可以直接交由 Foreman 开始执行。祝 E2E 闭环顺利打通！