# T12 AD-11 Security Check Generation

## Goal

Enhance `ralph validate --generate-security-checks plan.yaml` so Ralph emits deterministic behavioral security check specs from plan metadata.

## Scope

- Read `goal_behavior`, `acceptance_criteria`, `provides.schema_hint`, and security-related `critical_flows`.
- Use existing security recipe concepts and critical-flow categories to generate check commands.
- Emit a JSON list of `{name, command, auto_generated: true}`.
- Generate no checks when no security critical flow is declared.

## Validation

`python -m pytest tests/test_security_check_generator.py -v`
