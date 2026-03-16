"""Canonical IM config normalization helpers.

This module keeps IM config shape consistent across Web/CLI/bridge paths.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Set

from ...util.conv import coerce_bool

SUPPORTED_IM_PLATFORMS: Set[str] = {"telegram", "slack", "discord", "feishu", "dingtalk", "wecom"}
SUPPORTED_FEISHU_MESSAGE_STYLES: Set[str] = {"text", "card"}
_GROUP_LOCAL_ONLY_KEYS: Set[str] = {"enabled"}

_LEGACY_KEYS: Set[str] = {
    "token_env",
    "token",
    "bot_token_env",
    "bot_token",
    "app_token_env",
    "app_token",
    "feishu_domain",
    "feishu_app_id",
    "feishu_app_id_env",
    "feishu_app_secret",
    "feishu_app_secret_env",
    "dingtalk_app_key",
    "dingtalk_app_key_env",
    "dingtalk_app_secret",
    "dingtalk_app_secret_env",
    "dingtalk_robot_code",
    "dingtalk_robot_code_env",
    "wecom_bot_id",
    "wecom_bot_id_env",
    "wecom_secret",
    "wecom_secret_env",
}


def is_env_var_name(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z_][A-Z0-9_]*", (value or "").strip()))


def normalize_feishu_domain(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    v = raw.lower().rstrip("/")
    if v.endswith("/open-apis"):
        v = v[: -len("/open-apis")].rstrip("/")
    if v in ("feishu", "cn", "china", "open.feishu.cn", "https://open.feishu.cn"):
        return "https://open.feishu.cn"
    if v in (
        "lark",
        "global",
        "intl",
        "international",
        "open.larkoffice.com",
        "https://open.larkoffice.com",
        "open.larksuite.com",
        "https://open.larksuite.com",
    ):
        return "https://open.larkoffice.com"
    return "https://open.feishu.cn"


def normalize_feishu_message_style(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in SUPPORTED_FEISHU_MESSAGE_STYLES:
        return raw
    return "text"


def _first_nonempty(raw: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(raw.get(key) or "").strip()
        if value:
            return value
    return ""


def _set_secret_ref(out: Dict[str, Any], *, env_key: str, value_key: str, raw_value: str) -> None:
    value = str(raw_value or "").strip()
    if not value:
        out.pop(env_key, None)
        out.pop(value_key, None)
        return
    if is_env_var_name(value):
        out[env_key] = value
        out.pop(value_key, None)
    else:
        out[value_key] = value
        out.pop(env_key, None)


def canonicalize_im_config(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    platform = str(raw.get("platform") or "").strip().lower()
    if platform not in SUPPORTED_IM_PLATFORMS:
        return {}

    out: Dict[str, Any] = {"platform": platform}
    if "enabled" in raw:
        out["enabled"] = coerce_bool(raw.get("enabled"), default=False)
    files = raw.get("files")
    if isinstance(files, dict):
        out["files"] = dict(files)
    if "skip_pending_on_start" in raw:
        out["skip_pending_on_start"] = coerce_bool(raw.get("skip_pending_on_start"), default=True)

    if platform in {"telegram", "discord", "slack"}:
        bot_ref = _first_nonempty(raw, "bot_token_env", "bot_token", "token_env", "token")
        _set_secret_ref(out, env_key="bot_token_env", value_key="bot_token", raw_value=bot_ref)
        if platform == "slack":
            app_ref = _first_nonempty(raw, "app_token_env", "app_token")
            _set_secret_ref(out, env_key="app_token_env", value_key="app_token", raw_value=app_ref)
    elif platform == "feishu":
        domain = normalize_feishu_domain(str(raw.get("feishu_domain") or ""))
        if domain:
            out["feishu_domain"] = domain
        out["feishu_message_style"] = normalize_feishu_message_style(raw.get("feishu_message_style"))
        _set_secret_ref(
            out,
            env_key="feishu_app_id_env",
            value_key="feishu_app_id",
            raw_value=_first_nonempty(raw, "feishu_app_id_env", "feishu_app_id"),
        )
        _set_secret_ref(
            out,
            env_key="feishu_app_secret_env",
            value_key="feishu_app_secret",
            raw_value=_first_nonempty(raw, "feishu_app_secret_env", "feishu_app_secret"),
        )
        title = str(raw.get("feishu_card_title") or "").strip()
        if title:
            out["feishu_card_title"] = title
        template_id = str(raw.get("feishu_card_template_id") or "").strip()
        if template_id:
            out["feishu_card_template_id"] = template_id
    elif platform == "dingtalk":
        _set_secret_ref(
            out,
            env_key="dingtalk_app_key_env",
            value_key="dingtalk_app_key",
            raw_value=_first_nonempty(raw, "dingtalk_app_key_env", "dingtalk_app_key"),
        )
        _set_secret_ref(
            out,
            env_key="dingtalk_app_secret_env",
            value_key="dingtalk_app_secret",
            raw_value=_first_nonempty(raw, "dingtalk_app_secret_env", "dingtalk_app_secret"),
        )
        _set_secret_ref(
            out,
            env_key="dingtalk_robot_code_env",
            value_key="dingtalk_robot_code",
            raw_value=_first_nonempty(raw, "dingtalk_robot_code_env", "dingtalk_robot_code"),
        )
    elif platform == "wecom":
        _set_secret_ref(
            out,
            env_key="wecom_bot_id_env",
            value_key="wecom_bot_id",
            raw_value=_first_nonempty(raw, "wecom_bot_id_env", "wecom_bot_id"),
        )
        _set_secret_ref(
            out,
            env_key="wecom_secret_env",
            value_key="wecom_secret",
            raw_value=_first_nonempty(raw, "wecom_secret_env", "wecom_secret"),
        )

    # Preserve non-credential extension fields (forward-compatible).
    for key, value in raw.items():
        if key in out:
            continue
        if key in _LEGACY_KEYS:
            continue
        if key in {"platform", "enabled", "files", "skip_pending_on_start", "wecom_agent_id"}:
            continue
        out[key] = value

    return out


def canonicalize_im_defaults(raw: Any) -> Dict[str, Any]:
    out = canonicalize_im_config(raw)
    for key in _GROUP_LOCAL_ONLY_KEYS:
        out.pop(key, None)
    return out


def resolve_im_config(group_raw: Any, global_raw: Any) -> Dict[str, Any]:
    global_cfg = canonicalize_im_defaults(global_raw)
    group_cfg = canonicalize_im_config(group_raw)
    if not global_cfg:
        return group_cfg
    if not group_cfg:
        return global_cfg
    merged = dict(global_cfg)
    for key, value in group_cfg.items():
        if key in _GROUP_LOCAL_ONLY_KEYS:
            continue
        merged[key] = value
    return merged


def get_group_im_enabled(raw: Any) -> Optional[bool]:
    if not isinstance(raw, dict) or "enabled" not in raw:
        return None
    return coerce_bool(raw.get("enabled"), default=False)
