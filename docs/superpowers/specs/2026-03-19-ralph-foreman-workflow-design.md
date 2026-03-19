# Ralph-Foreman 角色驱动工作流系统设计规格

## 概述

将 CCCC 从通用 MCP 协作内核转型为角色驱动工作流系统：
- Ralph Daemon（Rust）作为独立外层循环控制器
- Foreman 作为唯一对外协调者，可动态创建 Agent
- Git 作为状态持久化层和通信媒介
- 移除 CCCC MCP 自动启用，改为按需 Prompt 引入

## 1. 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                     Ralph Daemon (Rust)                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │ Git Watcher │→ │ Event Loop  │→ │ Protocol Validator      │  │
│  │ (轮询提交)   │  │ (消息总线)   │  │ (验证标准 + ready-batch) │  │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘  │
│         ↑                                      ↓                │
│         │              Git 仓库                │                │
│         └──────── (状态 + 通信媒介) ───────────┘                │
└─────────────────────────────────────────────────────────────────┘
                              ↕ Git 事件
┌─────────────────────────────────────────────────────────────────┐
│                     CCCC Daemon (Python)                        │
│  ┌──────────┐  ┌──────────┐  ┌────────────┐  ┌──────────────┐   │
│  │ Web API  │  │ Messaging│  │ Automation │  │ Memory       │   │
│  │ (HTTP)   │  │ (收件箱)  │  │ (定时任务)  │  │ (共享知识)    │   │
│  └──────────┘  └──────────┘  └────────────┘  └──────────────┘   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ Capability (Prompt 模板管理)                              │   │
│  │ - Foreman: 完整工具集 + Feishu API                        │   │
│  │ - Worker: 任务执行工具子集                                 │   │
│  │ - Reviewer: 只读审查工具                                   │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              ↕ HTTP API
┌─────────────────────────────────────────────────────────────────┐
│                        Actor 层                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   Foreman    │  │   Worker(s)  │  │   Reviewer   │          │
│  │ (协调+Feishu) │  │ (有限自主)    │  │ (质量门)     │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│         ↓                  ↓                  ↓                 │
│     Git Commit         Git Commit         Git Commit            │
│  (---METADATA---)    (---METADATA---)   (---METADATA---)        │
└─────────────────────────────────────────────────────────────────┘
```

## 2. Ralph Daemon 设计

### 2.1 项目结构

```
ralph/
├── src/
│   ├── main.rs              # 入口，CLI 参数解析
│   ├── git_watcher.rs       # Git 提交监控（复用 gitcortex）
│   ├── message_bus.rs       # 事件总线（复用 gitcortex）
│   ├── validator/
│   │   ├── mod.rs
│   │   ├── build_test.rs    # 构建/测试验证器
│   │   ├── task_file.rs     # 任务文件状态检查
│   │   └── promise.rs       # Completion Promise 检查
│   ├── scheduler/
│   │   ├── mod.rs
│   │   ├── dep_graph.rs     # 任务依赖图分析
│   │   └── ready_batch.rs   # 可执行批次计算
│   ├── state/
│   │   ├── mod.rs
│   │   ├── actor_state.rs   # Actor 级别状态管理
│   │   └── persistence.rs   # 状态持久化到 Git
│   └── protocol/
│       ├── mod.rs
│       └── metadata.rs      # Git 提交元数据协议
└── Cargo.toml
```

### 2.2 Git 提交元数据协议

```
feat: implement user authentication

Detailed description of changes...

---METADATA---
actor_id: worker-1
task_id: TASK-003
status: completed|checkpoint|failed
next_action: continue|review|retry|blocked
changed_files: src/auth.py,src/models/user.py
verification:
  build: pass
  test: pass
  lint: pass
```

### 2.3 验证流程

验证标准（可配置组合，分层优先级）：
1. **必选**：构建/测试/lint 等可执行命令（机器可验证，最可靠）
2. **推荐**：任务文件状态检查（`.cccc/actors/{id}/state.json`）
3. **可选**：Completion Promise（Actor 主动声明完成的信号）

干预方式：通过 messaging 系统发送反馈消息。

### 2.4 Ready-Batch 计算

Ralph 计算可执行任务批次，输出为 proposal 供 Foreman 审核：

```json
// .cccc/ralph/ready_batch_proposal.json
{
  "proposal_id": "prop-20260319-103000",
  "status": "pending_review",
  "suggested_batch": [
    {
      "task_id": "T4",
      "priority_score": 85,
      "reason": "关键路径：被 T7 依赖",
      "suggested_agent": "claude-backend-dev"
    }
  ],
  "blocked_tasks": [...]
}
```

Foreman 审核后确认：

```json
// .cccc/ralph/ready_batch_confirmed.json
{
  "proposal_id": "prop-20260319-103000",
  "decision": "accepted_with_changes",
  "confirmed_batch": [
    {"task_id": "T4", "assigned_to": "worker-1", "agent": "claude-backend-dev"}
  ]
}
```

## 3. 动态角色系统

### 3.1 角色层次

- **Foreman**：唯一固定角色，负责评估任务需求、动态创建/复用 Agent、分配任务、外部通信
- **动态 Agent Pool**：由 Foreman 根据任务需求和模型能力创建，可保存复用

### 3.2 模型能力注册表

```yaml
# .cccc/models/registry.yaml
models:
  claude-sonnet:
    runtime: claude
    strengths: [复杂逻辑推理, 长上下文理解, 代码重构]
    weaknesses: [实时信息获取]
    context_window: 200k

  gemini-pro:
    runtime: gemini
    strengths: [多模态理解, 架构设计, 快速原型]
    weaknesses: [长代码文件处理]
    context_window: 1m

  codex:
    runtime: codex
    strengths: [代码审查, 快速修复, Git 操作]
    weaknesses: [复杂架构决策]
    context_window: 192k
```

### 3.3 Agent 定义

```yaml
# .cccc/agents/claude-backend-dev.yaml
id: claude-backend-dev
name: Claude Backend Developer
created_by: foreman
model:
  runtime: claude
  model_id: claude-sonnet-4
role_type: worker  # worker | reviewer | specialist
capabilities: [task_execution, memory_access, code_modification]
prompt: |
  # Role: Backend Developer
  你是一个专注于后端开发的 Worker...
task_affinity: [backend, database, api]
```

### 3.4 角色职责

- **Worker**：有限自主，可以在任务范围内做技术决策，但不能修改任务范围
- **Reviewer**：质量门守护，有权否决不合格的工作并要求返工

## 4. 状态持久化与 Context Rollover

### 4.1 状态存储结构

```
.cccc/
├── ralph/                        # Ralph Daemon 状态
│   ├── ready_batch_proposal.json
│   ├── ready_batch_confirmed.json
│   └── processed_commits.json
├── agents/                       # Agent 定义（Foreman 创建）
├── actors/                       # Actor 运行时状态
│   ├── foreman/
│   │   ├── state.json
│   │   └── context.md
│   └── worker-1/
│       ├── state.json
│       ├── context.md
│       ├── current_task.json
│       └── guardrails.md
├── tasks/                        # 任务状态
│   ├── index.json
│   └── TASK-*.json
└── models/
    └── registry.yaml
```

### 4.2 Context Rollover 机制

当 Ralph 决定重启 Actor 会话时：
1. Actor 提交带 `status=checkpoint` 的 commit，更新 `context.md`
2. Ralph 写入 `.cccc/actors/{id}/inbox/restart.json`
3. CCCC Daemon 检测到 inbox 变更，终止当前进程，启动新会话
4. 新会话读取 `context.md` 恢复上下文，`iteration += 1`

## 5. 任务流程与通信协议

### 5.1 Git 通信协议

| 通信类型 | 文件路径 | 触发方 |
|---------|---------|-------|
| 任务分配 | `.cccc/actors/{id}/inbox/assignment.json` | Foreman |
| 重启指令 | `.cccc/actors/{id}/inbox/restart.json` | Ralph |
| 审查请求 | `.cccc/actors/{id}/inbox/handoff.json` | Worker |
| 审查结果 | `.cccc/actors/{id}/inbox/review_result.json` | Reviewer |
| Ready Batch | `.cccc/ralph/ready_batch_*.json` | Ralph/Foreman |

### 5.2 完整任务生命周期

1. **任务输入**：Feishu → Foreman → 解析为任务列表
2. **任务规划**：Foreman 分析依赖 → 写入 tasks/index.json
3. **Ready-Batch 计算**：Ralph 分析依赖图 → proposal
4. **Foreman 审核**：审核/调整/确认 → confirmed
5. **Worker 执行**：Ralph Loop（执行 → 验证 → 反馈）
6. **Reviewer 审查**：审查 → approve/reject
7. **任务完成**：更新状态 → 重新计算 → 循环继续

## 6. 现有模块改造

### 6.1 边界划分

| 模块 | 职责 |
|------|------|
| Ralph | Git 事件驱动、任务依赖分析、协议验证、Context 刷新 |
| Automation | 时间触发的定时任务：standup、提醒、状态检查 |
| Capability | Prompt 模板管理：按角色/需求组装 API 调用说明 |
| Memory | 跨 Actor 共享知识：项目决策、技术约定、学习经验 |

### 6.2 Capability 改造

从 MCP 工具包改为 Prompt 模板片段：

```yaml
# .cccc/capabilities/task_management.yaml
id: cap_task_mgmt
name: Task Management
prompt_fragments:
  foreman: |
    ### 任务管理
    - `GET /api/tasks` — 列出所有任务
    - `POST /api/tasks/{id}/assign` — 分配任务
  worker: |
    ### 任务管理
    - `GET /api/tasks/{id}` — 获取任务详情
    - `POST /api/tasks/{id}/status` — 更新状态
```

### 6.3 Automation 改造

- 保留：`interval`/`cron`/`at` 触发器，`notify`/`group_state` 动作
- 移除：`actor_control` 动作（转移给 Ralph）
- 新增：`ralph_signal` 动作

## 7. 实现任务分解

### Phase 1: 基础设施（可并行）
- T1: Ralph Daemon 骨架
- T2: Git 通信协议
- T3: Capability 改造

### Phase 2: 核心能力（依赖 Phase 1）
- T4: 动态 Agent 系统
- T5: Ready-Batch 调度器
- T6: Context Rollover

### Phase 3: 集成与验证（依赖 Phase 2）
- T7: Foreman 角色实现
- T8: 验证器实现
- T9: Feishu 进度上报

### Phase 4: 收尾（依赖 Phase 3）
- T10: 端到端测试与文档

### 并行执行计划

```
Wave 1（并行）: T1, T2, T3
Wave 2（并行）: T4, T5, T6
Wave 3（并行）: T7, T8
Wave 4: T9
Wave 5: T10
```

## 关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| Ralph 定位 | 独立外层 Daemon | 解耦、可独立演进 |
| 实现语言 | Rust | 复用 gitcortex 组件 |
| 通信媒介 | Git | 状态可追溯、无额外依赖 |
| 工具调用 | HTTP API | 简单、通用 |
| 角色控制 | Prompt 层 | 轻量、灵活 |
| 调度决策 | Ralph 建议 + Foreman 审核 | 平衡自动化与人工判断 |
