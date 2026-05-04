from __future__ import annotations

from commoditiesbot.config import SYMBOL_BUCKETS
from commoditiesbot.indicators import atr, clamp, ema, highest, lowest, momentum, sma, stdev
from commoditiesbot.models import Candle, CommoditySignal


def trend_signal(
    symbol: str,
    candles: list[Candle],
    strategy: str,
    *,
    atr_mult: float,
    reward_risk: float,
    min_score: float,
    max_hold: int,
    event_bias: float = 0.0,
    prefer_breakout: bool = True,
) -> CommoditySignal | None:
    if len(candles) < 28:
        return None
    closes = [candle.close for candle in candles]
    last = candles[-1]
    fast = ema(closes[-12:], 6)
    medium = ema(closes[-24:], 12)
    slow = ema(closes, 24)
    atr_value = atr(candles, 14)
    mom5 = momentum(closes, 5)
    mom15 = momentum(closes, 15)
    breakout_up = last.close >= highest(candles[:-1], 18) * 0.997 if prefer_breakout else last.close > medium
    breakout_down = last.close <= lowest(candles[:-1], 18) * 1.003 if prefer_breakout else last.close < medium
    trend = (fast - slow) / max(atr_value, 0.0001)
    vol = stdev(closes, 20) / max(sma(closes, 20), 0.0001)

    long_score = 48.0 + clamp(trend * 8.0, -18.0, 18.0) + clamp(mom5 * 350.0, -12.0, 12.0) + clamp(mom15 * 180.0, -10.0, 10.0)
    short_score = 48.0 - clamp(trend * 8.0, -18.0, 18.0) - clamp(mom5 * 350.0, -12.0, 12.0) - clamp(mom15 * 180.0, -10.0, 10.0)
    long_score += event_bias
    short_score -= event_bias
    if breakout_up:
        long_score += 8.0
    if breakout_down:
        short_score += 8.0
    if vol > 0.04:
        long_score -= 3.0
        short_score -= 3.0

    side = "LONG" if long_score >= short_score else "SHORT"
    score = max(long_score, short_score)
    if score < min_score:
        return None

    price = last.close
    stop_distance = max(atr_value * atr_mult, price * 0.006)
    if side == "LONG":
        sl_price = price - stop_distance
        tp_price = price + stop_distance * reward_risk
    else:
        sl_price = price + stop_distance
        tp_price = price - stop_distance * reward_risk
    return CommoditySignal(
        symbol=symbol,
        side=side,
        strategy=strategy,
        score=round(score, 4),
        price=price,
        sl_price=sl_price,
        tp_price=tp_price,
        atr=atr_value,
        expected_hold_bars=max_hold,
        data_freshness_minutes=24.0 * 60.0,
        event_risk="NORMAL",
        bucket=SYMBOL_BUCKETS.get(symbol, "OTHER"),
        metadata={"time": last.time, "mom5": mom5, "mom15": mom15, "trend": trend, "expected_hold_bars": max_hold},
    )
