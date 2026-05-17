# T3 Aegis Rules

Implement AD-3 from plan.yaml:
- five Aegis discipline validation checks
- RULE_DOCS entries
- RULE_VERSION_REGISTRY entries
- focused tests for all rule codes and explain output

Validation:
- `python -m pytest tests/ralph/test_aegis_rules.py -v`
- `python -m pytest tests/ralph/test_ralph_standalone.py -v`
