# T20 FL-5 Guide Advisory Warnings

## Goal

In `guide_generator.py`, make `guide --update` flow-step checks treat "affected by changes - review manually" warnings on non-main branches as advisory: display them, but do not fail the step.

## Scope

- Locate the flow-step blocking logic.
- Keep the warning visible to the user.
- Avoid adding silent fallbacks or unrelated guardrails.
- Verify with `python -m pytest tests/test_flow_guide_advisory.py -v`.

## Acceptance

- Relevant flow step succeeds when only these advisory warnings are present.
- Existing explicit failures remain failures.
- The requested pytest target passes.
