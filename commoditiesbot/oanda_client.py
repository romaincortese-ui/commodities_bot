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
        except TimeoutError as exc:
            raise RuntimeError(f"OANDA request timed out: {exc}") from exc

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

    def account_summary(self) -> dict[str, object]:
        payload = self._request("GET", f"/v3/accounts/{self.config.oanda_account_id}/summary")
        account = payload.get("account", {})
        if not isinstance(account, dict):
            return {}
        return account

    def account_nav(self) -> float:
        account = self.account_summary()
        for key in ("NAV", "balance"):
            value = account.get(key)
            if value in (None, ""):
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return 0.0

    def account_available_balance(self) -> float:
        account = self.account_summary()
        for key in ("marginAvailable", "availableMargin", "balance", "NAV"):
            value = account.get(key)
            if value in (None, ""):
                continue
            try:
                return float(value)
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

    def open_trades(self) -> list[dict[str, object]]:
        payload = self._request("GET", f"/v3/accounts/{self.config.oanda_account_id}/openTrades")
        trades = payload.get("trades", [])
        if not isinstance(trades, list):
            return []
        return [trade for trade in trades if isinstance(trade, dict)]

    def instrument_tradeable(self, instrument: str) -> tuple[bool, str]:
        params = urlencode({"instruments": instrument, "includeHomeConversions": "false"})
        payload = self._request("GET", f"/v3/accounts/{self.config.oanda_account_id}/pricing?{params}")
        prices = payload.get("prices", [])
        if not isinstance(prices, list):
            return False, "pricing_unavailable"
        price = next((item for item in prices if isinstance(item, dict) and str(item.get("instrument") or "").upper() == instrument.upper()), None)
        if not isinstance(price, dict):
            return False, "pricing_unavailable"
        status = str(price.get("status") or "").strip().lower()
        tradeable = price.get("tradeable")
        if status and status != "tradeable":
            return False, f"pricing_status_{status.replace('-', '_')}"
        if tradeable is False:
            return False, "pricing_not_tradeable"
        bids = price.get("bids", [])
        asks = price.get("asks", [])
        if not isinstance(bids, list) or not bids or not isinstance(asks, list) or not asks:
            return False, "pricing_missing_bid_ask"
        return True, status or "tradeable"

    def current_bid_ask(self, instrument: str) -> tuple[float, float]:
        params = urlencode({"instruments": instrument, "includeHomeConversions": "false"})
        payload = self._request("GET", f"/v3/accounts/{self.config.oanda_account_id}/pricing?{params}")
        prices = payload.get("prices", [])
        if not isinstance(prices, list):
            raise RuntimeError("pricing_unavailable")
        price = next((item for item in prices if isinstance(item, dict) and str(item.get("instrument") or "").upper() == instrument.upper()), None)
        if not isinstance(price, dict):
            raise RuntimeError("pricing_unavailable")
        try:
            bid = float(price["bids"][0]["price"])
            ask = float(price["asks"][0]["price"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise RuntimeError("pricing_missing_bid_ask") from exc
        return bid, ask

    def close_trade(self, trade_id: str) -> dict[str, object]:
        return self._request("PUT", f"/v3/accounts/{self.config.oanda_account_id}/trades/{trade_id}/close", {"units": "ALL"})

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
