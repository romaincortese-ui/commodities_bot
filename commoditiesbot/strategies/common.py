from __future__ import annotations

from commoditiesbot.config import SYMBOL_BUCKETS
from commoditiesbot.indicators import atr, clamp, ema, highest, lowest, momentum, sma, stdev
from commoditiesbot.models import Candle, CommoditySignal


STOP_FLOOR_BY_BUCKET = {"ENERGY": 0.0045, "GRAINS": 0.0035, "SOFTS": 0.0040}


def _adaptive_stop_distance(
    *,
    price: float,
    atr_value: float,
    atr_mult: float,
    trend: float,
    score: float,
    min_score: float,
    volatility: float,
    bucket: str,
) -> tuple[float, dict[str, float]]:
    atr_pct = atr_value / max(price, 0.0001)
    trend_strength = clamp(abs(trend) / 4.0, 0.0, 1.0)
    signal_confidence = clamp((score - min_score) / 20.0, 0.0, 1.0)
    volatility_ratio = clamp(volatility / max(atr_pct, 0.0001), 0.75, 1.35)

    adaptive_mult = atr_mult * (0.85 + 0.10 * volatility_ratio - 0.25 * trend_strength - 0.15 * signal_confidence)
    adaptive_mult = clamp(adaptive_mult, 0.60, 1.35)

    bucket_floor = STOP_FLOOR_BY_BUCKET.get(bucket, 0.0040)
    floor_pct = max(0.0025, min(bucket_floor, atr_pct * 0.80))
    distance = max(atr_value * adaptive_mult, price * floor_pct)
    return distance, {
        "atr_pct": atr_pct,
        "stop_atr_mult": adaptive_mult,
        "stop_floor_pct": floor_pct,
        "stop_distance": distance,
    }


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
    bucket = SYMBOL_BUCKETS.get(symbol, "OTHER")
    stop_distance, stop_metadata = _adaptive_stop_distance(
        price=price,
        atr_value=atr_value,
        atr_mult=atr_mult,
        trend=trend,
        score=score,
        min_score=min_score,
        volatility=vol,
        bucket=bucket,
    )
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
        bucket=bucket,
        metadata={"time": last.time, "mom5": mom5, "mom15": mom15, "trend": trend, "expected_hold_bars": max_hold, **stop_metadata},
    )
