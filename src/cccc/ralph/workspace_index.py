"""Shared filesystem index for Ralph validators."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from typing import Dict, Optional, Set, Tuple

from .models import Plan

MISSING_PATH_STAT = -1


def _stat_key(full_path: Path) -> Tuple[str, int, int]:
    """Return ``(str(path), st_size, st_mtime_ns)`` for cache keying."""
    st = full_path.stat()
    return (str(full_path), st.st_size, st.st_mtime_ns)


def _path_exists_key(full_path: Path, rel_path: str) -> Tuple[str, int, int]:
    """Return ``(rel_path, st_size, st_mtime_ns)`` for existence caching."""
    try:
        st = full_path.stat()
    except (OSError, ValueError):
        return (rel_path, MISSING_PATH_STAT, MISSING_PATH_STAT)
    return (rel_path, st.st_size, st.st_mtime_ns)


class WorkspaceIndex:
    """Cached filesystem queries for plan validation against a project directory.

    Internal caches are keyed by ``(path, st_size, st_mtime_ns)`` so that
    daemon-resident instances automatically invalidate when a file is
    modified between successive validation runs.
    """

    def __init__(self, project_root: Path):
        self.project_root = project_root.resolve()
        self._path_cache: Dict[Tuple[str, int, int], bool] = {}
        self._path_to_key: Dict[str, Tuple[str, int, int]] = {}
        self._ast_cache: Dict[Tuple[str, int, int], Optional[ast.Module]] = {}
        self._ast_path_to_key: Dict[str, Tuple[str, int, int]] = {}
        self._src_dir = self.project_root / "src"
        if not self._src_dir.is_dir():
            self._src_dir = self.project_root

    def _safe_path(self, rel_path: str) -> Path | None:
        """Resolve rel_path and ensure it stays within project_root."""
        full_path = (self.project_root / rel_path).resolve()
        try:
            full_path.relative_to(self.project_root)
        except ValueError:
            return None
        return full_path

    def path_exists(self, rel_path: str) -> bool:
        full_path = self._safe_path(rel_path)
        if full_path is None:
            return False
        key = _path_exists_key(full_path, rel_path)
        cached = self._path_cache.get(key)
        if cached is not None:
            return cached
        old_key = self._path_to_key.get(rel_path)
        if old_key is not None and old_key != key:
            self._path_cache.pop(old_key, None)
        result = key[1] != MISSING_PATH_STAT
        self._path_cache[key] = result
        self._path_to_key[rel_path] = key
        return result

    def resolve_module(self, dotted_name: str) -> Optional[Path]:
        """Resolve a local dotted module name to a file path."""
        parts = dotted_name.split(".")
        for base in (self._src_dir, self.project_root):
            module_path = base.joinpath(*parts)
            python_file = module_path.with_suffix(".py")
            if python_file.is_file():
                return python_file
            package_init = module_path / "__init__.py"
            if package_init.is_file():
                return package_init

        try:
            importlib.util.find_spec(dotted_name)
        except (ModuleNotFoundError, ValueError):
            return None
        return None

    def is_stdlib_or_thirdparty(self, dotted_name: str) -> bool:
        """Check if a module is importable but not local to the project."""
        if self.resolve_module(dotted_name) is not None:
            return False
        root_name = dotted_name.split(".")[0]
        try:
            spec = importlib.util.find_spec(root_name)
        except (ModuleNotFoundError, ValueError):
            return False
        return spec is not None

    def ast_parse(self, rel_path: str) -> Optional[ast.Module]:
        full_path = self._safe_path(rel_path)
        if full_path is None:
            return None
        try:
            key = _stat_key(full_path)
        except (OSError, ValueError):
            return None
        if key in self._ast_cache:
            return self._ast_cache[key]
        old_key = self._ast_path_to_key.get(rel_path)
        if old_key is not None and old_key != key:
            self._ast_cache.pop(old_key, None)
        try:
            source = full_path.read_text(encoding="utf-8")
            result = ast.parse(source)
        except (FileNotFoundError, SyntaxError, UnicodeDecodeError):
            result = None
        self._ast_cache[key] = result
        self._ast_path_to_key[rel_path] = key
        return result

    def projected_paths(
        self, plan: Plan, task_id: str, *, include_self: bool = True,
    ) -> Set[str]:
        """Return claimed_paths from the task and all of its dependencies.

        Args:
            include_self: If False, exclude the task's own claimed_paths
                (only include paths from upstream dependencies).  Used by
                RV-24 to detect self-verification paradoxes.
        """
        task_map = {task.id: task for task in plan.tasks}
        if task_id not in task_map:
            return set()

        paths: Set[str] = set()
        visited: Set[str] = set()
        # RV-24: start from deps only when include_self=False
        stack = [task_id] if include_self else list(task_map[task_id].depends_on)

        while stack:
            current = stack.pop()
            if current in visited or current not in task_map:
                continue
            visited.add(current)
            task = task_map[current]
            paths.update(task.claimed_paths)
            stack.extend(task.depends_on)

        return paths

    def is_covered_by_projected(self, rel_path: str, projected: Set[str]) -> bool:
        """Check whether a path falls under any projected claimed path."""
        for claimed in projected:
            if rel_path == claimed:
                return True
            if rel_path.startswith(f"{claimed}/"):
                return True
        return False
