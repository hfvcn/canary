# Progress

## 2026-04-28

- Confirmed the gap is only present as a broad plan item, not as a concrete main-path issue in `todo/问题清单-v5-ralph.md`.
- Added RO-33 to track the missing assignment-startup wiring.
- Added prompt projection metadata to `ReadyBatchSuggestion` and preserved it through daemon IPC reconstruction.
- Stored prompt projection metadata in tracked workflow state during batch registration.
- Passed tracked issues, recommended tests, and forbidden flows into `_build_task_prompt()` during assignment startup.
- Added assignment-startup regression tests and prompt metadata round-trip coverage.
- Validation passed: `pytest tests/test_assignment_prompt_projection.py tests/test_prompt_issue_digest.py tests/test_prompt_recommended_tests.py tests/test_prompt_forbidden_flows.py -q`.
- Syntax check passed with `python -m py_compile` on modified modules.
- Ruff check passed via `uvx ruff check` on modified prompt projection files after removing existing unused imports, an unused heartbeat local, and no-op f-string prefixes.
