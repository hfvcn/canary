# RO-110 FTS CJK Coverage

## Goal

Add an Aegis discipline warning that detects FTS/search critical flows with CJK context but without substring-oriented verification coverage.

## Scope

- Update `src/cccc/ralph/validation_rules/discipline_security.py`
- Register the rule in `src/cccc/ralph/validation_rules/discipline.py`
- Add focused tests in `tests/test_aegis_security_chain.py`

## Acceptance

- New warning code `W_FTS_CJK_SUBSTRING_MISSING` is emitted only for search/FTS flows with CJK context and missing substring verification.
- Existing SSRF rule structure remains the implementation template.
- Target pytest command passes.
