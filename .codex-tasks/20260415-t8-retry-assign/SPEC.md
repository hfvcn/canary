# T8 Retry Assign

Goal: implement `cccc workflow retry --assign AGENT_ID` without changing engine retry contract (`retry -> READY`).

Boundaries:
- Read and preserve existing retry flow end-to-end.
- Use sequential orchestrator operations for retry+assign in one CLI call.
- Update focused tests and run required verification commands.
