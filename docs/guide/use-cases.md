# Use Cases

This page focuses on high-ROI, real-world CCCC workflows.

## How to Read This Page

Each scenario includes:
- Goal
- Minimal setup
- Execution flow
- Success criteria
- Common failure points

## Use Case 1: Builder + Reviewer Pair

### Goal

Increase delivery quality without adding human review bottlenecks.

### Minimal Setup

```bash
cd /path/to/repo
cccc attach .
cccc setup --runtime claude
cccc setup --runtime codex
cccc actor add builder --runtime claude
cccc actor add reviewer --runtime codex
cccc group start
```

### Execution Flow

1. Send implementation task to `@builder`.
2. Send review criteria to `@reviewer` (bug risk, regression risk, tests).
3. Require `@builder` to reply with changed files + rationale.
4. Require `@reviewer` to reply with findings (severity + evidence).
5. Use human decision for final merge.

### Success Criteria

- Faster implementation feedback loop.
- Fewer missed regressions.
- Review output is actionable, not generic.

### Common Failure Points

- Task scope too broad.
- Reviewer lacks explicit acceptance criteria.
- Team skips obligation semantics (`reply_required`) for critical asks.

## Use Case 2: Foreman-Led Multi-Agent Delivery

### Goal

Split one medium project into parallel tracks while keeping alignment.

### Minimal Setup

```bash
cccc actor add foreman --runtime claude
cccc actor add frontend --runtime codex
cccc actor add backend --runtime gemini
cccc actor add qa --runtime kimi
cccc group start
```

### Execution Flow

1. Foreman defines shared goal in Context (`vision`, `sketch`, `milestones`).
2. Assign focused tasks via direct recipients.
3. Enforce checkpoint reminders through Automation rules.
4. Foreman integrates and resolves conflicts.
5. QA agent validates key acceptance criteria before handoff.

### Success Criteria

- Parallel execution without major rework churn.
- Clear ownership per track.
- Traceable decision history in ledger.

### Common Failure Points

- Missing shared architecture baseline.
- Agents editing same surfaces without ownership rules.
- No explicit integration checkpoints.

## Use Case 3: Mobile Ops with IM Bridge

### Goal

Operate long-running groups from phone while keeping a reliable audit trail.

### Minimal Setup

```bash
cccc im set telegram --token-env TELEGRAM_BOT_TOKEN
cccc im start
```

Then `/subscribe` in your IM chat.

### Execution Flow

1. Receive progress/error notifications in IM.
2. Send escalation commands to `@foreman` from mobile.
3. Switch to Web UI for deep debugging only when needed.
4. Keep all critical decisions in CCCC messages (not only in IM thread).

### Success Criteria

- You can intervene without laptop access.
- Critical context remains in ledger.
- Downtime is reduced for overnight or offsite ops.

### Common Failure Points

- Exposing Web UI without proper token/gateway.
- Using IM as the only source of truth.
- No restart/recovery playbook.

## Use Case 4: Repeatable Agent Benchmark Harness

### Goal

Run comparable multi-agent sessions with stable logging and replayability.

### Minimal Setup

1. Define fixed task prompts and evaluation criteria.
2. Use same group template and runtime setup per run.
3. Keep automation policies deterministic.

### Execution Flow

1. Create baseline group/template.
2. Run multiple sessions with different runtime combinations.
3. Collect ledger and terminal evidence.
4. Evaluate outcome quality and operational stability.

### Success Criteria

- Comparable runs with low setup variance.
- Reproducible evidence set (`ledger`, state artifacts, logs).
- Clear model/runtime tradeoff signals.

### Common Failure Points

- Hidden prompt drift between runs.
- Uncontrolled environment differences.
- Missing run metadata in messages.

## Use Case 5: Headless CLI Smoke Validation

### Goal

Verify the daemon-driven control plane without relying on Web UI.

### Minimal Setup

```bash
cd /path/to/repo
bash scripts/smoke_headless_workflow.sh
```

### Execution Flow

1. Start an isolated daemon under a temporary `CCCC_HOME`.
2. Create a group and attach the current workspace.
3. Add a headless actor and start the group.
4. Send a directed message and verify inbox delivery.
5. Read the ledger tail and confirm the event path end to end.

### Success Criteria

- Core lifecycle works without opening `/ui/`.
- CLI stays aligned with daemon semantics.
- Validation can run in local shells and CI runners.

### Common Failure Points

- Depending on Web-only flows for state changes.
- Running against a polluted shared `CCCC_HOME`.
- Forgetting to verify inbox and ledger, not just command exit codes.

## Recommended Next Reads

- `docs/guide/operations.md`
- `docs/reference/positioning.md`
- `docs/reference/features.md`
