from __future__ import annotations

from commoditiesbot.config import CommodityConfig, SYMBOL_BUCKETS
from commoditiesbot.models import Candle, CommoditySignal
from commoditiesbot.strategies.agriculture import agriculture_signal
from commoditiesbot.strategies.energy import energy_signal
from commoditiesbot.strategies.softs import softs_signal


def generate_signal(symbol: str, candles: list[Candle], config: CommodityConfig) -> CommoditySignal | None:
    bucket = SYMBOL_BUCKETS.get(symbol)
    if bucket == "ENERGY":
        return energy_signal(symbol, candles, config)
    if bucket == "GRAINS":
        return agriculture_signal(symbol, candles, config)
    if bucket == "SOFTS":
        return softs_signal(symbol, candles, config)
    return None
