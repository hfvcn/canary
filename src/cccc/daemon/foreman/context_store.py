"""Task context persistence for Context Rollover (E-3).

Saves and loads task execution context so workers can resume
with knowledge of previous attempts.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import List, Optional

import yaml


INITIAL_ITERATION = 1
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


@dataclass
class TaskContext:
    """Execution context for a workflow task."""

    goal: str = ""
    completed_steps: List[str] = field(default_factory=list)
    unresolved: List[str] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)
    iteration: int = 0
    last_error: str = ""
    changed_files: List[str] = field(default_factory=list)
    updated_at: str = ""


class ContextStore:
    """Persist and retrieve task execution contexts."""

    def __init__(self, project_root: "str | Path") -> None:
        self.context_dir = Path(project_root) / ".cccc" / "task_contexts"

    def save(self, task_id: str, context: TaskContext) -> Path:
        """Save context, auto-incrementing iteration."""
        self.context_dir.mkdir(parents=True, exist_ok=True)
        path = self.context_dir / f"{task_id}.yaml"
        persisted = self._build_persisted_context(task_id, context)
        path.write_text(
            yaml.safe_dump(
                asdict(persisted),
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            ),
            encoding="utf-8",
        )
        return path

    def load(self, task_id: str) -> Optional[TaskContext]:
        """Load context for a task. Returns None if not found."""
        path = self.context_dir / f"{task_id}.yaml"
        if not path.exists():
            return None

        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return None
            allowed_fields = TaskContext.__dataclass_fields__
            filtered = {key: value for key, value in data.items() if key in allowed_fields}
            return TaskContext(**filtered)
        except Exception:
            return None

    @staticmethod
    def render_prompt_section(context: TaskContext) -> str:
        """Format context as markdown for worker prompt injection."""
        lines = [f"## 上次执行记录（第 {context.iteration} 次尝试）", ""]
        if context.goal:
            lines.append(f"**目标**: {context.goal}")
        if context.completed_steps:
            lines.append("**已完成**:")
            for step in context.completed_steps:
                lines.append(f"- {step}")
        if context.unresolved:
            lines.append("**未解决**:")
            for item in context.unresolved:
                lines.append(f"- {item}")
        if context.last_error:
            lines.append(f"**上次错误**: {context.last_error}")
        if context.next_steps:
            lines.append("**建议下一步**:")
            for step in context.next_steps:
                lines.append(f"- {step}")
        if context.changed_files:
            lines.append(f"**已变更文件**: {', '.join(context.changed_files)}")
        return "\n".join(lines)

    def _build_persisted_context(self, task_id: str, context: TaskContext) -> TaskContext:
        """Create the stored payload without mutating the input context."""
        existing = self.load(task_id)
        iteration = INITIAL_ITERATION
        if existing is not None:
            iteration = existing.iteration + 1
        elif context.iteration >= INITIAL_ITERATION:
            iteration = context.iteration

        return replace(
            context,
            iteration=iteration,
            updated_at=time.strftime(TIMESTAMP_FORMAT, time.gmtime()),
        )
