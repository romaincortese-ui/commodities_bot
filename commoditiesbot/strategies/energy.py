from __future__ import annotations

from commoditiesbot.config import CommodityConfig
from commoditiesbot.models import Candle, CommoditySignal
from commoditiesbot.strategies.common import trend_signal


def energy_signal(symbol: str, candles: list[Candle], config: CommodityConfig) -> CommoditySignal | None:
    if symbol == "NATGAS":
        return trend_signal(
            symbol,
            candles,
            "NATGAS_WEATHER_STORAGE",
            atr_mult=0.95,
            reward_risk=1.35,
            min_score=57.0,
            max_hold=4,
            event_bias=-1.0,
            prefer_breakout=False,
        )
    if symbol in {"GASOLINE", "HEATING_OIL"}:
        return trend_signal(
            symbol,
            candles,
            "PRODUCT_INVENTORY_TREND",
            atr_mult=1.05,
            reward_risk=1.55,
            min_score=58.0,
            max_hold=6,
            event_bias=1.5,
        )
    return trend_signal(
        symbol,
        candles,
        "CRUDE_INVENTORY_TREND",
        atr_mult=1.10,
        reward_risk=1.65,
        min_score=58.0,
        max_hold=7,
        event_bias=1.0,
    )
