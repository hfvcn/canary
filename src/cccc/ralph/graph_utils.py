"""Shared graph algorithm utilities for Ralph validators.

Extracted from validator.py to eliminate duplication with filesystem_validator.py.
All functions operate on TaskSpec lists and task ID sets — no side effects.
"""

from __future__ import annotations

from typing import Dict, List, Set

from .models import TaskSpec


def transitive_deps(task_id: str, task_map: Dict[str, TaskSpec]) -> Set[str]:
    """Compute the transitive dependency closure for a task, excluding itself."""
    visited: Set[str] = set()
    if task_id not in task_map:
        return visited
    stack = list(task_map[task_id].depends_on)

    while stack:
        dep_id = stack.pop()
        if dep_id in visited or dep_id not in task_map:
            continue
        visited.add(dep_id)
        stack.extend(task_map[dep_id].depends_on)

    return visited


def detect_cycle(tasks: List[TaskSpec], task_ids: Set[str]) -> List[str]:
    """Return task IDs involved in a cycle, or empty list if DAG is valid."""
    adj: Dict[str, List[str]] = {t.id: [] for t in tasks}
    in_degree: Dict[str, int] = {t.id: 0 for t in tasks}

    for t in tasks:
        for dep in t.depends_on:
            if dep in task_ids:
                adj[dep].append(t.id)
                in_degree[t.id] += 1

    queue = [tid for tid, deg in in_degree.items() if deg == 0]
    visited = 0

    while queue:
        node = queue.pop(0)
        visited += 1
        for neighbor in adj[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if visited == len(tasks):
        return []
    return [tid for tid, deg in in_degree.items() if deg > 0]


def find_components(tasks: List[TaskSpec], task_ids: Set[str]) -> List[Set[str]]:
    """Find connected components (treating dep edges as undirected)."""
    adj: Dict[str, Set[str]] = {t.id: set() for t in tasks}
    for t in tasks:
        for dep in t.depends_on:
            if dep in task_ids:
                adj[t.id].add(dep)
                adj[dep].add(t.id)

    visited: Set[str] = set()
    components: List[Set[str]] = []

    for t in tasks:
        if t.id in visited:
            continue
        component: Set[str] = set()
        stack = [t.id]
        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            component.add(node)
            stack.extend(adj[node] - visited)
        components.append(component)

    return components
