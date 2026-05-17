# T26 Security Lint Extended

## Goal

Execute T26 from `plans/fix-v38-all-issues.yaml`: extend pre-completion security lint with additional regex patterns, warning behavior for non-blocking findings, and blocking input robustness failures for critical input/search/query flows.

## Scope

- Update `src/cccc/ralph/security_scan.py`.
- Update `src/cccc/daemon/foreman/verification_gate.py`.
- Add `tests/test_security_lint_extended.py`.

## Acceptance

- `eval()` findings are recorded as warnings.
- bare `except:` findings are recorded as warnings.
- critical input/search/query flow with failed input robustness is a blocking verification failure.
- Relevant automated tests pass.
