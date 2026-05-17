"""Tests for AD-1 Aegis discipline schema support."""

from __future__ import annotations

from cccc.contracts.v1.ralph_ipc import TaskRef
from cccc.ralph.models import AegisDiscipline, RepairTrack, RetirementTrack, TaskSpec


def test_aegis_discipline_parses_from_dict():
    aegis = AegisDiscipline.model_validate(
        {
            "intent": "fix",
            "baseline_refs": ["plan.yaml#T1"],
            "compat_boundary": "no compatibility shim",
            "repair_track": {
                "root_cause": "missing schema field",
                "canonical_owner": "src/cccc/ralph/models.py",
                "minimal_change": "add typed field",
                "verification_method": "unit tests",
            },
            "retirement_track": {
                "old_owner": "legacy path",
                "deletion_trigger": "next major",
                "retained": True,
                "retention_reason": "compatibility window",
            },
        }
    )

    assert aegis.intent == "fix"
    assert aegis.baseline_refs == ["plan.yaml#T1"]
    assert aegis.compat_boundary == "no compatibility shim"
    assert isinstance(aegis.repair_track, RepairTrack)
    assert aegis.repair_track.root_cause == "missing schema field"
    assert isinstance(aegis.retirement_track, RetirementTrack)
    assert aegis.retirement_track.retained is True


def test_task_spec_parses_aegis_field():
    task = TaskSpec.model_validate(
        {
            "id": "T1",
            "aegis": {
                "intent": "feature",
                "baseline_refs": ["docs/aegis.md"],
                "compat_boundary": "new schema only",
            },
        }
    )

    assert task.aegis is not None
    assert task.aegis.intent == "feature"
    assert task.aegis.baseline_refs == ["docs/aegis.md"]
    assert task.aegis.compat_boundary == "new schema only"


def test_task_spec_to_task_ref_preserves_aegis_dict():
    task = TaskSpec.model_validate(
        {
            "id": "T1",
            "aegis": {
                "intent": "fix",
                "baseline_refs": ["plan.yaml#T1"],
                "compat_boundary": "no compatibility shim",
                "repair_track": {
                    "root_cause": "missing TaskRef field",
                    "canonical_owner": "src/cccc/contracts/v1/ralph_ipc.py",
                    "minimal_change": "add serialized dict field",
                    "verification_method": "pytest",
                },
            },
        }
    )

    task_ref = task.to_task_ref()

    assert isinstance(task_ref, TaskRef)
    assert task_ref.aegis == {
        "intent": "fix",
        "baseline_refs": ["plan.yaml#T1"],
        "compat_boundary": "no compatibility shim",
        "repair_track": {
            "root_cause": "missing TaskRef field",
            "canonical_owner": "src/cccc/contracts/v1/ralph_ipc.py",
            "minimal_change": "add serialized dict field",
            "verification_method": "pytest",
        },
    }


def test_old_task_spec_without_aegis_still_works():
    task = TaskSpec.model_validate({"id": "T-old"})

    assert task.aegis is None
    assert task.to_task_ref().aegis is None


def test_unknown_fields_in_aegis_discipline_are_ignored():
    aegis = AegisDiscipline.model_validate(
        {
            "intent": "refactor",
            "unknown_top_level": "ignored",
            "repair_track": {
                "root_cause": "known",
                "unknown_repair": "ignored",
            },
            "retirement_track": {
                "old_owner": "legacy",
                "unknown_retirement": "ignored",
            },
        }
    )

    dumped = aegis.model_dump()

    assert "unknown_top_level" not in dumped
    assert "unknown_repair" not in dumped["repair_track"]
    assert "unknown_retirement" not in dumped["retirement_track"]
