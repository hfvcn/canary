"""LLM-backed behavioral security check generation for Ralph plans."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from .models import CriticalFlow, Plan
from .plan_io import load_plan
from .security_recipes import SECURITY_RECIPES

log = logging.getLogger(__name__)

DEFAULT_LLM_PROVIDER = "gemini"
MIN_LLM_SECURITY_CHECKS = 3
LLM_SOURCE = "llm"
LLM_OPERATION = "security check generation"
SECURITY_FLOW_KEYWORDS = (
    "auth",
    "token",
    "ssrf",
    "sql",
    "injection",
    "xss",
    "toctou",
    "race",
)
RECIPE_HINT_KEYS = (
    "keywords",
    "coverage_terms",
    "hostname_encoding_matrix",
    "timing_safe_compare_patterns",
    "temporal_pattern",
    "toctou_test_templates",
    "two_phase_test_template",
)
FLOW_TEXT_FIELDS = ("id", "description", "surface_type", "temporal_pattern")


def generate_llm_security_checks(
    plan_path: str,
    *,
    provider: str = DEFAULT_LLM_PROVIDER,
) -> list[dict[str, object]]:
    """Generate behavioral security checks with RalphAgent Gemini JSON retry."""
    try:
        resolved_provider = _resolve_provider(provider)
        plan = load_plan(Path(plan_path))
        flows = _security_flows(plan)
        if not flows:
            return []
        prompt = _build_llm_prompt(flows)
        agent = _build_agent(resolved_provider)
        return agent._run_gemini_json_retry(
            prompt,
            parser=_parse_llm_checks,
            operation=LLM_OPERATION,
        )
    except Exception as exc:
        log.warning("LLM security check generation skipped: %s", _skip_reason(exc))
        return []


def _resolve_provider(provider: str) -> str:
    normalized = str(provider or "").strip().casefold()
    if normalized not in {"gemini", "gemini-cli"}:
        raise RuntimeError(f"unsupported provider: {provider}")
    from .agent import GEMINI_PROVIDER

    return GEMINI_PROVIDER


def _build_agent(provider: str):
    from .agent import AgentConfig, RalphAgent

    return RalphAgent(config=AgentConfig(provider=provider, warmup_enabled=False))


def _security_flows(plan: Plan) -> list[CriticalFlow]:
    return [flow for flow in plan.critical_flows if _is_security_flow(flow)]


def _is_security_flow(flow: CriticalFlow) -> bool:
    text = _normalized_flow_text(flow)
    return any(_contains_keyword(text, keyword) for keyword in SECURITY_FLOW_KEYWORDS)


def _build_llm_prompt(flows: list[CriticalFlow]) -> str:
    context = json.dumps(
        {
            "critical_flows": [_flow_prompt_context(flow) for flow in flows],
            "response_schema": [
                {
                    "name": "descriptive behavioral security check name",
                    "command": "concrete shell command that exercises the security behavior",
                }
            ],
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    return (
        "Generate behavioral security checks for the following Ralph critical flows.\n"
        "Return only JSON matching response_schema. No prose.\n"
        f"Return a JSON array with at least {MIN_LLM_SECURITY_CHECKS} items.\n"
        "Each item must contain non-empty name and command fields.\n"
        "Commands must be concrete shell commands that validate observable security behavior.\n"
        "Prefer focused pytest commands or narrow project CLI commands, not placeholders.\n"
        "Use the flow details and security_recipe_hints to cover the highest-risk abuse cases.\n\n"
        f"{context}"
    )


def _flow_prompt_context(flow: CriticalFlow) -> dict[str, object]:
    return {
        "id": flow.id,
        "description": flow.description,
        "surface_type": getattr(flow, "surface_type", "") or "",
        "entrypoints": list(flow.entrypoints),
        "security_recipe_hints": _relevant_recipe_hints(flow),
    }


def _relevant_recipe_hints(flow: CriticalFlow) -> list[dict[str, object]]:
    return [
        _recipe_hint(recipe_name, recipe)
        for recipe_name, recipe in SECURITY_RECIPES.items()
        if _recipe_applies(flow, recipe_name, recipe)
    ]


def _recipe_applies(
    flow: CriticalFlow,
    recipe_name: str,
    recipe: dict[str, Any],
) -> bool:
    surface_type = str(getattr(flow, "surface_type", "") or "")
    temporal_pattern = str(getattr(flow, "temporal_pattern", "") or "")
    if surface_type == recipe_name:
        return True
    if recipe_name == "temporal:store_then_use" and temporal_pattern == "store_then_use":
        return True
    flow_text = _normalized_flow_text(flow)
    return any(_contains_keyword(flow_text, keyword) for keyword in _recipe_keywords(recipe))


def _recipe_hint(recipe_name: str, recipe: dict[str, Any]) -> dict[str, object]:
    hint: dict[str, object] = {"recipe": recipe_name}
    for key in RECIPE_HINT_KEYS:
        if key in recipe:
            hint[key] = recipe[key]
    return hint


def _recipe_keywords(recipe: dict[str, Any]) -> tuple[str, ...]:
    keywords = recipe.get("keywords")
    if isinstance(keywords, (list, tuple)):
        return tuple(str(keyword) for keyword in keywords)
    if keywords:
        return (str(keywords),)
    return ()


def _parse_llm_checks(stdout: str) -> list[dict[str, object]]:
    payload = _parse_llm_payload(stdout)
    if not isinstance(payload, list):
        raise _gemini_error("Gemini response JSON must be a list")
    checks = [_coerce_llm_check(item) for item in payload]
    if len(checks) < MIN_LLM_SECURITY_CHECKS:
        raise _gemini_error(
            f"Gemini response returned fewer than {MIN_LLM_SECURITY_CHECKS} security checks"
        )
    return checks


def _parse_llm_payload(stdout: str) -> Any:
    from .agent import _extract_gemini_response, _strip_json_fence

    response_text = _extract_gemini_response(stdout)
    try:
        return json.loads(_strip_json_fence(response_text))
    except json.JSONDecodeError as exc:
        raise _gemini_error("Gemini response was not valid JSON") from exc


def _coerce_llm_check(item: object) -> dict[str, object]:
    if not isinstance(item, dict):
        raise _gemini_error("Gemini security check must be an object")
    name = str(item.get("name", "")).strip()
    command = str(item.get("command", "")).strip()
    if not name or not command:
        raise _gemini_error("Gemini security check had invalid name or command")
    return {
        "name": name,
        "command": command,
        "auto_generated": True,
        "source": LLM_SOURCE,
    }


def _gemini_error(message: str) -> Exception:
    from .agent import GeminiResponseError

    return GeminiResponseError(message)


def _normalized_flow_text(flow: CriticalFlow) -> str:
    parts = [str(getattr(flow, field, "") or "") for field in FLOW_TEXT_FIELDS]
    return _normalize_text(" ".join(parts))


def _normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _contains_keyword(text: str, keyword: str) -> bool:
    pattern = rf"(?<![a-z0-9]){re.escape(_normalize_text(keyword))}(?![a-z0-9])"
    return re.search(pattern, text) is not None


def _skip_reason(exc: Exception) -> str:
    message = str(exc).strip()
    return message or exc.__class__.__name__
