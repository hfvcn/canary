from __future__ import annotations

import copy
import logging
from typing import Any

from uvicorn.config import LOGGING_CONFIG

WEB_ACCESS_LOG_FILTER_NAME = "cccc_web_access"
_UI_PREFIX = "/ui"


def _strip_control_chars(value: str) -> str:
    return "".join(ch for ch in value if 32 <= ord(ch) < 127 or ord(ch) >= 160)


def _is_ui_not_modified(path: str, status: Any) -> bool:
    try:
        code = int(status)
    except (TypeError, ValueError):
        return False
    return code == 304 and path.startswith(_UI_PREFIX)


class WebAccessLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        args = getattr(record, "args", ())
        if not isinstance(args, tuple) or len(args) < 5:
            return True
        path = _strip_control_chars(str(args[2] or ""))
        if path != args[2]:
            record.args = args[:2] + (path,) + args[3:]
        return not _is_ui_not_modified(path, args[4])


def build_web_log_config() -> dict[str, Any]:
    config = copy.deepcopy(LOGGING_CONFIG)
    filters = config.setdefault("filters", {})
    filters[WEB_ACCESS_LOG_FILTER_NAME] = {"()": "cccc.ports.web.access_log.WebAccessLogFilter"}
    access_handler = config.get("handlers", {}).get("access")
    if isinstance(access_handler, dict):
        existing = list(access_handler.get("filters") or [])
        if WEB_ACCESS_LOG_FILTER_NAME not in existing:
            access_handler["filters"] = [*existing, WEB_ACCESS_LOG_FILTER_NAME]
    return config
