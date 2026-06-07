from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional


class FeishuAdapterWrapper:
    """Wrapper to make FeishuAdapter compatible with FeishuSender protocol."""

    def __init__(
        self,
        adapter: Any,
        *,
        log_fn: Optional[Callable[[str], None]] = None,
    ):
        self._adapter = adapter
        self._log = log_fn or (lambda msg: None)

    def send_card(self, chat_id: str, card: Dict[str, Any]) -> bool:
        """Send a card message via Feishu adapter."""
        if not self._adapter:
            self._log("[feishu] No adapter configured")
            return False

        try:
            if hasattr(self._adapter, "send_card"):
                return self._adapter.send_card(chat_id, card)

            card_json = json.dumps(card, ensure_ascii=False)
            if hasattr(self._adapter, "_api"):
                body = {
                    "receive_id": chat_id,
                    "msg_type": "interactive",
                    "content": card_json,
                }
                resp = self._adapter._api(
                    "POST",
                    "/im/v1/messages?receive_id_type=chat_id",
                    body,
                )
                return resp.get("code") == 0

            return False
        except Exception as exc:
            self._log(f"[feishu] Send card error: {exc}")
            return False
