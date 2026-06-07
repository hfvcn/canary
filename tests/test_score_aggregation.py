from __future__ import annotations

from pathlib import Path

from cccc.contracts.v1.agent import ModelCapability, ModelRegistry
from cccc.contracts.v1.agent_lease import AgentLease
from cccc.daemon.ops.agent_ops import load_model_registry, save_model_registry
from cccc.daemon.ops.model_ops import aggregate_model_scores
from cccc.daemon.ops.trace_bridge import TraceBridge


MODEL_A = "codex-model-a"
MODEL_B = "claude-model-b"
UNKNOWN_MODEL = "gemini-unknown"
FIXED_NOW = "2026-05-31T00:00:00Z"
FIRST_ATTEMPT = 1
SECOND_ATTEMPT = 2
THIRD_ATTEMPT = 3
MODEL_A_TRACE_COUNT = 2
SINGLE_TRACE_COUNT = 1
MANUAL_RATING = 4.5
MODEL_KEY_SPLIT_LIMIT = 1


def _registry_path(tmp_path: Path) -> Path:
    return tmp_path / ".cccc" / "models" / "registry.yaml"


def _performance_dir(tmp_path: Path) -> Path:
    return tmp_path / ".cccc" / "performance"


def _model(runtime: str, model_id: str, **overrides: object) -> ModelCapability:
    data = {"runtime": runtime, "model_id": model_id}
    data.update(overrides)
    return ModelCapability(**data)


def _write_registry(tmp_path: Path, models: dict[str, ModelCapability]) -> Path:
    registry_path = _registry_path(tmp_path)
    assert save_model_registry(ModelRegistry(models=models), registry_path)
    return registry_path


def _make_lease(model_key: str) -> AgentLease:
    return AgentLease(
        lease_id=f"lease-{model_key}",
        agent_id=f"agent-{model_key}",
        actor_id=f"actor-{model_key}",
        model_runtime=model_key.split("-", maxsplit=MODEL_KEY_SPLIT_LIMIT)[0],
        model_id=model_key,
        model_key=model_key,
        is_new_actor=False,
        assignment_reason="selected for aggregation test",
    )


def _record_attempt(bridge: TraceBridge, model_key: str, index: int) -> None:
    bridge.record_attempt(
        _make_lease(model_key),
        task_id=f"task-{index}",
        run_id=f"run-{index}",
        workflow_id=f"workflow-{index}",
        attempt_id=f"attempt-{index}",
        trace_path=f"traces/run-{index}.jsonl",
    )


def test_empty_traces_return_empty_dict(tmp_path: Path) -> None:
    registry_path = _write_registry(tmp_path, {MODEL_A: _model("codex", MODEL_A)})

    assert aggregate_model_scores(registry_path, _performance_dir(tmp_path)) == {}


def test_multiple_traces_aggregate_correctly_per_model(
    tmp_path: Path,
    monkeypatch,
) -> None:
    registry_path = _write_registry(
        tmp_path,
        {
            MODEL_A: _model("codex", MODEL_A),
            MODEL_B: _model("claude", MODEL_B),
        },
    )
    bridge = TraceBridge(_performance_dir(tmp_path))
    _record_attempt(bridge, MODEL_A, FIRST_ATTEMPT)
    _record_attempt(bridge, MODEL_A, SECOND_ATTEMPT)
    _record_attempt(bridge, MODEL_B, THIRD_ATTEMPT)
    monkeypatch.setattr("cccc.util.time.utc_now_iso", lambda: FIXED_NOW)

    assert aggregate_model_scores(registry_path, _performance_dir(tmp_path)) == {
        MODEL_A: {"sample_count": MODEL_A_TRACE_COUNT, "last_updated": FIXED_NOW},
        MODEL_B: {"sample_count": SINGLE_TRACE_COUNT, "last_updated": FIXED_NOW},
    }


def test_registry_sample_count_and_last_rated_at_updated(
    tmp_path: Path,
    monkeypatch,
) -> None:
    registry_path = _write_registry(tmp_path, {MODEL_A: _model("codex", MODEL_A)})
    bridge = TraceBridge(_performance_dir(tmp_path))
    _record_attempt(bridge, MODEL_A, FIRST_ATTEMPT)
    _record_attempt(bridge, MODEL_A, SECOND_ATTEMPT)
    monkeypatch.setattr("cccc.util.time.utc_now_iso", lambda: FIXED_NOW)

    aggregate_model_scores(registry_path, _performance_dir(tmp_path))

    model = load_model_registry(registry_path).get_model(MODEL_A)
    assert model is not None
    assert model.foreman_sample_count == MODEL_A_TRACE_COUNT
    assert model.last_rated_at == FIXED_NOW


def test_manually_set_foreman_rating_not_overwritten(
    tmp_path: Path,
    monkeypatch,
) -> None:
    registry_path = _write_registry(
        tmp_path,
        {MODEL_A: _model("codex", MODEL_A, foreman_rating=MANUAL_RATING)},
    )
    _record_attempt(TraceBridge(_performance_dir(tmp_path)), MODEL_A, FIRST_ATTEMPT)
    monkeypatch.setattr("cccc.util.time.utc_now_iso", lambda: FIXED_NOW)

    aggregate_model_scores(registry_path, _performance_dir(tmp_path))

    model = load_model_registry(registry_path).get_model(MODEL_A)
    assert model is not None
    assert model.foreman_rating == MANUAL_RATING
    assert model.foreman_sample_count == SINGLE_TRACE_COUNT


def test_unknown_model_key_in_traces_is_skipped(tmp_path: Path) -> None:
    registry_path = _write_registry(tmp_path, {MODEL_A: _model("codex", MODEL_A)})
    _record_attempt(TraceBridge(_performance_dir(tmp_path)), UNKNOWN_MODEL, FIRST_ATTEMPT)

    assert aggregate_model_scores(registry_path, _performance_dir(tmp_path)) == {}


def test_empty_registry_returns_empty_dict(tmp_path: Path) -> None:
    registry_path = _write_registry(tmp_path, {})
    _record_attempt(TraceBridge(_performance_dir(tmp_path)), MODEL_A, FIRST_ATTEMPT)

    assert aggregate_model_scores(registry_path, _performance_dir(tmp_path)) == {}
