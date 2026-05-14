# Gemini Retry Fix

## Goal

Implement T2 from `plans/fix-v5-v21-new.yaml` by adding bounded retry for Gemini
JSON parsing failures in Ralph Agent review and verification flows, plus a
graceful degraded verification fallback for challenge mode.

## Scope

In scope:
- `src/cccc/ralph/agent.py`
- `src/cccc/daemon/foreman/ralph_service.py`
- `tests/test_gemini_retry.py`

Out of scope:
- Broader Gemini provider refactors
- Silent fallback behavior outside the requested verification degrade path

## Validation

Run:

```bash
python -m pytest tests/test_gemini_retry.py -v
```
