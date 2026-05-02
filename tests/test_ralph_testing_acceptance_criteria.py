from __future__ import annotations

from pathlib import Path


def test_ro32_testing_acceptance_standard_lives_outside_trellis() -> None:
    path = Path("docs/standards/CCCC_TESTING_ACCEPTANCE_V1.md")

    text = path.read_text(encoding="utf-8")

    assert path.exists()
    assert ".trellis" in text
    assert "runtime-contract" in text
    assert "P1 or P2" in text
    assert "schema-smoke" in text
    assert "negative `runtime-contract` test" in text
    assert "WorkflowEngine" in text
