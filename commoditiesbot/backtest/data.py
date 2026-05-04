from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

from commoditiesbot.config import BASE_PRICES
from commoditiesbot.models import Candle


class FixtureMarketDataProvider:
    """Deterministic commodity fixtures for pre-secret validation and CI.

    The generated paths deliberately include trend, reversal, and volatility regimes so
    strategy behavior can be validated before OANDA credentials are available.
    """

    def __init__(self, days: int = 120, end: datetime | None = None) -> None:
        self.days = days
        self.end = end or datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        self._cache: dict[str, list[Candle]] = {}

    def history(self, symbol: str) -> list[Candle]:
        symbol = symbol.upper()
        if symbol not in self._cache:
            self._cache[symbol] = self._generate(symbol)
        return list(self._cache[symbol])

    def _generate(self, symbol: str) -> list[Candle]:
        base = BASE_PRICES.get(symbol, 100.0)
        seed = sum(ord(char) for char in symbol) * 7919
        rng = random.Random(seed)
        phase = (seed % 360) / 57.2958
        price = base
        candles: list[Candle] = []
        start = self.end - timedelta(days=self.days - 1)
        drift = self._drift(symbol)
        volatility = self._volatility(symbol)
        for day in range(self.days):
            cycle = math.sin(day / 5.5 + phase) * volatility * 0.45
            slow_cycle = math.sin(day / 18.0 + phase / 2.0) * volatility * 0.85
            regime_push = drift if day % 37 < 24 else -drift * 0.65
            shock = rng.gauss(0.0, volatility * 0.22)
            daily_return = regime_push + cycle + slow_cycle + shock
            open_price = price
            close = max(0.05, open_price * (1.0 + daily_return))
            intraday = abs(daily_return) + volatility * (0.75 + rng.random() * 0.65)
            high = max(open_price, close) * (1.0 + intraday * 0.55)
            low = min(open_price, close) * (1.0 - intraday * 0.55)
            volume = 10000.0 * (1.0 + abs(daily_return) / max(volatility, 0.0001))
            candles.append(
                Candle(
                    time=start + timedelta(days=day),
                    open=open_price,
                    high=high,
                    low=max(0.01, low),
                    close=close,
                    volume=volume,
                )
            )
            price = close
        return candles

    @staticmethod
    def _drift(symbol: str) -> float:
        return {
            "WTI": 0.0023,
            "BRENT": 0.0021,
            "NATGAS": -0.0016,
            "GASOLINE": 0.0018,
            "HEATING_OIL": 0.0017,
            "CORN": 0.0014,
            "WHEAT": -0.0012,
            "SOYBEANS": 0.0015,
            "SUGAR": 0.0012,
            "COFFEE": 0.0020,
            "COCOA": 0.0024,
            "COTTON": -0.0011,
        }.get(symbol, 0.001)

    @staticmethod
    def _volatility(symbol: str) -> float:
        return {
            "NATGAS": 0.034,
            "COCOA": 0.030,
            "COFFEE": 0.024,
            "WTI": 0.020,
            "BRENT": 0.018,
            "GASOLINE": 0.020,
            "HEATING_OIL": 0.019,
            "CORN": 0.014,
            "WHEAT": 0.017,
            "SOYBEANS": 0.013,
            "SUGAR": 0.018,
            "COTTON": 0.016,
        }.get(symbol, 0.015)
