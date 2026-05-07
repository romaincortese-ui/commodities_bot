from __future__ import annotations

from commoditiesbot.config import CommodityConfig
from commoditiesbot.models import Candle, CommoditySignal
from commoditiesbot.strategies.common import trend_signal


def softs_signal(symbol: str, candles: list[Candle], config: CommodityConfig) -> CommoditySignal | None:
    event_bias = {"COFFEE": 2.0, "COCOA": 2.0, "SUGAR": 1.0, "COTTON": -0.25}.get(symbol, 0.0)
    signal = trend_signal(
        symbol,
        candles,
        f"{symbol}_SUPPLY_WEATHER_TREND",
        atr_mult=1.35,
        reward_risk=1.85,
        min_score=58.5,
        max_hold=12,
        event_bias=event_bias,
        prefer_breakout=True,
    )
    if signal is not None and symbol == "SUGAR" and signal.score < 70.0:
        return None
    return signal
