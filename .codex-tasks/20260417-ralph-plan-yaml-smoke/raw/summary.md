# Ralph Plan YAML Smoke

## Validate Before Edit
- return_code: 0
- errors: (none)
- warnings: (none)
- hints: H_SEMANTIC_COVERAGE_DEGRADED

## Completion Before Edit
- accepted: True
- verification_outcome: passed
- reason: (none)

## Validate After Edit
- return_code: 1
- errors: E_COVERS_UNKNOWN_FLOW
- warnings: W_COVERS_PATHS_UNVERIFIED
- hints: H_SEMANTIC_COVERAGE_DEGRADED

## Diff
- Validation Diff:
- Added (2):
-   - W_COVERS_PATHS_UNVERIFIED [T1] #06fa83a29b4df114: task 'T1' verification command references 'tests/test_app.py' outside claimed_paths and verification.covers.paths
-   - E_COVERS_UNKNOWN_FLOW [T1] #e754f50e82042ffb: task 'T1' covers flow 'ghost-flow' which is not declared in critical_flows or forbidden_flows
- Removed (0):
- Unchanged: 1

## Completion After Edit
- blocked.accepted: False
- blocked.code: plan_digest_divergence
- blocked.reason: plan_digest_divergence: Plan file '/Users/vfch/Documents/project/canary/cccc-main-git/.codex-tasks/20260417-ralph-plan-yaml-smoke/fixture/project/plan.yaml' was modified after registration (registered=8bebfd9ac0dd… current=b8fd339a103b…). Re-register the plan or use --force-stale-complete to override.
- override.accepted: True
- override.verification_outcome: passed
- divergence_event_count: 3
