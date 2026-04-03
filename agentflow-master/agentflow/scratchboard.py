"""File-based shared scratchboard for concurrent agents."""

from __future__ import annotations

import asyncio
import fcntl
from pathlib import Path


class Scratchboard:
    """Shared memory file that multiple agents can read and write.

    For local nodes the scratchboard is a real file in the run directory.
    For remote nodes the orchestrator uploads/downloads it around each
    execution so the agent sees a normal file on the remote filesystem.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("# Shared Scratchboard\n", encoding="utf-8")

    def read(self) -> str:
        if self.path.exists():
            return self.path.read_text(encoding="utf-8")
        return ""

    async def merge(self, node_id: str, remote_content: str) -> None:
        """Merge content returned from a remote node back into the central copy.

        Only appends lines that are not already present (deduplication).
        """
        async with self._lock:
            current = self.read()
            current_lines = set(current.splitlines())
            new_lines = []
            for line in remote_content.splitlines():
                if line.strip() and line not in current_lines:
                    new_lines.append(line)
            if new_lines:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(f"\n## From {node_id}\n")
                    for line in new_lines:
                        f.write(line + "\n")

    async def append(self, node_id: str, content: str) -> None:
        """Directly append content (used by local nodes via orchestrator)."""
        if not content.strip():
            return
        async with self._lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(f"\n## From {node_id}\n{content.strip()}\n")


SCRATCHBOARD_FILENAME = "scratchboard.md"

SCRATCHBOARD_PROMPT_SUFFIX = """

---
SHARED SCRATCHBOARD: {scratchboard_path}
Read this file for context and findings from other agents.
If you discover something critical (patterns, bugs, warnings, insights),
append it concisely to that file. Only add what is not already there.
---"""
