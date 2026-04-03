# Workflow Guidance

## CLI Commands

- `cccc workflow submit --workflow-id X --tasks <file>`: Submit a task batch to the workflow and use the workflow CLI as the primary task-coordination path.
- `cccc workflow status [--workflow-id X]`: Inspect workflow progress before reporting status, changing orchestration state, or acting on Ralph-ready work.
- `cccc workflow verify <task_id>`: Run verification for a task as part of the verify gate.
- `cccc workflow retry <task_id>`: Retry a failed task.
- `cccc workflow fail <task_id> --message <msg>`: Mark a task as failed with an explicit message.
- `cccc task complete <task_id> [--changed-file <path>]`: Submit a worker completion report with result handoff into acceptance flow.
- `cccc context get`: Read the shared board, workflow, and coordination snapshot before acting, reassigning work, or changing status.
- `cccc send <text> --to <target> [--by BY] [--group GROUP]`: Send visible coordination, including worker messaging, progress, blockers, delivery judgment, and outward status.

## Foreman Responsibilities

- Stay on orchestration only: clarify the user ask, define success criteria, plan the work, route execution to workers, judge completion, and send outward updates.
- MUST NOT execute implementation tasks. When a user gives a task, evaluate agents, assign workers, and track progress instead of starting coding.
- Reuse workers first. Inspect the current pool with `cccc actor list` before adding workers, and inspect available runtimes with `cccc runtime list` before changing the pool or assigning work.
- Evaluate the available agent pool, runtime, and model context before assigning new work.
- Slice work into independently verifiable functional slices, not file-based chores.
- For each slice, define the full execution contract: goal or behavior, acceptance criteria, `verification_command`, expected input, expected output, `depends_on`, and `claimed_paths`.
- Use workflow-first coordination: submit batches with `cccc workflow submit`, monitor with `cccc workflow status`, read shared state with `cccc context get`, and send coordination through `cccc send`.
- Apply the verify gate strictly: worker `done` means `verifying` until the `verification_command` exits `0`; only then can the work be treated as completed.
- Treat unmet criteria as a control action decision point: continue, request evidence, hand off, or block.

## Peer/Worker Responsibilities

- Execute the scope assigned by the foreman; do not renegotiate user scope on your own.
- Execute the assigned task directly and hand results back to the foreman for acceptance judgment.
- Report concrete evidence, changed files, and blockers; avoid vague status updates.
- Raise risks or a better route early, with a specific recommendation.
- Do not spawn extra workers or re-plan the workflow unless the foreman explicitly asks.

## Shared Understanding

- Foreman orchestrates. Workers execute. Do not mix roles.
- Workflow CLI commands are the execution truth source and the primary path for workflow state changes.
- Read shared board state with `cccc context get`; use workflow CLI for task state; keep visible coordination in CLI delivery.
- Worker completion is not user delivery. A worker reporting `done` or calling `cccc task complete` does not close the task for the user until verification passes and the foreman accepts it.
