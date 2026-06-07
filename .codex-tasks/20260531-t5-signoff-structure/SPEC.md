# T5 Sign-off Structure Validation

Implement FL-56:

- Add `_check_signoff_structure` rule exposed from `security.py`.
- Emit `W_SIGNOFF_STRUCTURE_WEAK` warnings for security-sensitive independent review tasks with sign-off references that lack a structured sign-off verification check.
- Register the rule in `validation_rules/__init__.py` and `validator.py`.
- Cover acceptance criteria in `tests/ralph/test_signoff_structure.py`.

