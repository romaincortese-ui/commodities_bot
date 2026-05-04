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
        self._instrument_details_cache: dict[str, dict[str, int]] | None = None

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
        except HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8")
            except Exception:
                detail = str(exc)
            try:
                parsed = json.loads(detail)
                rejection = parsed.get("orderRejectTransaction", {}) if isinstance(parsed, dict) else {}
                if isinstance(rejection, dict) and rejection.get("rejectReason"):
                    detail = str(rejection["rejectReason"])
            except json.JSONDecodeError:
                pass
            raise RuntimeError(f"OANDA request failed: {exc.code} {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"OANDA request failed: {exc}") from exc

    def tradeable_instruments(self) -> list[str]:
        return list(self._instrument_details().keys())

    def _instrument_details(self) -> dict[str, dict[str, int]]:
        if self._instrument_details_cache is not None:
            return self._instrument_details_cache
        payload = self._request("GET", f"/v3/accounts/{self.config.oanda_account_id}/instruments")
        instruments = payload.get("instruments", [])
        details: dict[str, dict[str, int]] = {}
        if not isinstance(instruments, list):
            self._instrument_details_cache = details
            return details
        for item in instruments:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            name = str(item["name"]).upper()
            details[name] = {
                "displayPrecision": _int_or_default(item.get("displayPrecision"), 5),
                "tradeUnitsPrecision": _int_or_default(item.get("tradeUnitsPrecision"), 0),
            }
        self._instrument_details_cache = details
        return details

    def _price_precision(self, instrument: str) -> int:
        details = self._instrument_details().get(instrument.upper(), {})
        return details.get("displayPrecision", 5)

    def _units_precision(self, instrument: str) -> int:
        details = self._instrument_details().get(instrument.upper(), {})
        return details.get("tradeUnitsPrecision", 0)

    def account_nav(self) -> float:
        payload = self._request("GET", f"/v3/accounts/{self.config.oanda_account_id}/summary")
        account = payload.get("account", {})
        if not isinstance(account, dict):
            return 0.0
        for key in ("NAV", "balance"):
            try:
                return float(account.get(key) or 0.0)
            except (TypeError, ValueError):
                continue
        return 0.0

    def open_positions(self) -> set[str]:
        payload = self._request("GET", f"/v3/accounts/{self.config.oanda_account_id}/openPositions")
        positions = payload.get("positions", [])
        open_instruments: set[str] = set()
        if not isinstance(positions, list):
            return open_instruments
        for position in positions:
            if not isinstance(position, dict):
                continue
            instrument = str(position.get("instrument") or "").strip().upper()
            if not instrument:
                continue
            try:
                long_units = abs(float((position.get("long") or {}).get("units") or 0.0))
                short_units = abs(float((position.get("short") or {}).get("units") or 0.0))
            except (AttributeError, TypeError, ValueError):
                continue
            if long_units > 0 or short_units > 0:
                open_instruments.add(instrument)
        return open_instruments

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

    def place_market_order(
        self,
        instrument: str,
        units: float,
        tag: str,
        *,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> dict[str, object]:
        if self.config.paper_trade:
            return {"paper": True, "instrument": instrument, "units": units, "time": datetime.now(timezone.utc).isoformat()}
        price_precision = self._price_precision(instrument)
        order = {
            "type": "MARKET",
            "instrument": instrument,
            "units": _format_units(units, self._units_precision(instrument)),
            "timeInForce": "FOK",
            "positionFill": "DEFAULT",
            "clientExtensions": {"tag": tag},
        }
        if stop_loss is not None and stop_loss > 0:
            order["stopLossOnFill"] = {"price": _format_price(stop_loss, price_precision)}
        if take_profit is not None and take_profit > 0:
            order["takeProfitOnFill"] = {"price": _format_price(take_profit, price_precision)}
        payload = {
            "order": order
        }
        return self._request("POST", f"/v3/accounts/{self.config.oanda_account_id}/orders", payload)


def _int_or_default(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _format_units(value: float, precision: int) -> str:
    digits = max(0, min(8, precision))
    if digits == 0:
        return str(int(round(value)))
    return f"{value:.{digits}f}".rstrip("0").rstrip(".")


def _format_price(value: float, precision: int) -> str:
    digits = max(0, min(8, precision))
    if digits == 0:
        return str(int(round(value)))
    return f"{value:.{digits}f}".rstrip("0").rstrip(".")
