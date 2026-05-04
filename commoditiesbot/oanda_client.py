from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from commoditiesbot.config import CommodityConfig
from commoditiesbot.models import Candle


class OandaClient:
    def __init__(self, config: CommodityConfig) -> None:
        self.config = config

    def _request(self, method: str, path: str, payload: dict[str, object] | None = None) -> dict[str, object]:
        if not self.config.has_oanda_credentials:
            raise RuntimeError("OANDA credentials are not configured")
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            self.config.oanda_base_url + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.config.oanda_api_token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError) as exc:
            raise RuntimeError(f"OANDA request failed: {exc}") from exc

    def tradeable_instruments(self) -> list[str]:
        payload = self._request("GET", f"/v3/accounts/{self.config.oanda_account_id}/instruments")
        instruments = payload.get("instruments", [])
        if not isinstance(instruments, list):
            return []
        return [str(item.get("name")) for item in instruments if isinstance(item, dict) and item.get("name")]

    def candles(self, instrument: str, count: int = 120, granularity: str = "D") -> list[Candle]:
        params = urlencode({"count": count, "granularity": granularity, "price": "M"})
        payload = self._request("GET", f"/v3/instruments/{instrument}/candles?{params}")
        rows = payload.get("candles", [])
        candles: list[Candle] = []
        if not isinstance(rows, list):
            return candles
        for row in rows:
            if not isinstance(row, dict) or not row.get("complete", True):
                continue
            mid = row.get("mid")
            if not isinstance(mid, dict):
                continue
            try:
                candles.append(
                    Candle(
                        time=datetime.fromisoformat(str(row["time"]).replace("Z", "+00:00")),
                        open=float(mid["o"]),
                        high=float(mid["h"]),
                        low=float(mid["l"]),
                        close=float(mid["c"]),
                        volume=float(row.get("volume", 0.0)),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return candles

    def place_market_order(self, instrument: str, units: float, tag: str) -> dict[str, object]:
        if self.config.paper_trade:
            return {"paper": True, "instrument": instrument, "units": units, "time": datetime.now(timezone.utc).isoformat()}
        payload = {
            "order": {
                "type": "MARKET",
                "instrument": instrument,
                "units": str(round(units, 4)),
                "timeInForce": "FOK",
                "positionFill": "DEFAULT",
                "clientExtensions": {"tag": tag},
            }
        }
        return self._request("POST", f"/v3/accounts/{self.config.oanda_account_id}/orders", payload)
