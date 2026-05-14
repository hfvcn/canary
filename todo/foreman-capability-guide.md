# Foreman 能力指南 — CCCC Workflow System

> 版本：v29 (2026-05-13)
> 用途：E2E 实测时复制到项目 docs/ 目录，供 Foreman 读取

---

## 一、计划阶段能力

### 1.1 plan.yaml 结构

每个 task 支持以下字段：

```yaml
tasks:
  - id: T1
    title: "Backend scaffold"
    type: backend          # 任意字符串，用于分类
    claimed_paths:         # 精确到文件/目录，禁止 "/"
      - "backend/"
      - "requirements.txt"
    depends_on: []         # 依赖的 task ID 列表
    provides:              # 本任务产出的契约
      - "backend_api"
    consumes: []           # 本任务依赖的契约
    covers_flows:          # 关联的 critical_flows
      - "board_crud"
    goal_behavior: |       # 任务目标描述
      Implement FastAPI backend with CRUD endpoints...
    acceptance_criteria: |  # 验收标准（具体、可测试）
      - GET /boards returns 200 with list
      - POST /boards creates board with auto-increment position
    expected_input: {}      # 模块输入规范（黑盒接口，BP-3）
    expected_output: {}     # 模块输出规范（黑盒接口，BP-3）
    verification:
      mode: ralph           # ralph(shell) 或 agent
      checks:               # shell 模式下的检查命令
        - name: compile
          command: "cd backend && python -c 'import app.main'"
          required: true
        - name: test
          command: "cd backend && python -m pytest -x"
          required: true
      mock_tests:           # agent 模式下的模拟测试用例（BP-1）
        - name: "create board returns 201"
          input: "POST /boards {\"title\": \"Test\"}"
          expected: "201 with board object containing id, title, position"
```

**关键字段说明：**
- `claimed_paths`：精确到文件或目录，引擎用它做并行冲突检测和 DAG 调度
- `depends_on`：表达真实依赖关系，引擎会强制执行（依赖未完成 = 任务不会启动）
- `verification.checks`：每个任务至少包含 compile + test 两个 check
- `mock_tests`：Foreman 预设的模拟测试用例，Worker 看不到（对抗性验证），仅 agent 模式使用
- `expected_input`/`expected_output`：黑盒接口规范，会渲染到 Worker prompt 中
- `acceptance_criteria`：必须具体、可测试——模糊的验收标准是结果分低的主因

### 1.2 Ralph validate

```bash
ralph validate plan.yaml --project-root .
```

- 检查依赖环、重复 ID、未知依赖、claimed_paths 冲突等
- 新增（v30）：错误消息附带字段建议和示例
- `--show-schema`：显示完整 plan.yaml schema（v30 新增）
- **必须 0 error 才能提交**
- Warning 级别：`W_SHARED_PATH_NO_DEPENDENCY`（两个 task claim 同一文件但无 depends_on）——不阻塞但应检查

### 1.3 Ralph suggest

```bash
ralph suggest plan.yaml
```

- 基于 DAG 分析可并行批次
- 输出建议的批次分组和 worker 分配

---

## 二、执行阶段能力

### 2.1 Worker 创建

```bash
cccc actor add worker --title "worker-be" --runtime codex --scope /path/to/project
cccc actor add worker --title "worker-fe" --runtime claude --scope /path/to/project
```

**支持的 Runtime：**
- `claude`：完全支持，推荐用于前端/全栈任务。零 stall 历史（v28 验证）
- `codex`：完全支持，推荐用于后端/测试任务。稳定可靠
- `gemini`：**不推荐用于 worker**——连续多轮 E2E（v22-v28）0% 可靠率。仅用于 Ralph Agent 内部验证

### 2.2 Workflow submit（计划模式）

```bash
cccc workflow submit --plan plan.yaml \
  --auto-process \
  --auto-dispatch \
  --assignment-map '{"T1":"worker-be","T2":"worker-be","T3":"worker-fe"}'
```

**关键参数：**
- `--plan plan.yaml`：从 plan 文件加载任务（自动跳过已完成任务）
- `--auto-process`：批次完成后自动推进下一批（无需手工确认）
- `--auto-dispatch`：自动将任务分发给 worker（无需手工 `cccc send`）
- `--assignment-map`：指定每个任务分配给哪个 worker

**auto-dispatch 发送给 Worker 的内容包括：**
- Task ID、Title、Goal、Acceptance Criteria
- Verification Command（shell 模式）
- Expected I/O Contract（如有）
- Claimed paths（合同范围）
- Runtime 适配提示
- Completion 提醒（`cccc task complete TASK_ID --changed-file PATH`）

### 2.3 DAG 调度（非批次门控）

引擎使用**依赖感知调度**，不是按批次整体等待：
- 当 T1 完成 → 引擎检查 T1 解锁了哪些下游任务
- 下游任务的所有 depends_on 都满足 → 立即标记为 ready 并分配
- 不需要等同批次其他任务完成

### 2.4 Worker 完成协议

Worker 完成任务后必须执行：
```bash
cccc task complete TASK_ID --changed-file PATH [--changed-file PATH2 ...]
```

引擎收到后自动触发 verification gate。

### 2.5 Verification Gate

**Shell 模式（默认）：**
- 按 plan.yaml 中的 `verification.checks` 顺序执行
- 每个 check 运行 command，检查 exit code
- required=true 的 check 失败 → 任务标记为 failed

**Agent 模式：**
- 使用 mock_tests 进行对抗性验证
- Worker 看不到 mock_tests 内容
- 验证结果：passed / failed / agent_pending

### 2.6 Stall Detection

- Running 任务超过 300 秒无 heartbeat → 标记为 stalled
- Assigned 任务超过 120 秒未启动 → 标记为 stalled
- Foreman 收到通知后可决定重试/重分配

### 2.7 Workflow 终态（v30 新增）

- 当所有任务进入终态（completed/failed/archived/blocked）时，workflow 自动转为终态
- 无需 Foreman 手工关闭

---

## 三、监控命令

```bash
# 查看工作流状态
cccc workflow status

# 查看最新消息
cccc tail -n 20

# 实时跟踪
cccc tail -f

# 查看 actor 列表
cccc actor list

# 验证单个任务
ralph verify plan.yaml --task TASK_ID
```

---

## 四、已知限制（v29）

1. **Verification 无法检查测试充分性**——只能检查"测试是否通过"，不能检查"测试是否覆盖了关键场景"。需要 Foreman 在验收标准中明确列出必须覆盖的场景
2. **goal_behavior 语义验证缺失**——Ralph 不验证 goal_behavior 中的技术断言是否与源码一致
3. **模块化拆分未实现**——Task 内部无法拆分为多个 Module 并行执行
4. **Mock tests 需要 Foreman 主动填写**——引擎不会自动生成 mock_tests，需要 Foreman 在计划阶段预设

---

## 五、最佳实践（来自 v1-v28 实战经验）

1. **验收标准要具体**：写"POST /boards 返回 201 + board 对象包含 id/title/position"而非"支持创建 board"
2. **verification checks 要真正验证**：不要只 import，要运行 pytest
3. **claimed_paths 精确**：`"backend/app/routers/"` 优于 `"backend/"`
4. **不要用 Gemini 做 worker**：用 claude 或 codex
5. **每批完成后 `ralph suggest`**：查看下一批可提交的任务
6. **mock_tests 写关键边界**：如"删除后 position 重排"、"FK 约束拒绝非法值"
