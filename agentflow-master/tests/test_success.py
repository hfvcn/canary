from pathlib import Path

from agentflow.specs import NodeResult, NodeSpec
from agentflow.success import evaluate_success


def test_success_criteria_cover_output_and_files(tmp_path: Path):
    target = tmp_path / "artifact.txt"
    target.write_text("hello success world", encoding="utf-8")
    node = NodeSpec.model_validate(
        {
            "id": "writer",
            "agent": "codex",
            "prompt": "x",
            "success_criteria": [
                {"kind": "output_contains", "value": "success"},
                {"kind": "file_exists", "path": "artifact.txt"},
                {"kind": "file_contains", "path": "artifact.txt", "value": "hello"},
                {"kind": "file_nonempty", "path": "artifact.txt"},
            ],
        }
    )
    result = NodeResult(node_id="writer", output="success")
    passed, messages = evaluate_success(node, result, tmp_path)
    assert passed is True
    assert any("file_exists" in message for message in messages)


def test_success_criteria_handle_non_utf8_artifacts(tmp_path: Path):
    target = tmp_path / "artifact.bin"
    target.write_bytes(b"\xff\xfehello\n")
    node = NodeSpec.model_validate(
        {
            "id": "writer",
            "agent": "codex",
            "prompt": "x",
            "success_criteria": [
                {"kind": "file_contains", "path": "artifact.bin", "value": "hello"},
                {"kind": "file_nonempty", "path": "artifact.bin"},
            ],
        }
    )

    passed, messages = evaluate_success(node, NodeResult(node_id="writer"), tmp_path)

    assert passed is True
    assert "file_contains(artifact.bin, 'hello')=True" in messages
    assert "file_nonempty(artifact.bin)=True" in messages
