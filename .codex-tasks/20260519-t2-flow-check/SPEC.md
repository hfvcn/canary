# T2: FL-20C + FL-21 + FL-22

## Goal

Strengthen Ralph flow checks so Codex output authenticity and review substance are verified instead of only file presence or shallow markers.

## Scope

- `src/cccc/ralph/flow_engine.py`
- `src/cccc/ralph/flow_steps_e2e.py`
- `src/cccc/ralph/flow_improvement_check.py`
- `tests/ralph/test_flow_engine.py`
- `tests/ralph/test_flow_e2e.py`
- `tests/test_flow_archive_prompt.py`

## Acceptance

1. Codex JSON without a valid `_sig` fails authenticity validation.
2. When `CODEX_BRIDGE_SECRET` is absent, validation falls back to `codex_bridge.py --verify-session SESSION_ID`.
3. Solve step-4 requires substantive tracker additions tied to step-3 review findings.
4. E2E report synthesis must reference review findings from `.ralph-flow/step-4-review/`.
5. Improvement register requires short-tracker deletions for archived items and archive paragraph additions in full tracker.
