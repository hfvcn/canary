# Ralph Boundary Summary

## Coverage Statement
- 这轮边界验收覆盖了 `schema_version` 严格模式、unknown-flow、covers-paths literal 提取与 skip 分支、suppress lease 两个边界、comment-only stale digest、validate --diff 两个边界、audit 2/3 次失败边界、W7 missing-metrics、W10 no-overlap。
- 仍然不是“所有改动都可由纯 plan.yaml 触发”；W7 与 W10 本质上依赖 runtime 状态，所以这里额外做了最小 runtime 探针。

## Plan Boundaries
- base: rc=0 errors=[] warnings=[]
- flow_declared: rc=1 errors=['E_FORBIDDEN_FLOW_LEVEL_TOO_WEAK'] warnings=['W_COVERS_PATHS_UNVERIFIED']
- pytest_k: rc=0 warnings=[]
- make_test: rc=0 warnings=[]
- suppress_expired: rc=0 errors=[] warnings=['W_SUPPRESS_EXPIRED']
- suppress_incomplete: rc=1 errors=['E_SUPPRESS_LEASE_INCOMPLETE']
- strict_unknown_field: rc=2 exception=SchemaUnknownFieldError
- legacy_unknown_field: rc=0 banner=True

## Timing Boundaries
- comment_only_digest: before_issue_ids=['079f60c2d3cceedc'] after_issue_ids=['079f60c2d3cceedc'] blocked_code=plan_digest_divergence
- diff_ruleset_only: rc=0 line=True
- diff_major_mismatch: rc=2

## Audit / Runtime Boundaries
- audit_two_failures_has_flapping=False
- audit_three_failures_has_flapping=True
- audit_skip_complete_has_hint=True
- audit_skip_pass_complete_has_hint=False
- w7_missing_metrics_cache_sizes=[1, 1, 2]
- w10_no_overlap_decision=approved defer_events=0

## Result
- failures: (none)
