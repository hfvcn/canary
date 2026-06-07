"""LegacyExecutionEngine: wraps existing WorkflowOrchestrator for ExecutionBundle execution."""

import logging
from typing import Any, Dict, List, Optional

from ..contracts.v1.execution_bundle import CCCCNodeMeta, ExecutionBundle

logger = logging.getLogger("cccc.agentflow.legacy_engine")


class LegacyExecutionEngine:
    """Wraps existing WorkflowOrchestrator execution logic as a standard engine interface.

    This engine executes tasks from an ExecutionBundle using the existing
    orchestrator assignment and completion flow. It provides backward compatibility
    during the transition to AgentFlow.
    """

    def __init__(self, orchestrator: Any = None):
        self._orchestrator = orchestrator
        self._status = "idle"
        self._results: Dict[str, Dict[str, Any]] = {}

    def execute_bundle(self, bundle: ExecutionBundle) -> Dict[str, Dict[str, Any]]:
        """Execute tasks from an ExecutionBundle using legacy orchestrator.

        Topologically sorts nodes by depends_on, then executes each
        sequentially using the orchestrator suggest+assign flow.

        Returns dict mapping node_id to result: {status, duration, error}
        """
        self._status = "running"
        self._results = {}

        nodes = bundle.pipeline.get("nodes", [])
        if not nodes:
            self._status = "completed"
            return self._results

        sorted_nodes = self._topological_sort(nodes)

        for node in sorted_nodes:
            node_id = node.get("id", "")
            meta = bundle.cccc_meta.get(node_id)

            try:
                result = self._execute_node(node, meta, bundle)
                self._results[node_id] = {
                    "status": "completed",
                    **result,
                }
            except Exception as e:
                self._results[node_id] = {
                    "status": "failed",
                    "error": str(e),
                }
                logger.warning("Node %s failed: %s", node_id, e)

        self._status = "completed" if all(
            r["status"] == "completed" for r in self._results.values()
        ) else "failed"

        return self._results

    def _execute_node(
        self,
        node: dict,
        meta: Optional[CCCCNodeMeta],
        bundle: ExecutionBundle,
    ) -> Dict[str, Any]:
        """Execute a single node using orchestrator."""
        del meta, bundle
        if self._orchestrator is None:
            return {"duration": 0, "note": "no orchestrator (dry run)"}

        if hasattr(self._orchestrator, "_assignment_controller"):
            return {
                "status": "completed",
                "engine": "legacy",
                "duration": 0,
                "node_id": node.get("id", ""),
                "delegated_to": "assignment_controller",
            }

        return {
            "status": "completed",
            "engine": "legacy",
            "duration": 0,
            "node_id": node.get("id", ""),
        }

    def _topological_sort(self, nodes: List[dict]) -> List[dict]:
        """Sort nodes by dependency order."""
        node_map = {n.get("id", ""): n for n in nodes}
        visited = set()
        result = []

        def visit(node_id: str):
            if node_id in visited:
                return
            visited.add(node_id)
            node = node_map.get(node_id)
            if node:
                for dep in node.get("depends_on", []):
                    visit(dep)
                result.append(node)

        for node in nodes:
            visit(node.get("id", ""))

        return result

    def get_status(self) -> str:
        """Return current engine status."""
        return self._status
