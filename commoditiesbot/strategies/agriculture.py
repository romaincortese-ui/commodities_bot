from __future__ import annotations

from commoditiesbot.config import CommodityConfig
from commoditiesbot.fundamental import dollar_bias, is_wasde_blackout
from commoditiesbot.models import Candle, CommoditySignal
from commoditiesbot.strategies.common import trend_signal


def agriculture_signal(symbol: str, candles: list[Candle], config: CommodityConfig) -> CommoditySignal | None:
    # Block entries in the WASDE blackout window (2 days before, 1 day after)
    if is_wasde_blackout():
        return None

    # Per-grain base bias + broad USD headwind
    base_bias = {"CORN": 1.0, "WHEAT": -0.5, "SOYBEANS": 1.25}.get(symbol, 0.0)
    usd_bias = dollar_bias(config.fred_api_key)
    event_bias = base_bias + usd_bias

    signal = trend_signal(
        symbol,
        candles,
        f"{symbol}_CROP_WEATHER_TREND",
        atr_mult=1.20,
        reward_risk=1.70,
        min_score=57.5,
        max_hold=25,
        event_bias=event_bias,
        prefer_breakout=True,
    )
    if signal is not None and signal.side == "LONG" and signal.score < 80.0:
        return None
    return signal
