# Ralph Review Fixes

## Goal

Fix four review findings from the Ralph RO/RA progress audit:

- IPC verification results must update the workflow engine state.
- Ralph IPC TTL cleanup must apply to real state entries and run from live handlers.
- RalphService must not fall back to orchestrator shadow status for status truth.
- CLI `complete --verify` must not mark `agent_pending` tasks complete.

## Scope

In scope:
- Targeted production fixes in Ralph daemon/service/CLI code.
- Focused regression tests that fail on the reviewed defects.
- A list of the relevant test files used for these tasks.

Out of scope:
- Broad refactors beyond the identified findings.
- Reworking the full Ralph Agent provider implementation.

## Validation

Run focused pytest targets first, then a broader Ralph/workflow subset if time permits.
