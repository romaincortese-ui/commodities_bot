from __future__ import annotations

from urllib.parse import urlencode
from urllib.request import urlopen


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str) -> None:
        self.token = token
        self.chat_id = chat_id

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, text: str) -> None:
        if not self.enabled:
            return
        params = urlencode({"chat_id": self.chat_id, "text": text[:3500]})
        url = f"https://api.telegram.org/bot{self.token}/sendMessage?{params}"
        try:
            urlopen(url, timeout=10).read()
        except Exception:
            return
