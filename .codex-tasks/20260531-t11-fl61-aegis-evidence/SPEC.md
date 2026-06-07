# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- Fix `aegis_evidence_card` evidence parsing and outcome consistency for T11 / FL-61.
- Parse string JSON evidence payloads before extracting `summary`, `text`, or `message`.
- Ensure missing or trivial evidence always produces a failed `E_AEGIS_EVIDENCE_MISSING` check.

## Non-Goals

- Do not change unrelated verification gates.
- Do not refactor existing Aegis intent warning behavior beyond the evidence-missing consistency fix.

## Constraints

- Keep failures visible; do not introduce silent fallbacks.
- Keep changes limited to `verification_gate.py` and the requested regression test.

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: Python
- **Test framework**: pytest

## Deliverables

- `src/cccc/daemon/foreman/verification_gate.py`
- `tests/test_aegis_evidence_consistency.py`

## Done-When

- [ ] JSON string evidence with `summary` passes and does not report missing evidence.
- [ ] Trivial or absent evidence fails with `E_AEGIS_EVIDENCE_MISSING`.
- [ ] Outcome and missing-evidence details are consistent.
- [ ] `python -m pytest tests/test_aegis_evidence_consistency.py -v` passes.

## Final Validation Command

```bash
python -m pytest tests/test_aegis_evidence_consistency.py -v
```
