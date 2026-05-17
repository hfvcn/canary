# T24 UX-12 Suspicious Duration Exemptions

## Goal

Exempt inherently fast commands from `SUSPICIOUS` duration marking in `ralph_service.py`.

## Scope

- Add a command-prefix check for `grep`, `test`, `[`, `true`, and `false`.
- Skip `SUSPICIOUS` marking for those prefixes regardless of duration.
- Create or update `tests/test_suspicious_exempt.py`.
- Validate with `python -m pytest tests/test_suspicious_exempt.py -v`.

## Constraints

- Keep failures explicit; do not add silent fallbacks.
- Keep changes narrowly scoped to the duration-classification behavior.
