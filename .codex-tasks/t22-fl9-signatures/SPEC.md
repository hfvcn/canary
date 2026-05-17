# T22 FL-9 Contract Signatures

## Goal

Add optional contract signature declarations and advisory validation for exported function signature mismatches.

## Scope

- Add `Contract.signatures: Optional[Dict[str, str]]`.
- When validation sees a consumer upstream provider with signatures, parse exported Python functions with `ast.parse` and emit `W_CONTRACT_SIGNATURE_MISMATCH` on mismatches.
- Keep contracts without `signatures` backward compatible with no additional check.
- Verify with `python -m pytest tests/test_contract_signatures.py -v`.

