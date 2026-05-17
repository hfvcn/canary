"""Tests for Ralph guide generation."""

from __future__ import annotations

from pathlib import Path

from cccc.ralph.guide_generator import (
    generate_guide,
    update_guide,
    _parse_sections,
    _affected_sections,
    _section_matches,
)


def test_generate_guide_contains_plan_fields() -> None:
    output = generate_guide()

    assert "batch_e2e_command" in output
    assert "provides" in output
    assert "ModuleSpec" in output


def test_generate_guide_contains_validation_codes() -> None:
    output = generate_guide()

    assert "W_VERIFICATION_SHAPE_UNKNOWN" in output
    assert "E_CYCLE_DETECTED" in output


def test_generate_guide_cli_subcommands() -> None:
    output = generate_guide()

    assert "validate" in output
    assert "suggest" in output
    assert "guide" in output


def test_parse_sections_splits_by_h2() -> None:
    text = "# Title\npreamble\n\n## Section A\nbody a\n\n## Section B\nbody b\n"
    sections = _parse_sections(text)
    assert len(sections) == 3
    assert sections[0][0] == ""
    assert sections[1][0] == "Section A"
    assert sections[2][0] == "Section B"
    assert "body a" in sections[1][1]
    assert "body b" in sections[2][1]


def test_section_matches_substring() -> None:
    assert _section_matches("Plan Schema Fields", "Plan Schema Fields")
    assert _section_matches("CLI Commands and Flags", "CLI Commands")
    assert _section_matches("Validation Rules Reference", "Validation Rules")
    assert not _section_matches("Stall Detection", "CLI Commands")


def test_affected_sections_maps_files() -> None:
    files = ["src/cccc/ralph/models.py", "src/cccc/daemon/foreman/ralph_service.py"]
    affected = _affected_sections(files)
    assert "Plan Schema Fields" in affected
    assert "Verification Modes" in affected


def test_update_guide_preserves_behavioral_sections(tmp_path: Path, monkeypatch) -> None:
    guide = tmp_path / "guide.md"
    guide.write_text(
        "# Guide\n\n"
        "## CLI Commands Reference\nauto content\n\n"
        "## Verification Modes\nmanual behavioral docs\n\n"
        "## Plan Schema Fields\nauto schema\n",
        encoding="utf-8",
    )
    from cccc.ralph import guide_generator
    monkeypatch.setattr(
        guide_generator, "_git_changed_files",
        lambda since, path: ["src/cccc/daemon/foreman/ralph_service.py"],
    )
    content, warnings = update_guide(guide)
    assert "manual behavioral docs" in content
    assert any("Verification Modes" in w for w in warnings)


def test_update_guide_regenerates_auto_sections(tmp_path: Path, monkeypatch) -> None:
    guide = tmp_path / "guide.md"
    guide.write_text(
        "# Guide\n\n"
        "## Plan Schema Fields\nold stale content\n\n"
        "## Other Section\npreserved\n",
        encoding="utf-8",
    )
    from cccc.ralph import guide_generator
    monkeypatch.setattr(
        guide_generator, "_git_changed_files",
        lambda since, path: ["src/cccc/ralph/models.py"],
    )
    content, _ = update_guide(guide)
    assert "batch_e2e_command" in content
    assert "old stale content" not in content
    assert "preserved" in content
