# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- Implement `src/cccc/ralph/semantic_metrics.py` for append-only semantic metrics recording, gate readiness computation, and human-readable reporting.
- Satisfy the `T1-metrics` requirements from `plans/phase4-deep-integration.yaml`.

## Non-Goals

- No CLI wiring.
- No changes to existing Phase 1-3 behavior outside the new module.

## Constraints

- Follow the plan-defined JSONL schema and confidence/outcome enums.
- Keep Ralph stateless per invocation.
- Pass the two verification commands defined in the plan.

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: Python 3.9+
- **Package manager**: setuptools

## Deliverables

- `src/cccc/ralph/semantic_metrics.py`

## Done-When

- [ ] Module imports successfully.
- [ ] Functional gate-readiness test prints `PASS`.

## Final Validation Command

```bash
python -c "from cccc.ralph.semantic_metrics import record_semantic_outcome, compute_gate_readiness, format_gate_report, GateReadiness" && python -c "
import tempfile, pathlib
from cccc.ralph.semantic_metrics import record_semantic_outcome, compute_gate_readiness
with tempfile.TemporaryDirectory() as d:
    p = pathlib.Path(d) / 'metrics.jsonl'
    for i in range(50):
        record_semantic_outcome('test', f'T{i}', 'S_SYMBOL_TARGET_MISSING', 'warning', 'exact', 'true_positive', metrics_path=p)
    record_semantic_outcome('test', 'T50', 'S_SYMBOL_TARGET_MISSING', 'warning', 'exact', 'false_positive', metrics_path=p)
    for i in range(10):
        record_semantic_outcome('test', f'B{i}', 'S_SYMBOL_TARGET_MISSING', 'warning', 'best_effort', 'false_positive', metrics_path=p)
    g_all = compute_gate_readiness('S_SYMBOL_TARGET_MISSING', 0.05, min_samples=50, metrics_path=p)
    assert not g_all.gate_ready
    g_exact = compute_gate_readiness('S_SYMBOL_TARGET_MISSING', 0.05, confidence_filter='exact', min_samples=50, metrics_path=p)
    assert g_exact.gate_ready
    print('PASS')
"
```
