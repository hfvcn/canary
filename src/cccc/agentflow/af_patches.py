"""CCCC extensions for AgentFlow integration.

Defines CCCC-specific agent kind, actor target, and trace parser
for registering CCCC execution capabilities with AgentFlow.
All changes are additive - no modification to existing AF behavior.
"""

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


CCCC_AGENT_KIND = "cccc"
CCCC_TARGET_KIND = "cccc_actor"


@dataclass(frozen=True)
class CCCCActorTarget:
    """AgentFlow target spec for CCCC actor execution."""

    kind: str = CCCC_TARGET_KIND


class CCCCTraceParser:
    """Parses CCCC actor JSON line trace output for AgentFlow trace pipeline."""

    def parse_line(self, line: str) -> Optional[Dict[str, Any]]:
        """Parse a single trace line from CCCC actor output.

        Expected format: JSON object with at minimum {"type": "...", "data": ...}
        Returns parsed dict or None if line is not valid trace JSON.
        """
        stripped = line.strip()
        if not stripped:
            return None

        try:
            parsed = json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            return None

        if isinstance(parsed, dict) and "type" in parsed:
            return parsed
        return None

    def parse_lines(self, lines: List[str]) -> List[Dict[str, Any]]:
        """Parse multiple trace lines, filtering out non-trace lines."""
        return [
            parsed
            for line in lines
            if (parsed := self.parse_line(line)) is not None
        ]


def register_cccc_extensions(runner_registry: Any = None) -> Dict[str, Any]:
    """Register CCCC extensions with an AF runner registry.

    If runner_registry is provided, registers "cccc_actor" target kind.
    Returns dict of registered extensions for verification.
    """
    extensions = {
        "agent_kind": CCCC_AGENT_KIND,
        "target_kind": CCCC_TARGET_KIND,
        "trace_parser": CCCCTraceParser,
    }
    if runner_registry is not None and hasattr(runner_registry, "register"):
        runner_registry.register(CCCC_TARGET_KIND, extensions)
    return extensions
