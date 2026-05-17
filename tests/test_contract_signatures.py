"""Contract signature declaration and advisory validation tests."""

from __future__ import annotations

import logging

from cccc.contracts.v1.ralph_ipc import TaskRef
from cccc.daemon.foreman.contract_signature_advisory import (
    SignatureAdvisoryContext,
    warn_on_contract_signature_source_mismatches,
)
from cccc.ralph.models import Plan
from cccc.ralph.validator import validate, validate_with_project


SIGNATURE_WARNING = "W_CONTRACT_SIGNATURE_MISMATCH"
CONTRACT_NAME = "user_api"
SIGNATURES = {"fetch_user": "(user_id: str) -> dict"}


def _validate_signature_plan(
    *,
    provider_signatures: dict[str, str] | None,
    consumer_signatures: dict[str, str] | None,
):
    provider_contract = {"name": CONTRACT_NAME, "kind": "artifact"}
    consumer_contract = {"name": CONTRACT_NAME, "kind": "artifact", "from": "T1"}
    if provider_signatures is not None:
        provider_contract["signatures"] = provider_signatures
    if consumer_signatures is not None:
        consumer_contract["signatures"] = consumer_signatures

    plan = Plan.model_validate({
        "tasks": [
            {
                "id": "T1",
                "claimed_paths": ["src/provider.py"],
                "provides": [provider_contract],
                "verification": {"level": "unit", "command": "true"},
            },
            {
                "id": "T2",
                "claimed_paths": ["src/consumer.py"],
                "depends_on": ["T1"],
                "consumes": [consumer_contract],
                "verification": {
                    "level": "integration",
                    "command": "python -m pytest src/provider.py tests/consumer_test.py",
                    "covers": {"tasks": ["T1", "T2"]},
                },
            },
        ]
    })
    return validate(plan)


def _warning_codes(report) -> list[str]:
    return [warning.code for warning in report.warnings]


def _validate_provider_source_plan(
    tmp_path,
    *,
    provider_signatures: dict[str, str] | None,
    provider_source: str,
):
    provider_path = tmp_path / "src" / "provider.py"
    consumer_path = tmp_path / "src" / "consumer.py"
    provider_path.parent.mkdir()
    provider_path.write_text(provider_source, encoding="utf-8")
    consumer_path.write_text("from src.provider import fetch_user\n", encoding="utf-8")
    provider_contract = {"name": CONTRACT_NAME, "kind": "artifact"}
    if provider_signatures is not None:
        provider_contract["signatures"] = provider_signatures
    plan = Plan.model_validate({
        "tasks": [
            {
                "id": "T1",
                "claimed_paths": ["src/provider.py"],
                "provides": [provider_contract],
                "verification": {"level": "unit", "command": "python -m py_compile src/provider.py"},
            },
            {
                "id": "T2",
                "claimed_paths": ["src/consumer.py"],
                "depends_on": ["T1"],
                "consumes": [{"name": CONTRACT_NAME, "kind": "artifact", "from": "T1"}],
                "verification": {
                    "level": "integration",
                    "command": "python -m py_compile src/provider.py src/consumer.py",
                    "covers": {"tasks": ["T1", "T2"]},
                },
            },
        ]
    })
    return validate_with_project(plan, project_root=tmp_path)


def test_consumer_signatures_provider_missing_warns():
    report = _validate_signature_plan(
        provider_signatures=None,
        consumer_signatures=SIGNATURES,
    )

    assert report.valid is True
    assert SIGNATURE_WARNING in _warning_codes(report)


def test_matching_provider_and_consumer_signatures_pass():
    report = _validate_signature_plan(
        provider_signatures=SIGNATURES,
        consumer_signatures=SIGNATURES,
    )

    assert report.valid is True
    assert SIGNATURE_WARNING not in _warning_codes(report)


def test_no_signatures_anywhere_skips_signature_check():
    report = _validate_signature_plan(
        provider_signatures=None,
        consumer_signatures=None,
    )

    assert report.valid is True
    assert SIGNATURE_WARNING not in _warning_codes(report)


def test_provider_source_signature_mismatch_warns(tmp_path):
    report = _validate_provider_source_plan(
        tmp_path,
        provider_signatures=SIGNATURES,
        provider_source="def fetch_user(user_id: int) -> dict:\n    return {}\n",
    )

    assert report.valid is True
    assert SIGNATURE_WARNING in _warning_codes(report)


def test_matching_provider_source_signature_passes(tmp_path):
    report = _validate_provider_source_plan(
        tmp_path,
        provider_signatures=SIGNATURES,
        provider_source="def fetch_user(user_id: str) -> dict:\n    return {}\n",
    )

    assert report.valid is True
    assert SIGNATURE_WARNING not in _warning_codes(report)


def test_no_provider_signatures_skips_source_signature_check(tmp_path):
    report = _validate_provider_source_plan(
        tmp_path,
        provider_signatures=None,
        provider_source="def fetch_user(user_id: int) -> dict:\n    return {}\n",
    )

    assert report.valid is True
    assert SIGNATURE_WARNING not in _warning_codes(report)


def test_dispatch_advisory_logs_source_signature_mismatch(tmp_path, caplog):
    provider_path = tmp_path / "src" / "provider.py"
    provider_path.parent.mkdir()
    provider_path.write_text("def fetch_user(user_id: int) -> dict:\n    return {}\n", encoding="utf-8")
    provider = TaskRef(
        id="T1",
        claimed_paths=["src/provider.py"],
        provides=[{"name": CONTRACT_NAME, "kind": "artifact"}],
    )
    consumer = TaskRef(
        id="T2",
        consumes=[{"name": CONTRACT_NAME, "from": "T1", "signatures": SIGNATURES}],
    )

    with caplog.at_level(logging.WARNING):
        warn_on_contract_signature_source_mismatches(
            SignatureAdvisoryContext(tmp_path, [provider, consumer], [consumer])
        )

    assert "source signature mismatch" in caplog.text
    assert "fetch_user" in caplog.text
