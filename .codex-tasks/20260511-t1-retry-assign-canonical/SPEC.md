# T1 Retry Assign Canonical Map

Goal: implement `cccc workflow retry TASK --assign AGENT` so retry writes the canonical workflow `assignment_map` used by auto-dispatch.

Boundaries:
- Preserve existing retry behavior when `--assign` is omitted.
- Thread `assign_agent_id` through CLI, IPC handler, workflow task ops, and orchestrator.
- Persist updated assignment data through active workflow state and engine workflow metadata.
- Add focused tests for assignment-map mutation and retry return payload.
