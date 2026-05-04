from __future__ import annotations

from commoditiesbot.config import CommodityConfig
from commoditiesbot.models import Candle, CommoditySignal
from commoditiesbot.strategies.common import trend_signal


def agriculture_signal(symbol: str, candles: list[Candle], config: CommodityConfig) -> CommoditySignal | None:
    event_bias = {"CORN": 1.0, "WHEAT": -0.5, "SOYBEANS": 1.25}.get(symbol, 0.0)
    return trend_signal(
        symbol,
        candles,
        f"{symbol}_CROP_WEATHER_TREND",
        atr_mult=1.20,
        reward_risk=1.70,
        min_score=57.5,
        max_hold=10,
        event_bias=event_bias,
        prefer_breakout=True,
    )
