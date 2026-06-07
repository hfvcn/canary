import json

from cccc.agentflow.af_patches import (
    CCCC_AGENT_KIND,
    CCCC_TARGET_KIND,
    CCCCActorTarget,
    CCCCTraceParser,
    register_cccc_extensions,
)


TRACE_DATA = {"node_id": "T18", "status": "ok"}
TRACE_TYPE = "cccc.trace"


class _Registry:
    def __init__(self) -> None:
        self.calls = []

    def register(self, target_kind: str, extensions: dict) -> None:
        self.calls.append((target_kind, extensions))


def _valid_trace() -> dict:
    return {"type": TRACE_TYPE, "data": TRACE_DATA}


def test_cccc_agent_kind_constant() -> None:
    assert CCCC_AGENT_KIND == "cccc"


def test_cccc_actor_target_default_kind() -> None:
    target = CCCCActorTarget()

    assert target.kind == "cccc_actor"


def test_trace_parser_parse_line_with_valid_json_trace() -> None:
    trace = _valid_trace()
    parsed = CCCCTraceParser().parse_line(json.dumps(trace))

    assert parsed == trace


def test_trace_parser_parse_line_with_invalid_json_returns_none() -> None:
    parsed = CCCCTraceParser().parse_line("{invalid-json")

    assert parsed is None


def test_trace_parser_parse_line_with_non_trace_json_returns_none() -> None:
    parsed = CCCCTraceParser().parse_line(json.dumps({"data": TRACE_DATA}))

    assert parsed is None


def test_trace_parser_parse_lines_filters_correctly() -> None:
    first_trace = _valid_trace()
    second_trace = {"type": "cccc.done", "data": {"node_id": "T19"}}
    lines = [
        json.dumps(first_trace),
        "not json",
        json.dumps({"data": TRACE_DATA}),
        "",
        json.dumps(second_trace),
    ]

    assert CCCCTraceParser().parse_lines(lines) == [first_trace, second_trace]


def test_register_cccc_extensions_returns_expected_dict() -> None:
    extensions = register_cccc_extensions()

    assert extensions == {
        "agent_kind": CCCC_AGENT_KIND,
        "target_kind": CCCC_TARGET_KIND,
        "trace_parser": CCCCTraceParser,
    }


def test_register_cccc_extensions_calls_registry_register_if_provided() -> None:
    registry = _Registry()
    extensions = register_cccc_extensions(registry)

    assert registry.calls == [(CCCC_TARGET_KIND, extensions)]


def test_import_path_works() -> None:
    from cccc.agentflow.af_patches import CCCCTraceParser as ImportedTraceParser

    assert ImportedTraceParser is CCCCTraceParser
