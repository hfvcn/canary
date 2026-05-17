# T13 Security Recipe Library

## Goal
Implement and verify RO-92, RO-93, and RO-94 recipe behavior in `security_recipes.py`.

## Scope
- RO-92 TOCTOU recipe: only emits a two-phase test template for `critical_flow` findings with `temporal_pattern`.
- RO-93 SSRF hostname encoding recipe: emits `W_SSRF_ENCODING_UNCOVERED` at hint level when URL/SSRF critical flows lack the required encoding matrix in checks.
- RO-94 auth timing recipe: emits `W_AUTH_TIMING_UNSAFE` at hint level when auth/token/key critical flows compare tokens in claimed source paths without `secrets.compare_digest`.
- Recipes produce zero output when no matching `critical_flow` exists.

## Validation
Run `python -m pytest tests/test_security_recipes.py -v`.
