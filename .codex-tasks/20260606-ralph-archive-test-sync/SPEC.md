# Ralph archive test sync

## Goal

Update legacy tests to the tightened Ralph archive contract without modifying production code under `src/`.

## Scope

- Update test fixtures and assertions only.
- Keep negative tests failing for their original reason.
- Verify targeted tests and the full `tests/ralph` suite.

## Non-goals

- No production code changes.
- No weakening of archive or non-suppressible rules.
