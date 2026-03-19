"""
Dependency Graph - Task dependency analysis and management.

Provides a directed acyclic graph (DAG) for managing task dependencies,
with cycle detection and ready-task computation.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterator
from collections import deque
import logging

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"      # 等待执行
    READY = "ready"          # 依赖已满足，可执行
    ACTIVE = "active"        # 正在执行
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"        # 执行失败
    SKIPPED = "skipped"      # 已跳过
    BLOCKED = "blocked"      # 被阻塞（依赖失败）


class CycleDetectedError(Exception):
    """依赖图中检测到环路"""

    def __init__(self, cycle: list[str]):
        self.cycle = cycle
        cycle_str = " -> ".join(cycle)
        super().__init__(f"Cycle detected in dependency graph: {cycle_str}")


@dataclass
class TaskNode:
    """
    任务节点

    表示依赖图中的一个任务，包含其状态和依赖关系。

    Attributes:
        id: 任务唯一标识
        status: 当前状态
        deps: 依赖的任务 ID 集合
        task_type: 任务类型（backend/frontend/general）
        priority: 基础优先级分数（0-100）
        estimated_duration: 预估执行时间（秒）
        metadata: 额外元数据
    """
    id: str
    status: TaskStatus = TaskStatus.PENDING
    deps: set[str] = field(default_factory=set)
    task_type: str = "general"
    priority: int = 50
    estimated_duration: float = 300.0  # 默认 5 分钟
    metadata: dict = field(default_factory=dict)

    def is_terminal(self) -> bool:
        """检查是否处于终态"""
        return self.status in (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.SKIPPED,
        )

    def is_executable(self) -> bool:
        """检查是否可执行"""
        return self.status in (TaskStatus.PENDING, TaskStatus.READY)

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TaskNode):
            return False
        return self.id == other.id


class DependencyGraph:
    """
    任务依赖图

    管理任务之间的依赖关系，支持：
    - 添加/移除任务
    - 依赖关系管理
    - 环路检测
    - 计算可执行任务
    - 关键路径分析

    示例:
        graph = DependencyGraph()

        # 添加任务
        graph.add_task(TaskNode(id="T1"))
        graph.add_task(TaskNode(id="T2", deps={"T1"}))
        graph.add_task(TaskNode(id="T3", deps={"T1"}))
        graph.add_task(TaskNode(id="T4", deps={"T2", "T3"}))

        # 获取可执行任务
        ready = graph.get_ready_tasks()  # ["T1"]

        # 标记完成
        graph.mark_completed("T1")
        ready = graph.get_ready_tasks()  # ["T2", "T3"]
    """

    def __init__(self):
        self._nodes: dict[str, TaskNode] = {}
        # 反向依赖图：记录哪些任务依赖于某个任务
        self._dependents: dict[str, set[str]] = {}

    def add_task(self, node: TaskNode) -> None:
        """
        添加任务到图中

        Args:
            node: 任务节点

        Raises:
            CycleDetectedError: 如果添加后会形成环路
            ValueError: 如果任务依赖不存在的任务
        """
        # 检查自依赖（自环）
        if node.id in node.deps:
            raise CycleDetectedError([node.id, node.id])

        # 检查依赖是否存在
        for dep_id in node.deps:
            if dep_id not in self._nodes:
                raise ValueError(f"Task {node.id} depends on non-existent task: {dep_id}")

        # 添加节点
        self._nodes[node.id] = node

        # 更新反向依赖图
        if node.id not in self._dependents:
            self._dependents[node.id] = set()

        for dep_id in node.deps:
            if dep_id not in self._dependents:
                self._dependents[dep_id] = set()
            self._dependents[dep_id].add(node.id)

        # 检查环路
        cycle = self._detect_cycle_from(node.id)
        if cycle:
            # 回滚
            self.remove_task(node.id)
            raise CycleDetectedError(cycle)

        # 更新状态
        self._update_task_status(node.id)

        logger.debug(f"Task added: {node.id} (deps: {node.deps})")

    def remove_task(self, task_id: str) -> TaskNode | None:
        """
        移除任务

        Args:
            task_id: 任务 ID

        Returns:
            被移除的任务节点，如果不存在则返回 None
        """
        if task_id not in self._nodes:
            return None

        node = self._nodes.pop(task_id)

        # 清理反向依赖
        for dep_id in node.deps:
            if dep_id in self._dependents:
                self._dependents[dep_id].discard(task_id)

        if task_id in self._dependents:
            del self._dependents[task_id]

        logger.debug(f"Task removed: {task_id}")
        return node

    def get_task(self, task_id: str) -> TaskNode | None:
        """获取任务节点"""
        return self._nodes.get(task_id)

    def get_all_tasks(self) -> list[TaskNode]:
        """获取所有任务"""
        return list(self._nodes.values())

    def get_ready_tasks(self) -> list[TaskNode]:
        """
        获取所有可执行的任务

        返回所有依赖已满足且状态为 PENDING/READY 的任务。
        """
        ready = []
        for node in self._nodes.values():
            if not node.is_executable():
                continue

            # 检查所有依赖是否已完成
            deps_satisfied = all(
                self._nodes.get(dep_id) and
                self._nodes[dep_id].status == TaskStatus.COMPLETED
                for dep_id in node.deps
            )

            if deps_satisfied:
                ready.append(node)

        return ready

    def mark_completed(self, task_id: str) -> None:
        """
        标记任务为完成

        同时更新依赖于此任务的其他任务状态。
        """
        if task_id not in self._nodes:
            raise ValueError(f"Task not found: {task_id}")

        self._nodes[task_id].status = TaskStatus.COMPLETED

        # 更新依赖此任务的任务状态
        for dependent_id in self._dependents.get(task_id, set()):
            self._update_task_status(dependent_id)

        logger.info(f"Task completed: {task_id}")

    def mark_failed(self, task_id: str) -> None:
        """
        标记任务为失败

        同时将依赖于此任务的任务标记为 BLOCKED。
        """
        if task_id not in self._nodes:
            raise ValueError(f"Task not found: {task_id}")

        self._nodes[task_id].status = TaskStatus.FAILED

        # 递归标记所有依赖任务为 BLOCKED
        self._propagate_blocked(task_id)

        logger.warning(f"Task failed: {task_id}")

    def mark_active(self, task_id: str) -> None:
        """标记任务为正在执行"""
        if task_id not in self._nodes:
            raise ValueError(f"Task not found: {task_id}")

        self._nodes[task_id].status = TaskStatus.ACTIVE
        logger.info(f"Task active: {task_id}")

    def mark_skipped(self, task_id: str) -> None:
        """标记任务为已跳过"""
        if task_id not in self._nodes:
            raise ValueError(f"Task not found: {task_id}")

        self._nodes[task_id].status = TaskStatus.SKIPPED

        # 检查依赖此任务的任务是否应该被阻塞
        # 跳过视为"完成"，不阻塞后续任务
        for dependent_id in self._dependents.get(task_id, set()):
            self._update_task_status(dependent_id)

        logger.info(f"Task skipped: {task_id}")

    def _update_task_status(self, task_id: str) -> None:
        """更新单个任务状态"""
        node = self._nodes.get(task_id)
        if not node or not node.is_executable():
            return

        # 检查依赖状态
        all_deps_done = True
        any_dep_failed = False

        for dep_id in node.deps:
            dep = self._nodes.get(dep_id)
            if not dep:
                all_deps_done = False
                continue

            if dep.status == TaskStatus.FAILED:
                any_dep_failed = True
                break
            elif dep.status not in (TaskStatus.COMPLETED, TaskStatus.SKIPPED):
                all_deps_done = False

        if any_dep_failed:
            node.status = TaskStatus.BLOCKED
        elif all_deps_done:
            node.status = TaskStatus.READY
        else:
            node.status = TaskStatus.PENDING

    def _propagate_blocked(self, failed_task_id: str) -> None:
        """递归传播 BLOCKED 状态"""
        to_block = list(self._dependents.get(failed_task_id, set()))

        while to_block:
            task_id = to_block.pop()
            node = self._nodes.get(task_id)
            if node and node.is_executable():
                node.status = TaskStatus.BLOCKED
                # 继续传播到依赖此任务的任务
                to_block.extend(self._dependents.get(task_id, set()))

    def detect_cycles(self) -> list[list[str]] | None:
        """
        检测图中的所有环路

        使用 DFS 检测强连通分量中的环路。

        Returns:
            环路列表，每个环路是任务 ID 的列表；如果无环路则返回 None
        """
        cycles = []
        visited = set()
        rec_stack = set()

        def dfs(node_id: str, path: list[str]) -> None:
            visited.add(node_id)
            rec_stack.add(node_id)
            path.append(node_id)

            node = self._nodes.get(node_id)
            if node:
                for dep_id in node.deps:
                    if dep_id not in visited:
                        dfs(dep_id, path)
                    elif dep_id in rec_stack:
                        # 找到环路
                        cycle_start = path.index(dep_id)
                        cycles.append(path[cycle_start:] + [dep_id])

            path.pop()
            rec_stack.remove(node_id)

        for node_id in self._nodes:
            if node_id not in visited:
                dfs(node_id, [])

        return cycles if cycles else None

    def _detect_cycle_from(self, start_id: str) -> list[str] | None:
        """从指定节点开始检测环路"""
        visited = set()
        rec_stack = set()
        path = []

        def dfs(node_id: str) -> list[str] | None:
            visited.add(node_id)
            rec_stack.add(node_id)
            path.append(node_id)

            node = self._nodes.get(node_id)
            if node:
                for dep_id in node.deps:
                    if dep_id not in visited:
                        result = dfs(dep_id)
                        if result:
                            return result
                    elif dep_id in rec_stack:
                        cycle_start = path.index(dep_id)
                        return path[cycle_start:] + [dep_id]

            path.pop()
            rec_stack.remove(node_id)
            return None

        return dfs(start_id)

    def get_critical_path(self) -> list[str]:
        """
        计算关键路径

        关键路径是从任何入口节点到任何出口节点的最长路径。
        使用拓扑排序和动态规划计算。

        Returns:
            关键路径上的任务 ID 列表
        """
        if not self._nodes:
            return []

        # 拓扑排序
        topo_order = self._topological_sort()
        if not topo_order:
            return []

        # 计算每个节点到终点的最长路径
        dist: dict[str, float] = {node_id: 0.0 for node_id in self._nodes}
        parent: dict[str, str | None] = {node_id: None for node_id in self._nodes}

        # 反向遍历（从后向前）
        for node_id in reversed(topo_order):
            node = self._nodes[node_id]
            # 找依赖于此节点的任务中距离最长的
            for dependent_id in self._dependents.get(node_id, set()):
                dep_node = self._nodes.get(dependent_id)
                if dep_node:
                    new_dist = dist[dependent_id] + dep_node.estimated_duration
                    if new_dist > dist[node_id]:
                        dist[node_id] = new_dist
                        parent[node_id] = dependent_id

        # 找起点（入口节点中距离最大的）
        entry_nodes = [
            node_id for node_id, node in self._nodes.items()
            if not node.deps
        ]

        if not entry_nodes:
            return []

        start = max(entry_nodes, key=lambda x: dist[x])

        # 构建路径
        path = [start]
        current = start
        while parent[current]:
            current = parent[current]
            path.append(current)

        return path

    def _topological_sort(self) -> list[str]:
        """拓扑排序（Kahn 算法）"""
        in_degree = {node_id: len(node.deps) for node_id, node in self._nodes.items()}
        queue = deque([node_id for node_id, degree in in_degree.items() if degree == 0])
        result = []

        while queue:
            node_id = queue.popleft()
            result.append(node_id)

            for dependent_id in self._dependents.get(node_id, set()):
                in_degree[dependent_id] -= 1
                if in_degree[dependent_id] == 0:
                    queue.append(dependent_id)

        if len(result) != len(self._nodes):
            # 存在环路，无法完成拓扑排序
            return []

        return result

    def get_downstream_count(self, task_id: str) -> int:
        """
        获取下游任务数量

        返回直接或间接依赖于此任务的任务总数。
        """
        visited = set()
        
        def collect_downstream(node_id: str) -> None:
            for dependent_id in self._dependents.get(node_id, set()):
                if dependent_id not in visited:
                    visited.add(dependent_id)
                    collect_downstream(dependent_id)

        collect_downstream(task_id)
        return len(visited)

    def __len__(self) -> int:
        return len(self._nodes)

    def __contains__(self, task_id: str) -> bool:
        return task_id in self._nodes

    def __iter__(self) -> Iterator[TaskNode]:
        return iter(self._nodes.values())
