from __future__ import annotations

from cccc.daemon.foreman.prompt_builder import build_task_prompt
from cccc.ralph.models import Plan


CLAIMED_PATHS = [
    "src/cccc/daemon/foreman/prompt_builder.py",
    "tests/ralph/test_m3_worker_narrowing.py",
]


def _full_module() -> dict:
    return {
        "id": "module-api",
        "description": "Expose the API contract",
        "input_spec": {"request": {"type": "object"}},
        "output_spec": {"response": {"type": "object"}},
        "purpose": "Publish the canonical module interface",
        "interface": {
            "provides": [{"name": "response", "value": {"type": "object"}}],
            "consumes": [{"name": "request", "value": {"type": "object"}}],
        },
        "mock_inputs": [{"name": "request", "value": {"user_id": "u-1"}}],
        "expected_outputs": [{"name": "response", "value": {"status": "ok"}}],
        "black_box_tests": [{"command": "python -c \"print('ok')\"", "selector": "stdout"}],
        "integration_contract": {
            "upstream": ["module-auth"],
            "downstream": ["module-ui"],
        },
        "completion_evidence": {"required": ["module_io_passed"]},
        "internal_depends_on": ["module-auth"],
    }


def _legacy_module() -> dict:
    return {
        "id": "module-legacy",
        "description": "Legacy-only contract source",
        "input_spec": {"request": {"type": "object"}},
        "output_spec": {"response": {"type": "object"}},
        "black_box_tests": [{"command": "python -c \"print('legacy')\""}],
    }


def _task_ref(*, modules: list[dict] | None) -> object:
    task_payload = {
        "id": "T4",
        "title": "Narrow worker input",
        "type": "backend",
        "goal_behavior": "Render a narrowed module contract for workers",
        "acceptance_criteria": "Workers receive only the module contract they must satisfy",
        "claimed_paths": CLAIMED_PATHS,
        "verification": {
            "level": "unit",
            "command": "python -m pytest tests/ralph/test_m3_worker_narrowing.py -v",
        },
    }
    if modules is not None:
        task_payload["modules"] = modules
    plan = Plan.model_validate({"tasks": [task_payload]})
    return plan.tasks[0].to_task_ref()


def test_build_task_prompt_renders_module_narrowed_input_contract() -> None:
    prompt = build_task_prompt(_task_ref(modules=[_full_module()]))

    assert "模块收窄输入 / Module Narrowed Input:" in prompt
    assert "模块目标:" in prompt
    assert "接口:" in prompt
    assert "provides:" in prompt
    assert "consumes:" in prompt
    assert "模拟输入:" in prompt
    assert "允许修改路径:" in prompt
    assert "禁止修改路径:" in prompt
    assert "失败上报格式:" in prompt
    assert ", ".join(CLAIMED_PATHS) in prompt
    assert "Do not modify files outside claimed_paths." in prompt
    assert "[module-api] Expose the API contract" in prompt
    assert "Publish the canonical module interface" in prompt
    assert "status: blocked" in prompt
    # Blind verification (蓝图 1.3/3.2/4.3 + 既有 mock_tests 不变量): the worker must
    # NOT see the oracle (expected_outputs values) or the acceptance/verify command.
    assert "预期输出:" not in prompt
    assert "验收命令:" not in prompt
    assert "status: ok" not in prompt  # expected_output value must not leak
    assert "python -c \"print('ok')\"" not in prompt  # black_box acceptance command must not leak


def test_build_task_prompt_normalizes_legacy_module_contracts() -> None:
    prompt = build_task_prompt(_task_ref(modules=[_legacy_module()]))

    assert "模块收窄输入 / Module Narrowed Input:" in prompt
    assert "provides: [{'name': 'response', 'value': {'type': 'object'}}]" in prompt
    assert "consumes: [{'name': 'request', 'value': {'type': 'object'}}]" in prompt
    # acceptance command (black_box_tests) must not leak to the worker
    assert "python -c \"print('legacy')\"" not in prompt


def test_build_task_prompt_omits_narrowed_input_without_modules() -> None:
    prompt = build_task_prompt(_task_ref(modules=None))

    assert "模块收窄输入 / Module Narrowed Input:" not in prompt
    assert "模块目标:" not in prompt
    assert "Scope (claimed files): src/cccc/daemon/foreman/prompt_builder.py, tests/ralph/test_m3_worker_narrowing.py" in prompt
