# CCCC Testing Acceptance Criteria V1

This standard is the repository source of truth for Ralph/Foreman P1 and P2
fix acceptance. It replaces deleted `.trellis` spec storage.

## Test Levels

- `runtime-contract`: enters through a CLI command, daemon IPC op, or daemon
  public entrypoint and asserts the public response plus ledger or
  `WorkflowEngine` authority state.
- `unit-contract`: exercises one module boundary with real domain models.
- `schema-smoke`: checks field names, defaults, parsing, or serialization only.
- `api-surface`: checks that an import, callable, route, or command exists.

## P1/P2 Gate

Every Ralph/Foreman P1 or P2 fix must include at least one `runtime-contract`
test that fails before the fix and passes after it. The test must assert the
authoritative state source and the user-visible result.

Mocking may isolate external IO, clocks, process execution, network calls, or
provider CLIs. It must not replace the core call chain being verified.

`schema-smoke`, `api-surface`, and helper-only tests cannot be the only
completion evidence for P1/P2 fixes.

Requirements that say "must not fallback", "must not complete", or "must not
sync" require a negative `runtime-contract` test.

## Completion Evidence

Task notes or test names must identify the covered level when the distinction is
not obvious from the entrypoint. A valid completion record names:

- the production entrypoint under test;
- the authority source asserted, such as ledger or `WorkflowEngine`;
- the side effect or forbidden side effect;
- the pre-fix failure condition.
