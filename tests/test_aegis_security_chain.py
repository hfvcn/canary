from __future__ import annotations

from cccc.ralph.models import (
    CheckSpec,
    CriticalFlow,
    Plan,
    TaskSpec,
    Verification,
    VerificationCovers,
)
from cccc.ralph.validator import validate

SECURITY_CODE = "E_AEGIS_SECURITY_CHAIN_MISSING"
SSRF_ROUTE_BINDING_CODE = "W_SSRF_ROUTE_BINDING_MISSING"
FTS_CJK_SUBSTRING_CODE = "W_FTS_CJK_SUBSTRING_MISSING"
SILENT_DEGRADATION_CODE = "W_SILENT_DEGRADATION_UNCHECKED"
ENTRYPOINT = "src/auth.py"


def test_feature_with_security_flow_and_empty_checks_reports_error() -> None:
    report = validate(_plan(intent="feature", checks=[]))

    issue = _only_security_error(report)
    assert issue.task_ids == ["T1"]
    assert issue.evidence["intent"] == "feature"
    assert issue.evidence["critical_flows"] == ["ssrf_protection"]
    assert issue.evidence["check_names"] == []


def test_feature_with_security_flow_and_security_checks_passes() -> None:
    report = validate(_plan(intent="feature", checks=[_security_check()]))

    assert SECURITY_CODE not in _error_codes(report)


def test_feature_without_security_flow_passes() -> None:
    report = validate(_plan(intent="feature", flow_id="data_pipeline", checks=[]))

    assert SECURITY_CODE not in _error_codes(report)


def test_fix_with_security_flow_and_empty_checks_passes() -> None:
    report = validate(_plan(intent="fix", checks=[]))

    assert SECURITY_CODE not in _error_codes(report)


def test_ssrf_route_binding_import_only_warns() -> None:
    report = validate(_plan(intent="feature", checks=[_ssrf_import_only_check()]))

    assert SSRF_ROUTE_BINDING_CODE in _warning_codes(report)


def test_ssrf_route_binding_endpoint_check_passes() -> None:
    report = validate(_plan(intent="feature", checks=[_ssrf_endpoint_check()]))

    assert SSRF_ROUTE_BINDING_CODE not in _warning_codes(report)


def test_ssrf_route_binding_no_ssrf_flow_passes() -> None:
    report = validate(
        _plan(intent="feature", flow_id="data_pipeline", checks=[_ssrf_import_only_check()])
    )

    assert SSRF_ROUTE_BINDING_CODE not in _warning_codes(report)


def test_ssrf_route_binding_no_checks_skips() -> None:
    report = validate(_plan(intent="feature", checks=[]))

    assert SSRF_ROUTE_BINDING_CODE not in _warning_codes(report)


def test_fts_cjk_no_substring_warns() -> None:
    report = validate(
        _plan(
            intent="feature",
            flow_id="fts_search",
            flow_description="Full-text search for 中文 and 日本語 queries",
            checks=[_fts_search_check()],
        )
    )

    assert FTS_CJK_SUBSTRING_CODE in _warning_codes(report)


def test_fts_cjk_with_substring_passes() -> None:
    report = validate(
        _plan(
            intent="feature",
            flow_id="fts_search",
            flow_description="Full-text search for 中文 and 日本語 queries",
            checks=[_fts_substring_check()],
        )
    )

    assert FTS_CJK_SUBSTRING_CODE not in _warning_codes(report)


def test_fts_no_cjk_context_passes() -> None:
    report = validate(
        _plan(
            intent="feature",
            flow_id="fts_search",
            flow_description="Full-text search for Latin language queries",
            checks=[_fts_search_check()],
        )
    )

    assert FTS_CJK_SUBSTRING_CODE not in _warning_codes(report)


def test_no_search_flow_passes() -> None:
    report = validate(
        _plan(
            intent="feature",
            flow_id="analytics_pipeline",
            flow_description="Chinese text ingestion pipeline",
            checks=[_fts_search_check()],
        )
    )

    assert FTS_CJK_SUBSTRING_CODE not in _warning_codes(report)


def test_silent_degradation_no_error_check_warns() -> None:
    report = validate(
        _plan(
            intent="feature",
            flow_id="search_query",
            flow_description="Search query execution path",
            checks=[_search_behavior_check()],
        )
    )

    assert SILENT_DEGRADATION_CODE in _warning_codes(report)


def test_silent_degradation_with_error_check_passes() -> None:
    report = validate(
        _plan(
            intent="feature",
            flow_id="search_query",
            flow_description="Search query execution path",
            checks=[_search_error_propagation_check()],
        )
    )

    assert SILENT_DEGRADATION_CODE not in _warning_codes(report)


def test_silent_degradation_no_search_flow_passes() -> None:
    report = validate(
        _plan(
            intent="feature",
            flow_id="analytics_pipeline",
            flow_description="Analytics ingestion pipeline",
            checks=[_search_behavior_check()],
        )
    )

    assert SILENT_DEGRADATION_CODE not in _warning_codes(report)


def _plan(
    *,
    intent: str,
    checks: list[CheckSpec],
    flow_id: str = "ssrf_protection",
    flow_description: str = "",
) -> Plan:
    return Plan(
        tasks=[_task(intent=intent, flow_id=flow_id, checks=checks)],
        critical_flows=[
            CriticalFlow(
                id=flow_id,
                entrypoints=[ENTRYPOINT],
                description=flow_description,
                required_verification_level="unit",
            )
        ],
        semantic_mode="off",
    )


def _task(*, intent: str, flow_id: str, checks: list[CheckSpec]) -> TaskSpec:
    return TaskSpec(
        id="T1",
        title="Implement authentication path",
        claimed_paths=[ENTRYPOINT],
        verification_mode="challenge",
        verification=Verification(
            level="unit",
            checks=checks,
            covers=VerificationCovers(tasks=["T1"], flows=[flow_id]),
        ),
        aegis={"intent": intent},
    )


def _security_check() -> CheckSpec:
    return CheckSpec(
        name="ssrf behavior test",
        command="python -m pytest tests/test_aegis_security_chain.py -q",
    )


def _ssrf_import_only_check() -> CheckSpec:
    return CheckSpec(
        name="ssrf import smoke",
        command="python -m py_compile src/auth.py",
    )


def _ssrf_endpoint_check() -> CheckSpec:
    return CheckSpec(
        name="ssrf endpoint behavior",
        command="python -m pytest tests/test_aegis_security_chain.py -k endpoint -q",
    )


def _fts_search_check() -> CheckSpec:
    return CheckSpec(
        name="fts search behavior",
        command="python -m pytest tests/test_aegis_security_chain.py -k search -q",
    )


def _fts_substring_check() -> CheckSpec:
    return CheckSpec(
        name="fts substring behavior",
        command="python -m pytest tests/test_aegis_security_chain.py -k substring -q",
    )


def _search_behavior_check() -> CheckSpec:
    return CheckSpec(
        name="search behavior",
        command="python -m pytest tests/test_aegis_security_chain.py -k search -q",
    )


def _search_error_propagation_check() -> CheckSpec:
    return CheckSpec(
        name="search error-propagation behavior",
        command="python -m pytest tests/test_aegis_security_chain.py -k error_propagation -q",
    )


def _only_security_error(report):
    matches = [issue for issue in report.errors if issue.code == SECURITY_CODE]
    assert len(matches) == 1
    return matches[0]


def _error_codes(report) -> list[str]:
    return [issue.code for issue in report.errors]


def _warning_codes(report) -> list[str]:
    return [issue.code for issue in report.warnings]
