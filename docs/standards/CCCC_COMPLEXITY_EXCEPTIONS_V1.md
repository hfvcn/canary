# CCCC Complexity Exceptions V1

This document is the explicit exception register for legacy Ralph/Workflow
modules that still exceed the project complexity limits. New code must not use
this file as permission to add size or branching to these modules.

## Active Exceptions

| Path | Exception | Reason | Exit Criteria |
| --- | --- | --- | --- |
| `src/cccc/daemon/ralph_ipc_handler.py` | file size and handler length | Legacy daemon IPC dispatcher keeps many public ops in one compatibility surface. | Move each Ralph op to a dedicated handler module and keep this file as dispatch glue only. |
| `src/cccc/daemon/foreman/workflow_orchestrator.py` | file size and several lifecycle helpers | Existing workflow lifecycle compatibility still spans admission, assignment, notification, and replay coordination. | Finish moving assignment/projection/gate logic to existing focused modules, then reduce this file below the limit. |
| `src/cccc/daemon/foreman/ralph_service.py` | file size and verification helpers | Service still combines scheduling observation with verify gate compatibility. | Move verification execution and Agent verification mapping to a focused verify module. |
| `src/cccc/daemon/foreman/verification_gate.py` | verification completion helper length | Verify gate compatibility still bridges task events, legacy payloads, and engine recording in one path. | Split payload normalization, agent-mode handling, and engine recording into focused helpers. |
| `src/cccc/ralph/cli.py` | file size and command dispatcher length | CLI still hosts command wiring plus output formatting for compatibility. | Split command implementations into per-command modules while preserving CLI behavior. |
| `src/cccc/ralph/core.py` | `suggest` and semantic helper length | Core planner still owns compatibility behavior for old plan semantics. | Extract planner scoring and semantic checks into focused modules. |
| `src/cccc/ralph/agent.py` | file size and agent/error helper length | Agent review now contains provider setup, prompt building, response parsing, and error envelopes. | Split provider execution, prompt construction, and envelope formatting into separate modules. |
| `src/cccc/ralph/models.py` | file size | Ralph contract models remain co-located for schema compatibility. | Split planning, validation, verification, and batch-result models into separate modules. |
| `src/cccc/ralph/plan_io.py` | file size and plan-state update helper length | Plan loading/saving keeps legacy YAML/JSON compatibility and state mutation helpers together. | Move state update helpers out of plan serialization. |
| `src/cccc/ralph/rules_advisory.py` | file size | Advisory copy for many validation codes is still maintained in one lookup surface. | Move rule documentation into per-rule modules or data files. |
| `src/cccc/ralph/validator.py` | file size and validator helper length | The validator still coordinates structural, semantic, suppress, and beyond-scope issue flows. | Keep only orchestration in this file and move rule-specific helpers to focused modules. |
| `src/cccc/ralph/semantic_validator.py` | file size and semantic rule helper length | Semantic checks remain grouped while rule ownership is still being split. | Move each semantic rule family to `validation_rules/` modules. |
| `src/cccc/ralph/filesystem_validator.py` | file size and filesystem rule helper length | Filesystem validation still combines path checks, pytest parsing, import checks, and coverage checks. | Split filesystem checks by command, import, and coverage responsibility. |
| `src/cccc/ralph/validation_rules/coverage.py` | file size and several rule functions | Coverage rules were split from the validator but still contain multiple rule families. | Split critical-entrypoint, verification, and forbidden-flow rules into separate files. |
| `src/cccc/ralph/validation_rules/structural.py` | file size and structural rule function length | Structural rules still combine graph, role, and integration-spine checks. | Split graph, role, and integration-spine checks into focused modules. |
| `src/cccc/ralph/validation_rules/contracts.py` | contract rule function length | Contract checks still validate multiple contract surfaces in one function. | Split contract rule families into separate helpers under the function limit. |
| `src/cccc/ralph/guide_generator.py` | file size | Guide generator combines template rendering, capability extraction, and markdown assembly. | Split template sections into per-section generators. |
| `src/cccc/ralph/flow_engine.py` | file size | Flow engine combines state management, step orchestration, and check functions for solve/e2e flows. | Split check functions into per-flow modules (already started with flow_steps_e2e.py). |
| `src/cccc/ralph/flow_steps_e2e.py` | file size | E2E flow step checks combine env preparation, tracker scanning, version-marker enforcement, and archive advisory in one module. | Extract tracker-diff helpers (HEAD baseline, header parsing, body remnant scan) into a dedicated submodule once the per-step ownership stabilizes. |
| `src/cccc/ralph/validation_rules/__init__.py` | `get_all_rules` function length | Registry function lists all validation rule references in a single return statement for discoverability. | Not planned — a flat list is the simplest correct form for a registry. |

## Rules

- Exceptions are limited to the paths listed above.
- Edits inside an exception path must not introduce new fallback behavior.
- Any new function in an exception path must satisfy the normal function length
  and nesting limits.
- Tests for Ralph/Workflow P1/P2 changes still follow
  `docs/standards/CCCC_TESTING_ACCEPTANCE_V1.md`.
