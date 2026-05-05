from __future__ import annotations

import json
import re
from urllib.parse import urlencode
from urllib.request import urlopen


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str) -> None:
        self.token = token
        self.chat_id = chat_id

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, text: str, parse_mode: str | None = None) -> None:
        if not self.enabled:
            return
        payload = {"chat_id": self.chat_id, "text": text[:3500]}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        params = urlencode(payload)
        url = f"https://api.telegram.org/bot{self.token}/sendMessage?{params}"
        try:
            urlopen(url, timeout=10).read()
        except Exception:
            if not parse_mode:
                return
            plain_text = re.sub(r"<[^>]+>", "", text)
            params = urlencode({"chat_id": self.chat_id, "text": plain_text[:3500]})
            url = f"https://api.telegram.org/bot{self.token}/sendMessage?{params}"
            try:
                urlopen(url, timeout=10).read()
            except Exception:
                return

    def get_updates(self, offset: int, timeout: int = 1) -> list[dict[str, object]]:
        if not self.enabled:
            return []
        params = urlencode({"offset": offset, "timeout": timeout})
        url = f"https://api.telegram.org/bot{self.token}/getUpdates?{params}"
        try:
            payload = json.loads(urlopen(url, timeout=max(5, timeout + 3)).read().decode("utf-8"))
        except Exception:
            return []
        result = payload.get("result", []) if isinstance(payload, dict) else []
        return result if isinstance(result, list) else []
