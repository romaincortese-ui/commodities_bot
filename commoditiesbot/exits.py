from __future__ import annotations

from commoditiesbot.models import Candle, CommodityPosition


def evaluate_exit(position: CommodityPosition, candle: Candle) -> tuple[bool, float, str]:
    direction = position.direction
    position.bars_held += 1
    max_hold = int(position.metadata.get("expected_hold_bars", 8))
    if direction > 0:
        if candle.low <= position.sl_price:
            return True, position.sl_price, "stop_loss"
        if candle.high >= position.tp_price:
            return True, position.tp_price, "take_profit"
    else:
        if candle.high >= position.sl_price:
            return True, position.sl_price, "stop_loss"
        if candle.low <= position.tp_price:
            return True, position.tp_price, "take_profit"
    if position.bars_held >= max_hold:
        return True, candle.close, "time_stop"
    return False, candle.close, "hold"
