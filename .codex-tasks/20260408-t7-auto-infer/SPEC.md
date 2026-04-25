# T7 auto infer semantic targets

## Goal

Execute `T7-auto-infer` from `plans/phase4-deep-integration.yaml`.

## Scope

- Read the plan entry and current `validate_semantic()` behavior first.
- Add `auto_infer_semantic_targets(task, provider) -> List[SemanticTarget]`.
- Integrate plan-level `auto_infer` gate checks into `validate_semantic()`.
- Ensure inferred targets never emit error-level issues, even under strict mode.
- Run the exact verification commands requested by the user.

## Constraints

- Use gate readiness threshold `0.10` and `min_samples=50`.
- Emit `S_AUTO_INFER_NOT_READY` as warning when the gate is not ready.
- Emit `S_TARGETS_AUTO_INFERRED` as hint when targets are inferred.
- Run normal semantic validation rules against inferred targets.
- If an issue is supported only by inferred targets, downgrade severity from error to warning.
