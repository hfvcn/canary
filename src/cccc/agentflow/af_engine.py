"""AFExecutionEngine: uses AgentFlow orchestrator for DAG scheduling."""

import asyncio
import logging
from typing import Any, Callable, Dict, Optional

from ..contracts.v1.execution_bundle import CCCCNodeMeta, ExecutionBundle
from .actor_runner import CCCCActorRunner, RawExecutionResult
from .af_patches import CCCC_AGENT_KIND, register_cccc_extensions

logger = logging.getLogger("cccc.agentflow.af_engine")
ENGINE_PREFERENCE_LEGACY = "legacy"
StatusCallback = Callable[[str, str, str], None]


class AFExecutionEngine:
    """Execution engine using AgentFlow orchestrator for DAG scheduling."""

    def __init__(
        self,
        agent_pool: Any = None,
        actor_gateway: Any = None,
        trace_bridge: Any = None,
    ):
        self._pool = agent_pool
        self._gateway = actor_gateway
        self._trace = trace_bridge
        self._workflow_runs: Dict[str, Dict[str, Any]] = {}

    def execute_bundle(
        self,
        bundle: ExecutionBundle,
        workflow_id: str = "default",
        status_callback: Optional[StatusCallback] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Submit bundle to AF orchestrator for execution.

        Uses DAG scheduling from AgentFlow for dependency resolution
        and concurrent execution. CCCC retains verification authority.

        Raises RuntimeError if AF orchestrator is not available.
        """
        if bundle.engine_preference == ENGINE_PREFERENCE_LEGACY:
            raise ValueError("AF engine cannot execute legacy-preference bundle")

        run = {"status": "running", "results": {}}
        self._workflow_runs[workflow_id] = run

        nodes = bundle.pipeline.get("nodes", [])
        if not nodes:
            run["status"] = "completed"
            return run["results"]

        extensions = register_cccc_extensions()
        logger.debug("Registered AF extensions for %s: %s", CCCC_AGENT_KIND, extensions)

        sorted_nodes = self._topological_sort(nodes)
        pending = list(sorted_nodes)
        known_ids = {node.get("id", "") for node in sorted_nodes}
        completed: set[str] = set()
        loop = asyncio.new_event_loop()
        try:
            while pending:
                tier = [
                    node for node in pending
                    if self._dependencies_completed(node, completed, known_ids)
                ]
                if not tier:
                    for node in pending:
                        node_id = node.get("id", "")
                        run["results"][node_id] = self._blocked_result(node, completed, known_ids)
                    break
                for node_id, result in loop.run_until_complete(
                    self._execute_tier(tier, bundle, workflow_id, status_callback)
                ):
                    run["results"][node_id] = result
                    if result["status"] == "completed":
                        completed.add(node_id)
                tier_ids = {node.get("id", "") for node in tier}
                pending = [node for node in pending if node.get("id", "") not in tier_ids]
        finally:
            loop.close()

        run["status"] = "completed" if all(
            result["status"] == "completed"
            for result in run["results"].values()
        ) else "failed"

        return run["results"]

    async def _execute_tier(
        self,
        nodes: list,
        bundle: ExecutionBundle,
        workflow_id: str,
        status_callback: Optional[StatusCallback],
    ) -> list[tuple[str, Dict[str, Any]]]:
        results = await asyncio.gather(*[
            asyncio.to_thread(
                self._execute_node,
                node=node,
                node_id=node.get("id", ""),
                meta=bundle.cccc_meta.get(node.get("id", "")),
                bundle=bundle,
                workflow_id=workflow_id,
                status_callback=status_callback,
            )
            for node in nodes
        ])
        return [(node.get("id", ""), result) for node, result in zip(nodes, results)]

    def _execute_node(
        self,
        node: dict,
        node_id: str,
        meta: Optional[CCCCNodeMeta],
        bundle: ExecutionBundle,
        workflow_id: str,
        status_callback: Optional[StatusCallback],
    ) -> Dict[str, Any]:
        interim_statuses: list[str] = []

        try:
            interim_statuses = ["assigned"]
            self._report_status(node_id, "assigned", workflow_id, status_callback)

            interim_statuses.append("running")
            self._report_status(node_id, "running", workflow_id, status_callback)
            result = self._execute_with_af(node, meta, bundle)

            interim_statuses.append("verifying")
            self._report_status(node_id, "verifying", workflow_id, status_callback)
            return {"status": "completed", "interim_statuses": interim_statuses, **result}
        except Exception as e:
            logger.warning("AF node %s failed: %s", node_id, e)
            return {
                "status": "failed",
                "error": str(e),
                "failure_category": "engine_error",
                "interim_statuses": interim_statuses + ["failed"],
            }

    @staticmethod
    def _report_status(
        node_id: str,
        status: str,
        workflow_id: str,
        status_callback: Optional[StatusCallback],
    ) -> None:
        if status_callback:
            status_callback(node_id, status, workflow_id)

    def _execute_with_af(
        self,
        node: dict,
        meta: Optional[CCCCNodeMeta],
        bundle: ExecutionBundle,
    ) -> Dict[str, Any]:
        """Execute a node through AF scheduling with CCCC verification gate."""
        del bundle
        node_id = node.get("id", "")

        if not all([self._pool, self._gateway, self._trace]):
            raise RuntimeError(
                "AF engine requires agent_pool, actor_gateway, and trace_bridge "
                f"for node {node_id}; missing dependencies cannot be stubbed in production"
            )

        runner = CCCCActorRunner(
            agent_pool=self._pool,
            actor_gateway=self._gateway,
            event_stream=self._trace,
            sidecar={node_id: meta},
        )
        loop = asyncio.new_event_loop()
        try:
            result: RawExecutionResult = loop.run_until_complete(runner.execute(node))
        finally:
            loop.close()

        return {
            "engine": "af",
            "exit_code": result.exit_code,
            "cancelled": result.cancelled,
            "attempt_id": getattr(runner, "_last_attempt_id", ""),
            "verification_pending": True,
        }

    @staticmethod
    def _dependencies_completed(
        node: dict,
        completed: set[str],
        known_ids: set[str],
    ) -> bool:
        return all(dep in completed or dep not in known_ids for dep in node.get("depends_on", []))

    @staticmethod
    def _blocked_result(
        node: dict,
        completed: set[str],
        known_ids: set[str],
    ) -> Dict[str, Any]:
        unmet = [dep for dep in node.get("depends_on", []) if dep in known_ids and dep not in completed]
        return {
            "status": "failed",
            "error": f"unmet dependencies: {', '.join(unmet) or '(none)'}",
            "failure_category": "dependency_failed",
            "interim_statuses": ["failed"],
        }

    def _topological_sort(self, nodes: list) -> list:
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

    def get_status(self, workflow_id: str = "default") -> str:
        run = self._workflow_runs.get(workflow_id)
        return run["status"] if run else "idle"

    @staticmethod
    def availability_reason() -> str:
        """Return an empty string when AF is available, else the failure reason."""
        try:
            register_cccc_extensions()
        except Exception as exc:
            return str(exc).strip() or exc.__class__.__name__
        return ""

    @staticmethod
    def is_available() -> bool:
        """Check if AF orchestrator is available."""
        return AFExecutionEngine.availability_reason() == ""
