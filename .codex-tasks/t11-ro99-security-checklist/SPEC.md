# T11 RO-99 Security Checklist

## Goal

Inject a security checklist into challenge verification prompts only when
`critical_flows` names indicate security-sensitive categories.

## Scope

- Read `plan.critical_flows` through the existing Ralph challenge verification path.
- Match keyword categories: input-validation, ssrf, auth, xss, injection.
- Add category-specific checklist text to the Gemini verification prompt.
- Keep non-security critical flows on the existing functional-only review path.

## Validation

`python -m pytest tests/test_challenge_security_checklist.py -v`
