# T19 FL-15 + FL-7 Flow Tracker Prompt Guidance

## Goal

Update Ralph flow step instructions so E2E step 6 and solve step 4 explicitly direct agents to record new findings, archive resolved tracker items, and include a current-session version marker.

## Acceptance Criteria

1. E2E step-6 `instruction_text` contains guidance for all three tracker tasks.
2. Solve step-4 `instruction_text` mentions archive and version marker.
3. Agent following instructions produces all three categories of tracker updates.

## Validation

Run:

```bash
python -m pytest tests/test_flow_archive_prompt.py -v
```
