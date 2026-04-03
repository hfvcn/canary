"""Shared cloud resource manager for cross-node instance reuse."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable


@dataclass
class _SharedInstance:
    instance_id: str
    ip: str
    region: str
    ref_count: int = 0
    terminate: bool = True
    snapshot: bool = False


class SharedResourceManager:
    """Manage shared EC2/ECS instances across pipeline nodes.

    Nodes with the same ``shared`` ID reuse one cloud instance.
    The instance launches on the first acquire and cleans up
    (terminate/snapshot) when the last release brings the ref count
    to zero.
    """

    def __init__(self) -> None:
        self._instances: dict[str, _SharedInstance] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._expected_refs: dict[str, int] = {}  # shared_id -> total nodes that will use it

    def register_expected(self, shared_id: str, count: int) -> None:
        """Pre-register how many nodes will use this shared group."""
        self._expected_refs[shared_id] = self._expected_refs.get(shared_id, 0) + count

    def _lock(self, shared_id: str) -> asyncio.Lock:
        if shared_id not in self._locks:
            self._locks[shared_id] = asyncio.Lock()
        return self._locks[shared_id]

    async def acquire_ec2(
        self,
        shared_id: str,
        target: Any,
        node: Any,
        prepared: Any,
        on_output: Callable[[str, str], Awaitable[None]],
        launcher: Callable,
        wait_for_ssh: Callable,
    ) -> tuple[str, str]:
        """Get or launch a shared EC2 instance. Returns (ip, instance_id)."""
        async with self._lock(shared_id):
            if shared_id in self._instances:
                inst = self._instances[shared_id]
                await on_output("stderr", f"Reusing shared instance {inst.instance_id} ({inst.ip}) [{inst.ref_count} refs remaining]")
                return inst.ip, inst.instance_id

            await on_output("stderr", f"Launching shared EC2 instance for group '{shared_id}'...")
            instance_id = await asyncio.to_thread(launcher, node, prepared)
            await on_output("stderr", f"Shared instance {instance_id} launched, waiting for SSH...")
            ip = await asyncio.to_thread(wait_for_ssh, target.region, instance_id)
            await on_output("stderr", f"Shared instance ready at {ip}")

            # Use expected refs so the instance survives between sequential nodes
            expected = self._expected_refs.get(shared_id, 1)
            self._instances[shared_id] = _SharedInstance(
                instance_id=instance_id,
                ip=ip,
                region=target.region,
                ref_count=expected,
                terminate=getattr(target, "terminate", True),
                snapshot=getattr(target, "snapshot", False),
            )
            return ip, instance_id

    async def release_ec2(
        self,
        shared_id: str,
        target: Any,
        on_output: Callable[[str, str], Awaitable[None]],
        terminator: Callable,
        snapshotter: Callable | None = None,
    ) -> None:
        """Release a reference. Cleans up when last ref is released."""
        async with self._lock(shared_id):
            inst = self._instances.get(shared_id)
            if inst is None:
                return

            # Last node's settings win
            inst.terminate = getattr(target, "terminate", inst.terminate)
            inst.snapshot = getattr(target, "snapshot", inst.snapshot)

            inst.ref_count -= 1
            if inst.ref_count > 0:
                await on_output("stderr", f"Shared instance {inst.instance_id} still in use [{inst.ref_count} refs]")
                return

            await on_output("stderr", f"Last node done on shared instance {inst.instance_id}")

            if inst.snapshot and snapshotter:
                snap_name = f"agentflow-shared-{shared_id}-{inst.instance_id}"
                await on_output("stderr", f"Creating snapshot {snap_name}...")
                ami_id = await asyncio.to_thread(snapshotter, inst.region, inst.instance_id, snap_name)
                await on_output("stderr", f"Snapshot AMI: {ami_id}")

            if inst.terminate:
                await on_output("stderr", f"Terminating shared instance {inst.instance_id}...")
                await asyncio.to_thread(terminator, inst.region, inst.instance_id)
                await on_output("stderr", f"Shared instance {inst.instance_id} terminated.")
            else:
                await on_output("stderr", f"Shared instance {inst.instance_id} left running (terminate=false).")

            del self._instances[shared_id]

    async def cleanup(
        self,
        on_output: Callable[[str, str], Awaitable[None]],
        terminator: Callable,
    ) -> None:
        """Safety net: terminate any instances left by crashed nodes."""
        for shared_id, inst in list(self._instances.items()):
            try:
                await on_output("stderr", f"Cleanup: terminating leaked instance {inst.instance_id} (group '{shared_id}')")
                await asyncio.to_thread(terminator, inst.region, inst.instance_id)
            except Exception as exc:
                await on_output("stderr", f"Cleanup failed for {inst.instance_id}: {exc}")
        self._instances.clear()
