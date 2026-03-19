# CCCC Operating Playbook

> Ralph-Foreman 工作流操作手册

## 目录

1. [系统架构概述](#系统架构概述)
2. [安装与配置](#安装与配置)
3. [日常操作](#日常操作)
4. [故障排查](#故障排查)

---

## 系统架构概述

### 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        CCCC System                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐    IPC     ┌──────────────┐                   │
│  │    Ralph     │◄──────────►│   Foreman    │                   │
│  │   (Daemon)   │            │   (Daemon)   │                   │
│  └──────────────┘            └──────────────┘                   │
│         │                           │                            │
│         │ Git Watch                 │ Agent Pool                 │
│         ▼                           ▼                            │
│  ┌──────────────┐            ┌──────────────┐                   │
│  │  Scheduler   │            │  Agent Pool  │                   │
│  │              │            │   Manager    │                   │
│  ├──────────────┤            ├──────────────┤                   │
│  │ • Dep Graph  │            │ • Claude     │                   │
│  │ • Ready Batch│            │ • Gemini     │                   │
│  │ • Priority   │            │ • Custom     │                   │
│  └──────────────┘            └──────────────┘                   │
│         │                           │                            │
│         │ Verify                    │ Execute                    │
│         ▼                           ▼                            │
│  ┌──────────────┐            ┌──────────────┐                   │
│  │  Validator   │            │    Tasks     │                   │
│  │              │            │   Execution  │                   │
│  ├──────────────┤            └──────────────┘                   │
│  │ • Build      │                                               │
│  │ • Test       │                                               │
│  │ • Lint       │                                               │
│  └──────────────┘                                               │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 核心组件

| 组件 | 职责 | 位置 |
|------|------|------|
| **Ralph Daemon** | Git 监控、调度建议、验证执行 | `ralph/ralph/` |
| **Foreman Daemon** | Agent 池管理、任务分配、决策 | `src/cccc/daemon/foreman/` |
| **Scheduler** | 依赖图管理、Ready-Batch 计算 | `ralph/ralph/scheduler/` |
| **Validator** | 构建/测试/Lint 验证 | `ralph/ralph/validator/` |
| **IPC Protocol** | Ralph ↔ Foreman 通信协议 | `ralph/ralph/ipc/` |

### 数据流

1. **任务初始化**: 用户创建任务 → 构建依赖图
2. **调度建议**: Ralph 计算 Ready-Batch → 发送给 Foreman
3. **任务分配**: Foreman 评估 Agent 池 → 分配任务
4. **任务执行**: Agent 执行任务 → 提交代码
5. **验证反馈**: Ralph 检测提交 → 执行验证 → 报告结果

---

## 安装与配置

### 系统要求

- Python 3.11+
- Node.js 18+ (FlowPilot 依赖)
- Git 2.30+

### 安装步骤

```bash
# 1. 克隆仓库
git clone https://github.com/your-org/cccc.git
cd cccc

# 2. 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# 或 .venv\Scripts\activate  # Windows

# 3. 安装依赖
pip install -e .
pip install -e ralph/

# 4. 验证安装
python -c "import cccc; print(cccc.__version__)"
ralph --version
```

### 配置文件

#### Ralph 配置 (`~/.ralph/config.yaml`)

```yaml
# Ralph Daemon 配置
daemon:
  poll_interval: 2.0          # Git 轮询间隔（秒）
  max_batch_size: 5           # 最大批次大小
  priority_strategy: critical_path  # fifo | shortest_first | critical_path

validator:
  build_timeout: 300          # 构建超时（秒）
  test_timeout: 600           # 测试超时（秒）
  lint_timeout: 120           # Lint 超时（秒）

ipc:
  socket_path: /tmp/ralph.sock
  reconnect_delay: 5
```

#### 项目配置 (`.cccc/ralph.yaml`)

```yaml
# 项目级别配置
validator:
  build:
    command: "npm run build"
    working_dir: "."
    timeout: 300
    
  test:
    command: "npm run test"
    working_dir: "."
    timeout: 600
    
  lint:
    command: "npm run lint"
    working_dir: "."
    timeout: 120

scheduler:
  agent_mapping:
    backend: "claude-agent"
    frontend: "gemini-agent"
    general: "default-agent"
```

---

## 日常操作

### 启动服务

```bash
# 启动 Ralph Daemon
ralph start --repo /path/to/project --verbose

# 后台运行
ralph start --repo /path/to/project --daemon

# 检查状态
ralph status
```

### 工作流操作

```bash
# 初始化工作流（通过 FlowPilot）
cat tasks.md | node flow.js init

# 获取下一批任务
node flow.js next --batch

# 检查进度
node flow.js status

# 完成任务
echo 'Task completed [REMEMBER] Key finding' | node flow.js checkpoint <task_id> --files file1.py
```

### 任务管理

```bash
# 查看依赖图
ralph graph show

# 查看就绪任务
ralph batch ready

# 手动触发验证
ralph validate --task T1 --commit abc123

# 跳过任务
node flow.js skip <task_id>
```

### 监控与日志

```bash
# 查看实时日志
ralph logs --follow

# 查看特定任务日志
ralph logs --task T1

# 导出验证报告
ralph report --format json > report.json
```

---

## 故障排查

### 常见问题

#### 1. Ralph 无法连接到 Foreman

**症状**: `IPC connection failed` 错误

**排查步骤**:
```bash
# 检查 socket 文件
ls -la /tmp/ralph.sock

# 检查 Foreman 进程
ps aux | grep foreman

# 检查端口占用
lsof -i :8080

# 重启服务
ralph restart
```

**解决方案**:
- 确保 Foreman 已启动
- 检查 socket 权限
- 清理陈旧 socket 文件：`rm /tmp/ralph.sock`

#### 2. 依赖图检测到环路

**症状**: `CycleDetectedError: Cycle detected in dependency graph`

**排查步骤**:
```bash
# 查看依赖图
ralph graph show --format dot > graph.dot
dot -Tpng graph.dot -o graph.png

# 检查特定任务的依赖
ralph task deps <task_id>
```

**解决方案**:
- 重新设计任务依赖关系
- 使用 `node flow.js skip <task_id>` 跳过问题任务
- 手动修改 `.workflow/tasks.json` 修复依赖

#### 3. 验证超时

**症状**: `ValidationStatus.TIMEOUT`

**排查步骤**:
```bash
# 查看验证配置
cat .cccc/ralph.yaml | grep timeout

# 手动运行验证命令
npm run test

# 检查资源使用
top -p $(pgrep -f "npm test")
```

**解决方案**:
- 增加超时配置
- 优化测试性能
- 使用增量测试：`pytest --last-failed`

#### 4. Agent 池耗尽

**症状**: 任务长时间等待分配

**排查步骤**:
```bash
# 查看 Agent 状态
ralph pool status

# 查看活跃任务
ralph tasks --status active

# 检查 Agent 资源
ralph agent <agent_id> --metrics
```

**解决方案**:
- 增加 Agent 数量
- 调整 `max_batch_size`
- 优先完成耗时任务

#### 5. Git 监控失效

**症状**: 新提交未被检测

**排查步骤**:
```bash
# 检查 Git 状态
git status

# 检查分支配置
ralph config show | grep branch

# 检查轮询间隔
ralph config show | grep poll_interval

# 手动触发检测
ralph watch --once
```

**解决方案**:
- 确认监控的分支正确
- 减小轮询间隔
- 检查 Git 权限

### 日志分析

#### 关键日志文件

| 文件 | 内容 |
|------|------|
| `~/.ralph/logs/ralph.log` | Ralph Daemon 主日志 |
| `~/.ralph/logs/validator.log` | 验证器日志 |
| `~/.ralph/logs/ipc.log` | IPC 通信日志 |
| `.workflow/execution.log` | FlowPilot 执行日志 |

#### 日志级别

```bash
# 启用调试日志
ralph start --verbose --log-level DEBUG

# 查看特定模块日志
ralph logs --module scheduler

# 过滤错误日志
ralph logs --level ERROR
```

### 性能调优

#### 调度器优化

```yaml
# 高并行场景
scheduler:
  max_batch_size: 10
  priority_strategy: shortest_first
  
# 关键路径优化
scheduler:
  max_batch_size: 3
  priority_strategy: critical_path
```

#### 验证器优化

```yaml
validator:
  # 并行验证
  parallel: true
  
  # 增量验证
  incremental: true
  
  # 缓存
  cache:
    enabled: true
    ttl: 3600
```

### 紧急恢复

#### 工作流卡死

```bash
# 强制重置工作流状态
node flow.js reset --force

# 清理锁文件
rm -f .workflow/.lock

# 恢复到上一个 checkpoint
node flow.js restore --last
```

#### 数据损坏

```bash
# 备份当前状态
cp -r .workflow .workflow.backup

# 从 Git 历史恢复
git checkout HEAD~1 -- .workflow/

# 重建依赖图
ralph graph rebuild
```

---

## 附录

### 命令速查

| 命令 | 说明 |
|------|------|
| `ralph start` | 启动 Ralph Daemon |
| `ralph stop` | 停止 Ralph Daemon |
| `ralph status` | 查看运行状态 |
| `ralph validate` | 手动触发验证 |
| `ralph graph show` | 显示依赖图 |
| `ralph batch ready` | 查看就绪任务 |
| `ralph pool status` | 查看 Agent 池状态 |
| `ralph logs` | 查看日志 |

### 状态码参考

| 状态 | 含义 |
|------|------|
| `pending` | 等待执行 |
| `ready` | 依赖已满足，可执行 |
| `active` | 正在执行 |
| `completed` | 已完成 |
| `failed` | 执行失败 |
| `skipped` | 已跳过 |
| `blocked` | 被阻塞（依赖失败） |

### 联系支持

- GitHub Issues: https://github.com/your-org/cccc/issues
- 文档: https://docs.cccc.dev
- 社区: https://discord.gg/cccc
