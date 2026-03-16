from __future__ import annotations

import secrets
import time
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ..schemas import RouteContext, check_group

DEFAULT_MODEL = "notebooklm:work"
DEFAULT_PROVIDER = "notebooklm"
DEFAULT_LANE = "work"
GROUP_HEADER = "X-CCCC-Group-ID"
SUPPORTED_LANES = {"work", "memory"}
SUPPORTED_ROLES = {"system", "developer", "user", "assistant"}
UNSUPPORTED_ARGUMENTS = ("temperature", "top_p", "max_tokens")


class OpenAIChatContentPart(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str = Field(default="text")
    text: str | None = None


class OpenAIChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(default="user")
    content: str | list[OpenAIChatContentPart]


class OpenAIChatCompletionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(default=DEFAULT_MODEL)
    messages: list[OpenAIChatMessage] = Field(default_factory=list)
    stream: bool = False
    n: int = 1
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None


def _compat_error_type(status_code: int) -> str:
    if status_code == 401:
        return "authentication_error"
    if status_code == 403:
        return "permission_error"
    if status_code == 429:
        return "rate_limit_error"
    if status_code >= 500:
        return "server_error"
    return "invalid_request_error"


def _compat_error_response(
    status_code: int,
    *,
    message: str,
    code: str,
    param: str | None = None,
    error_type: str | None = None,
) -> JSONResponse:
    payload = {
        "error": {
            "message": str(message or "request failed"),
            "type": error_type or _compat_error_type(status_code),
            "param": param,
            "code": str(code or "request_failed"),
        }
    }
    return JSONResponse(status_code=status_code, content=payload)


def _parse_model_name(raw_model: str) -> tuple[str, str]:
    value = str(raw_model or "").strip() or DEFAULT_MODEL
    if ":" in value:
        provider, lane = value.split(":", 1)
    elif "/" in value:
        provider, lane = value.split("/", 1)
    else:
        provider, lane = value, DEFAULT_LANE
    provider_name = str(provider or "").strip() or DEFAULT_PROVIDER
    lane_name = str(lane or "").strip() or DEFAULT_LANE
    if lane_name not in SUPPORTED_LANES:
        raise ValueError(f"unsupported lane: {lane_name}")
    return provider_name, lane_name


def _message_text(content: str | list[OpenAIChatContentPart]) -> str:
    if isinstance(content, str):
        return content.strip()
    parts: list[str] = []
    for index, part in enumerate(content):
        kind = str(part.type or "").strip().lower()
        if kind != "text":
            raise ValueError(f"messages content only supports text parts; messages[].content[{index}] has type={kind or 'unknown'}")
        text = str(part.text or "").strip()
        if text:
            parts.append(text)
    return "\n".join(parts).strip()


def _build_query(messages: list[OpenAIChatMessage]) -> str:
    if not messages:
        raise ValueError("messages must contain at least one item")
    chunks: list[str] = []
    for index, message in enumerate(messages):
        role = str(message.role or "").strip().lower()
        if role not in SUPPORTED_ROLES:
            raise ValueError(f"unsupported role at messages[{index}]: {role or 'unknown'}")
        text = _message_text(message.content)
        if text:
            chunks.append(f"[{role}]\n{text}")
    query = "\n\n".join(chunks).strip()
    if not query:
        raise ValueError("messages must contain at least one non-empty text content item")
    return query


def _validate_request_shape(req: OpenAIChatCompletionsRequest) -> None:
    if req.stream:
        raise ValueError("stream is not supported")
    if int(req.n or 1) != 1:
        raise ValueError("n must equal 1")
    for name in UNSUPPORTED_ARGUMENTS:
        if getattr(req, name) is not None:
            raise ValueError(f"{name} is not supported")


def _daemon_error_status(code: str) -> int:
    mapping = {
        "group_not_found": 404,
        "permission_denied": 403,
        "space_backpressure": 429,
        "space_binding_missing": 404,
        "space_job_invalid": 400,
        "space_provider_disabled": 503,
    }
    return mapping.get(str(code or "").strip(), 502)


def _completion_payload(
    *,
    model: str,
    group_id: str,
    provider: str,
    lane: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    error = result.get("error") if isinstance(result.get("error"), dict) else None
    return {
        "id": f"chatcmpl_{secrets.token_hex(12)}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": str(result.get("answer") or "")},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "cccc": {
            "group_id": group_id,
            "provider": provider,
            "lane": lane,
            "provider_mode": str(result.get("provider_mode") or ""),
            "degraded": bool(result.get("degraded")),
            "references": list(result.get("references") or []),
            "error": error if error else None,
        },
    }


def _group_error_response(exc: HTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    return _compat_error_response(
        int(getattr(exc, "status_code", 403) or 403),
        message=str(detail.get("message") or "group access denied"),
        code=str(detail.get("code") or "permission_denied"),
    )


def _daemon_error_response(error: dict[str, Any]) -> JSONResponse:
    code = str(error.get("code") or "space_query_failed")
    return _compat_error_response(
        _daemon_error_status(code),
        message=str(error.get("message") or "space query failed"),
        code=code,
    )


def create_routers(ctx: RouteContext) -> list[APIRouter]:
    router = APIRouter()

    @router.post("/v1/chat/completions", response_model=None)
    async def openai_chat_completions(
        request: Request,
        req: OpenAIChatCompletionsRequest,
        x_cccc_group_id: str | None = Header(default=None, alias=GROUP_HEADER),
    ) -> Any:
        group_id = str(x_cccc_group_id or "").strip()
        if not group_id:
            return _compat_error_response(400, message=f"missing {GROUP_HEADER} header", code="missing_group_id", param=GROUP_HEADER)
        try:
            check_group(request, group_id)
            _validate_request_shape(req)
            provider, lane = _parse_model_name(req.model)
            query_text = _build_query(req.messages)
            daemon_resp = await ctx.daemon(
                {
                    "op": "group_space_query",
                    "args": {
                        "group_id": group_id,
                        "provider": provider,
                        "lane": lane,
                        "query": query_text,
                        "options": {},
                    },
                }
            )
        except HTTPException as exc:
            return _group_error_response(exc)
        except ValueError as exc:
            return _compat_error_response(400, message=str(exc), code="invalid_request")

        if not bool(daemon_resp.get("ok")):
            error = daemon_resp.get("error") if isinstance(daemon_resp.get("error"), dict) else {}
            return _daemon_error_response(error)

        result = daemon_resp.get("result") if isinstance(daemon_resp.get("result"), dict) else {}
        error = result.get("error") if isinstance(result.get("error"), dict) else {}
        if error and not str(result.get("answer") or "").strip():
            return _daemon_error_response(error)
        return _completion_payload(model=str(req.model or DEFAULT_MODEL), group_id=group_id, provider=provider, lane=lane, result=result)

    return [router]
