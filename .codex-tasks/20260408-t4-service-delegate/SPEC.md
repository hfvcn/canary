# T4-service-delegate

实现 `plans/phase4-remediation.yaml` 中 `T4-service-delegate`：

- `RalphService.suggest_ready_batch` / `verify_completion` 在存在 `PlanContext` 时委托到 `cccc.ralph.core`
- 保留无 plan_context 时的 legacy 行为
- 增加 `_resolve_auto_gate(ctx)`，按 `(workflow_id, provider)` 缓存 gate readiness
- 扩展 `VerificationResult.semantic_details`
- 运行指定 pytest 验证
