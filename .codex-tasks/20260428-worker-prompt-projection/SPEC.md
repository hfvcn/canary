# Worker Prompt Projection Wiring

Goal: ensure Ralph findings lessons reach the real worker assignment prompt, not only direct prompt-builder tests.

Scope:
- Record the missing main-path wiring in the v5 Ralph issue checklist.
- Wire real tracked assignment context into worker prompt construction.
- Add focused tests that exercise assignment startup, not only `_build_task_prompt()` directly.

Out of scope:
- Inventing synthetic findings when no validation context exists.
- Adding fallback success paths or suppressing missing data.
