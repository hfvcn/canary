"""Integration tests for FL-42: evaluation loop from task completion to candidate generation."""

from __future__ import annotations

import base64
from pathlib import Path

import yaml

from cccc.contracts.v1.agent import ModelCapability, ModelRegistry
from cccc.daemon.ops.model_ops import (
    MODEL_REVIEW_SAMPLE_THRESHOLD,
    create_prompt_candidate,
    parse_optimized_prompt,
    record_model_usage,
    save_model_registry,
    should_trigger_review,
)


MODEL_KEY = "test-model"
AGENT_ID = "test-agent"
OPTIMIZED_PROMPT = "You are an improved agent."
TASK_DURATION_SECONDS = 60


def _write_registry(registry_path: Path, *, best_for: str = "testing") -> None:
    registry = ModelRegistry(
        models={
            MODEL_KEY: ModelCapability(
                runtime="test",
                model_id=MODEL_KEY,
                description="test model",
                best_for=best_for,
                strengths=["testing"],
            ),
        }
    )
    assert save_model_registry(registry, registry_path)


def _encoded_prompt(prompt: str) -> str:
    return base64.b64encode(prompt.encode("utf-8")).decode("ascii")


class TestEvaluationIntegration:
    """Full-chain integration: 3 completions -> auto-trigger -> candidate generation."""

    def test_three_completions_trigger_review(self, tmp_path: Path) -> None:
        """3 task completions should trigger auto model review."""
        registry_path = tmp_path / "registry.yaml"
        _write_registry(registry_path)

        for index in range(MODEL_REVIEW_SAMPLE_THRESHOLD):
            record_model_usage(
                MODEL_KEY,
                registry_path,
                task_id=f"task-{index}",
                duration_seconds=TASK_DURATION_SECONDS,
            )

        assert should_trigger_review(MODEL_KEY, registry_path)

    def test_two_completions_do_not_trigger(self, tmp_path: Path) -> None:
        """2 task completions should NOT trigger review."""
        registry_path = tmp_path / "registry.yaml"
        _write_registry(registry_path, best_for="test")

        for index in range(MODEL_REVIEW_SAMPLE_THRESHOLD - 1):
            record_model_usage(MODEL_KEY, registry_path, task_id=f"task-{index}")

        assert not should_trigger_review(MODEL_KEY, registry_path)

    def test_prompt_candidate_creation_from_optimized_prompt(self, tmp_path: Path) -> None:
        """Foreman reply with OPTIMIZED_PROMPT creates candidate, NOT active agent change."""
        message = (
            f"Good model.\n"
            f"OPTIMIZED_PROMPT:{AGENT_ID}:{_encoded_prompt(OPTIMIZED_PROMPT)}\n"
            f"End."
        )

        result = parse_optimized_prompt(message)

        assert result == (AGENT_ID, OPTIMIZED_PROMPT)

        version = create_prompt_candidate(
            AGENT_ID,
            OPTIMIZED_PROMPT,
            {"avg_duration": TASK_DURATION_SECONDS},
            tmp_path,
        )

        assert version == "v1"

        candidate_file = tmp_path / "agent_versions" / AGENT_ID / "v1.yaml"
        assert candidate_file.exists()
        data = yaml.safe_load(candidate_file.read_text(encoding="utf-8"))
        assert data["status"] == "candidate"
        assert data["tuned_prompt"] == OPTIMIZED_PROMPT

    def test_no_optimized_prompt_no_candidate(self) -> None:
        """Foreman reply without OPTIMIZED_PROMPT marker creates no candidate."""
        message = "Model performs well. No changes suggested."

        assert parse_optimized_prompt(message) is None

    def test_model_ops_exception_does_not_propagate(self, tmp_path: Path) -> None:
        """Errors in evaluation should not block task completion."""
        registry_path = tmp_path / "nonexistent" / "registry.yaml"

        result = record_model_usage("bad-model", registry_path, task_id="t1")

        assert isinstance(result, bool)
