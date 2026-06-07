# T18 AF-M4a AF Source Patches

## Goal

Add CCCC-side AgentFlow extension points without changing AgentFlow behavior.

## Scope

- Create `src/cccc/agentflow/af_patches.py`.
- Create `tests/agentflow/test_af_patches.py`.
- Verify with `python -m pytest tests/agentflow/test_af_patches.py -v`.

## Non-goals

- Do not modify `/Users/vfch/Downloads/agentflow-master/`.
- Do not introduce fallback behavior or mock success paths.
