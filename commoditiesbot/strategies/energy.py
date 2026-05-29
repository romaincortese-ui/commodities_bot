from __future__ import annotations

from commoditiesbot.config import CommodityConfig
from commoditiesbot.fundamental import (
    crude_inventory_bias,
    dollar_bias,
    hdd_natgas_demand_bias,
    natgas_storage_bias,
    noaa_hdd_natgas_bias,
)
from commoditiesbot.models import Candle, CommoditySignal
from commoditiesbot.strategies.common import trend_signal


def energy_signal(symbol: str, candles: list[Candle], config: CommodityConfig) -> CommoditySignal | None:
    # Broad USD headwind applies to all energy commodities
    usd_bias = dollar_bias(config.fred_api_key)

    if symbol == "NATGAS":
        # Storage surplus/deficit (EIA weekly) + HDD demand bias (EIA or NOAA)
        storage_bias = natgas_storage_bias(config.eia_api_key)
        hdd_bias = hdd_natgas_demand_bias(config.eia_api_key) or noaa_hdd_natgas_bias(config.noaa_cdo_token)
        fundamental = storage_bias + hdd_bias + usd_bias
        return trend_signal(
            symbol,
            candles,
            "NATGAS_WEATHER_STORAGE",
            atr_mult=0.95,
            reward_risk=1.35,
            min_score=57.0,
            max_hold=12,
            event_bias=-1.0 + fundamental,
            prefer_breakout=False,
        )
    # WTI / BRENT
    inv_bias = crude_inventory_bias(config.eia_api_key)
    fundamental = inv_bias + usd_bias
    return trend_signal(
        symbol,
        candles,
        "CRUDE_INVENTORY_TREND",
        atr_mult=1.10,
        reward_risk=1.65,
        min_score=58.0,
        max_hold=20,
        event_bias=1.0 + fundamental,
    )
