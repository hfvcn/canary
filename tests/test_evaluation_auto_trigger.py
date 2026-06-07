from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cccc.contracts.v1.agent import ModelCapability, ModelRegistry
from cccc.daemon.foreman.assignment_controller import AssignmentController
from cccc.daemon.ops.agent_ops import save_model_registry
from cccc.daemon.ops.model_ops import record_model_usage


MODEL_KEY = "codex-test-model"
GROUP_ID = "group-test"
TASK_ID = "T1"
AGENT_ID = "worker-1"


class ReviewOwner:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self._group_id = GROUP_ID
        self._send_foreman_message = self._capture_foreman_message
        self.sent_messages: list[tuple[str, str, str]] = []
        self._active_workflows = {
            "wf-1": {
                "tasks": {
                    TASK_ID: {
                        "agent_id": AGENT_ID,
                        "claimed_paths": [],
                    }
                }
            }
        }
        self._task_to_agent = {TASK_ID: AGENT_ID}
        self._task_to_model = {TASK_ID: MODEL_KEY}
        self.foreman = SimpleNamespace(release_completed_task=lambda *_args: None)
        self.reporter = SimpleNamespace(on_task_completed=lambda *_args, **_kwargs: True)

    def _capture_foreman_message(self, group_id: str, actor_id: str, text: str) -> None:
        self.sent_messages.append((group_id, actor_id, text))

    def _post_hoc_plan_digest_check(self, _task_id: str, _workflow_id: str) -> None:
        return None

    def _record_model_usage(
        self,
        model_key: str,
        task_id: str,
        duration_seconds: int,
        changed_files: list[str],
    ) -> None:
        record_model_usage(
            model_key,
            self.project_root / ".cccc" / "models" / "registry.yaml",
            task_id=task_id,
            duration_seconds=duration_seconds,
            files_changed=len(changed_files),
        )

    def _check_batch_completion(self, _workflow_id: str) -> None:
        return None

    def _resuggest_ready_tasks(self, _workflow_id: str) -> None:
        return None

    def _notify_foreman_task_update(self, **_kwargs: object) -> None:
        return None

    def _build_completion_summary(self, **_kwargs: object) -> str:
        return "done"

    def _check_workflow_completion_after_terminal(self, _task_id: str) -> None:
        return None


def _registry_path(project_root: Path) -> Path:
    return project_root / ".cccc" / "models" / "registry.yaml"


def _write_registry(project_root: Path, sample_count: int, tags: list[str] | None = None) -> Path:
    registry_path = _registry_path(project_root)
    registry = ModelRegistry(
        models={
            MODEL_KEY: ModelCapability(
                runtime="codex",
                model_id=MODEL_KEY,
                foreman_sample_count=sample_count,
                tags=list(tags or []),
            )
        }
    )
    assert save_model_registry(registry, registry_path)
    return registry_path


def _complete_task(owner: ReviewOwner) -> bool:
    controller = AssignmentController(owner)
    return controller.on_task_completed_inner(TASK_ID, AGENT_ID, 12, [])


def test_sample_count_at_threshold_triggers_review(tmp_path: Path) -> None:
    _write_registry(tmp_path, sample_count=2)
    owner = ReviewOwner(tmp_path)

    with patch(
        "cccc.daemon.foreman.assignment_completion.request_model_review",
        return_value="sent",
    ) as request_review:
        assert _complete_task(owner) is True

    request_review.assert_called_once()


def test_sample_count_below_threshold_does_not_trigger(tmp_path: Path) -> None:
    _write_registry(tmp_path, sample_count=1)
    owner = ReviewOwner(tmp_path)

    with patch("cccc.daemon.foreman.assignment_completion.request_model_review") as request_review:
        assert _complete_task(owner) is True

    request_review.assert_not_called()


def test_already_reviewed_at_this_threshold_does_not_retrigger(tmp_path: Path) -> None:
    _write_registry(tmp_path, sample_count=2, tags=["reviewed_at_sample:3"])
    owner = ReviewOwner(tmp_path)

    with patch("cccc.daemon.foreman.assignment_completion.request_model_review") as request_review:
        assert _complete_task(owner) is True

    request_review.assert_not_called()


def test_request_model_review_exception_does_not_propagate(
    tmp_path: Path,
    caplog,
) -> None:
    _write_registry(tmp_path, sample_count=2)
    owner = ReviewOwner(tmp_path)

    with caplog.at_level(logging.WARNING, logger="cccc.daemon.foreman.assignment_controller"):
        with patch(
            "cccc.daemon.foreman.assignment_completion.request_model_review",
            side_effect=RuntimeError("foreman unavailable"),
        ):
            assert _complete_task(owner) is True

    assert "Failed to request model review" in caplog.text


def test_review_receives_correct_model_registry_group_and_sender(tmp_path: Path) -> None:
    registry_path = _write_registry(tmp_path, sample_count=2)
    owner = ReviewOwner(tmp_path)

    with patch(
        "cccc.daemon.foreman.assignment_completion.request_model_review",
        return_value="sent",
    ) as request_review:
        assert _complete_task(owner) is True

    request_review.assert_called_once()
    model_key, called_registry_path, group_id, send_message_fn = request_review.call_args.args
    assert model_key == MODEL_KEY
    assert called_registry_path == registry_path
    assert group_id == GROUP_ID
    assert send_message_fn is owner._send_foreman_message
