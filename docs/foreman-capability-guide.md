# Foreman Capability Guide

> Generated from source code: 2026-05-14 (post v31 fixes)
> Source: `src/cccc/` (CLI, Ralph, daemon, kernel)
> **Do not reuse across code versions — regenerate after each fix cycle**
> v31 changes: workflow.completed/failed ledger events (RO-77), retry workflow_id resolution (RO-78), python -c syntax validation (RO-79), ModuleSpec decomposition (BP-2), cross-task I/O contract validation (BP-4), batch_e2e_command (BP-5)

## 1. CLI Commands and Flags

### `cccc workflow submit`

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--workflow-id` | str | required | Workflow identifier |
| `--tasks` | path | — | Path to tasks JSON |
| `--plan` | path | — | Path to plan.yaml (mutually exclusive with `--tasks`) |
| `--rationale` | str | `""` | Optional rationale text |
| `--parallelism` | int | `1` | Estimated parallelism hint |
| `--auto-process` | bool | `true` | Auto-process suggestion immediately |
| `--auto-start-agents` | bool | `true` | Auto-start assigned agents |
| `--auto-dispatch` | bool | `false` | Enables auto-dispatch mode |
| `--assignment-map` | json | `{}` | `{"task_id": "agent_id"}` explicit assignments |
| `--stall-auto-reassign` | bool | `false` | Auto-retry stalled tasks |
| `--group` | str | active group | Target group ID |

With `--plan`: loads Plan, converts non-completed TaskSpec to TaskRef via `to_task_ref()`, sends `ralph_register_and_suggest` op.

### `cccc workflow status`

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--group` | str | active group | Target group ID |
| `--workflow-id` | str | optional | Specific workflow (omit for all) |

### `cccc workflow retry`

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--task-id` | str | required | Task to retry |
| `--group` | str | active group | Target group ID |
| `--assign` | str | optional | Pin retry to specific agent |

**RO-78**: `_resolve_task_workflow_id()` now queries existing workflow to resolve the correct workflow_id, preventing mismatch errors. `register_and_suggest_inner()` also calls `resolve_workflow_id_for_tasks()`.

### `cccc task complete`

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--task-id` | str | required | Task ID |
| `--agent-id` | str | required | Completing agent |
| `--changed-file` | str | repeatable | Files modified |
| `--force` | bool | false | Skip verification gate |
| `--force-stale-complete` | bool | false | Allow stale plan digest |
| `--evidence` | json | optional | Evidence object |
| `--workflow-id` | str | optional | Override workflow ID |

### `ralph validate <plan>`

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--format` | json\|text | text | Output format |
| `--project-root` | path | auto-detect | Project root |
| `--suppress` | str[] | [] | Suppress validation codes |
| `--gate` | terminal\|branch\|repo | none | Quality-gate rollout mode |
| `--no-semantic` | bool | false | Suppress semantic findings |
| `--no-agent` | bool | false | Skip AI agent review |
| `--compact` | bool | false | Show only errors + high-confidence warnings |
| `--show-schema` | bool | false | Print full plan schema and exit |
| `--diff` | path path | — | Diff two saved validation JSON reports |

Exit codes: `0` = valid, `1` = errors, `2` = internal error.

### `ralph suggest <plan>`

Shows next ready batch. Returns `BatchResult` with `ready`, `blocked`, `rationale`, `task_summaries`.

### `ralph verify <plan> --task <ID>`

Runs verification checks locally. Returns outcome (`passed`/`failed`/`skipped`/`agent_pending`).

### `ralph complete <plan> --task <ID>`

Marks task completed in plan state. `--verify` runs verification first.

### `ralph explain <plan> --task <ID>` / `--code <CODE>`

Shows why a task is blocked, or documents a validation rule code.

---

## 2. Verification Modes

### Three Modes

| Mode | Behavior | Auto-upgrade |
|------|----------|-------------|
| `ralph` | Runs structured verification commands (checks[]) | Upgraded to `challenge` if claimed_paths overlap CriticalFlow entrypoints |
| `agent` | Skips commands; calls Gemini agent for AI review | — |
| `challenge` | Runs `ralph` first, then `agent` if ralph passes | — |

### Shell Command Execution

- Shell operator detection: `&&`, `||`, `|`, `;` → wraps in `bash -c "set -o pipefail; <cmd>"`
- Default timeout: `60` seconds (per-check `CheckSpec.timeout` overrides)
- Suspicious speed: < `50ms` for non-trivial commands → prefixed with `[SUSPICIOUS]`
- Exit code: `passed` if returncode == `expected_exit_code` (default 0)

### Mock Tests (BP-1)

Defined in `task.verification.mock_tests`. Flow:
1. Run `setup_command` (if any) → fail stops mock test
2. Run `verify_command` → exit 0 = passed
3. ALL pass → proceed to agent verification
4. ANY fail → immediate `failed` result
5. Workers never see mock_tests content (adversarial)

### Batch E2E (BP-5, NEW)

Plan-level `batch_e2e_command` executes after batch completion:
- Runs in background thread (non-blocking to next batch)
- Uses `batch_e2e_timeout` (default 300s)
- Command read from plan file via `WorkflowMeta.plan_path`
- stdout/stderr truncated to last 2000 chars

### Output Contract Check (BP-4, NEW)

After verification passes, `_check_output_contract()` checks `expected_output.paths` vs actual `changed_files`:
- Missing paths → emits `workflow.verification_warning` event
- Non-blocking: exceptions silently caught

### Verification Outcomes

| Outcome | Meaning |
|---------|---------|
| `passed` | All checks passed |
| `force_passed` | Skipped via `--force` (no completer mismatch) |
| `failed` | One or more checks failed |
| `skipped_blocked` | No commands → task FAILED |
| `timeout` | Command exceeded timeout |
| `agent_pending` | Agent verification pending (RA-3) |

---

## 3. DAG Gating and Batch Scheduling

### suggest_ready_batch Logic

For each task:
1. All `depends_on` completed in engine state
2. No write-set conflict with currently **running** tasks
3. No write-set conflict with **already-selected** batch tasks

Write-set conflict: claimed_paths prefix overlap. `"__global__"` conflicts with everything.

### Ordering

Tasks sorted by **unlock score** (descending) — counts how many downstream tasks would become unblocked. Prioritizes critical path.

### Blocked Task Kinds

| Kind | Meaning |
|------|---------|
| `waiting` | Hard dependency not met |
| `deferred` | Write-set conflict with running/batch peer |

---

## 4. Stall Detection

### Thresholds

| Task State | Threshold |
|-----------|-----------|
| RUNNING | `300s` since last heartbeat |
| ASSIGNED (never started) | `min(effective, 120s)` since assigned_at |
| Codex runtime (RUNNING) | `max(300s, 1800s)` — 30 minute Codex threshold |

Reference time priority: `last_heartbeat` → `assigned_at` → `started_at`

### sweep_stalled_tasks (RalphService)

| Condition | Status |
|-----------|--------|
| `now - last_seen_at > 120s` | `"offline"` |
| `now - last_progress_at > 600s` | `"stalled"` |

### stall_auto_reassign

When enabled (`--stall-auto-reassign`), stalled tasks are automatically retried without manual intervention.

---

## 5. Plan Schema

### Plan (top-level)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `schema_version` | str? | None | Enables strict schema when set |
| `tasks` | TaskSpec[] | [] | All tasks |
| `state` | PlanState | empty | completed/running/failed task IDs |
| `critical_flows` | CriticalFlow[] | [] | Named E2E flows to verify |
| `forbidden_flows` | ForbiddenFlow[] | [] | Anti-bypass declarations |
| `required_issues` | str[] | [] | Issue IDs that must be addressed |
| `suppress_codes` | str[] | [] | Validation codes to suppress |
| `suppress_instances` | SuppressInstance[] | [] | Per-code suppressions with governance |
| `batch_e2e_command` | str? | None | **BP-5** Shell command for batch E2E |
| `batch_e2e_timeout` | int | 300 | **BP-5** Timeout for batch_e2e_command |
| `semantic_mode` | str | "off" | advisory, strict, off |

### TaskSpec

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | str | required | Unique task ID |
| `title` | str | "" | Short description |
| `role` | leaf\|integration\|verification | leaf | Task role |
| `type` | frontend\|backend\|general | general | For agent pool matching |
| `depends_on` | str[] | [] | Dependency task IDs |
| `claimed_paths` | str[] | [] | Files/dirs this task modifies |
| `awareness_paths` | str[] | [] | Read-only paths |
| `goal_behavior` | str | "" | What to accomplish |
| `acceptance_criteria` | str | "" | How to verify completion |
| `verification_mode` | ralph\|agent\|challenge | ralph | Verification strategy |
| `verification` | Verification? | None | Structured verification spec |
| `provides` | Contract[] | [] | Produced artifacts |
| `consumes` | Contract[] | [] | Required artifacts |
| `addresses` | str[] | [] | Issue IDs fixed |
| `expected_input` | dict | {} | **BP-3** Input contract keys |
| `expected_output` | dict | {} | **BP-3/4** Output contract; `paths` key for runtime check |
| `modules` | ModuleSpec[]? | None | **BP-2** Sub-module decomposition |

### ModuleSpec (BP-2, NEW)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | str | required | Module identifier |
| `description` | str | "" | What this module does |
| `input_spec` | dict | {} | Input specification |
| `output_spec` | dict | {} | Output specification |
| `internal_depends_on` | str[] | [] | Other module IDs within this task |

Modules are **advisory** — rendered in worker prompt to guide decomposition. Not separate workflow tasks.

### Verification

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `level` | compile\|unit\|integration\|e2e | required | Verification level |
| `command` | str | "" | Single command (use checks[] for multiple) |
| `checks` | CheckSpec[] | [] | Named verification checks |
| `covers` | VerificationCovers | empty | Tasks/paths/flows covered |
| `cleanup_patterns` | str[]? | None | Pre-verification cleanup globs |
| `mock_tests` | MockTestCase[]? | None | **BP-1** Mock tests for agent mode |

### CheckSpec

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | str | required | Check name |
| `command` | str | required | Shell command |
| `required` | bool | true | Failure stops subsequent checks |
| `expected_exit_code` | int | 0 | Expected exit code |
| `timeout` | int? | None | Override timeout (default 60s) |

### MockTestCase

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | str | required | Test name |
| `input` | dict | {} | Input data |
| `expected_output` | dict | {} | Expected output |
| `setup_command` | str | "" | Setup command (pre-verify) |
| `verify_command` | str | required | Verification command |

---

## 6. Auto-Dispatch and assignment_map

### Assignment Flow

1. Conflict check → reject tasks in active states
2. Workflow ID resolution (RO-78: reuse existing ID)
3. Single-writer deferral (write-set conflicts)
4. Cross-workflow pressure deferral (300s cooldown)
5. Agent pool scoring OR explicit assignment_map

### assignment_map

`--assignment-map '{"T1": "peer-a", "T2": "peer-b"}'`

Stored on WorkflowMeta. Bypasses agent pool scoring with `assignment_reason="foreman_explicit"`.

### Agent Pool Scoring

Key factors: task affinity (+40), worker role (+30), required capabilities (+20), model strength (+10), path domain (+25). Minimum score: 50.

---

## 7. Workflow Monitor Invariants

### MonitorConfig Modes

| Mode | Behavior |
|------|----------|
| `OBSERVE` | Log only |
| `WARN` | Log + emit warning event |
| `BLOCK` | Reject state transition |

### Check Functions

| Check | Fires When | Default Mode |
|-------|-----------|-------------|
| `check_silent_agent` | No events within 300s of assignment | OBSERVE |
| `check_progress_stall` | Progress stuck for 300s across 5+ heartbeats | OBSERVE |
| `check_path_deviation` | Worker tries to assign tasks via chat | OBSERVE |
| `check_unauthorized_subagent` | Unknown agent attempts task | OBSERVE |
| `check_completer_mismatch` | Completing agent != assigned agent | OBSERVE |
| `check_file_overstepping` | Worker modified files outside claimed_paths | OBSERVE |

---

## 8. v31 New Capabilities

### RO-77: Workflow Terminal Ledger Events

`complete_workflow()` now emits `workflow.completed` or `workflow.failed` before cleanup:
- `workflow.completed` when all tasks succeeded (failed_count == 0)
- `workflow.failed` when any task failed/archived
- Data: workflow_id, completed_count, failed_count, total, summary

### RO-78: Retry Workflow ID Resolution

`register_and_suggest_inner()` calls `resolve_workflow_id_for_tasks()` to resolve existing workflow_id. Prevents `ValueError("workflow_id mismatch")` on retry.

### RO-79: Python Syntax Validation at Validate Time

`check_verification_command_syntax()` now runs during `ralph validate`:
- Detects `python -c` payloads via `shlex.split()`
- Validates with `ast.parse()` — syntax errors emit `W_VERIFICATION_COMMAND_INVALID_SYNTAX`
- Detects literal `\n` in payloads (common mistake)

### BP-2: ModuleSpec Decomposition

Tasks can declare `modules: List[ModuleSpec]` for advisory sub-module structure. Rendered in worker prompt as "Module Decomposition" section. Validated: unique IDs, valid `internal_depends_on`.

### BP-4: Cross-Task I/O Contract Validation

Static: `W_CROSS_TASK_IO_MISMATCH` when task B expects input keys not in dependency A's expected_output.
Runtime: `_check_output_contract()` checks `expected_output.paths` vs changed_files after verification passes.

### BP-5: Batch E2E Command

Plan-level `batch_e2e_command` runs after batch completion:
- Loaded from plan file via `WorkflowMeta.plan_path`
- Runs in background thread (non-blocking)
- Timeout: `batch_e2e_timeout` (default 300s)
- Static validation: `W_BATCH_E2E_NO_COMMAND` for multi-batch plans without the field

---

## 9. Ledger Event Kinds

| Kind | Description |
|------|-------------|
| `workflow.task_registered` | Task registered with engine |
| `workflow.batch_registered` | Batch of tasks registered |
| `workflow.batch_approved` | Batch approved, tasks assigned |
| `workflow.task_started` | Worker started task |
| `workflow.task_heartbeat` | Worker heartbeat |
| `workflow.task_reported_completed` | Worker reported completion |
| `workflow.task_failed` | Task failed |
| `workflow.verification_passed` | Verification passed |
| `workflow.verification_failed` | Verification failed |
| `workflow.verification_skipped` | Verification skipped |
| `workflow.verification_skipped_blocked` | Skipped, completion blocked |
| `workflow.verification_agent_pending` | Agent verification pending |
| `workflow.verification_warning` | Non-fatal warning |
| `workflow.retry_requested` | Task retry requested |
| `workflow.task_blocked` | Task blocked |
| `workflow.task_deferred` | Task deferred |
| `workflow.monitor_violation` | Monitor invariant triggered |
| `workflow.transition_rejected` | Transition rejected |
| `workflow.completed` | **RO-77** Workflow completed |
| `workflow.failed` | **RO-77** Workflow failed |
| `workflow.contract_violation` | **BP-4** Contract violation (unused, reserved) |
