from __future__ import annotations

from math import sqrt

from commoditiesbot.models import Candle


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def sma(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    period = min(period, len(values))
    return sum(values[-period:]) / period


def ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    period = max(1, period)
    alpha = 2.0 / (period + 1.0)
    result = values[0]
    for value in values[1:]:
        result = alpha * value + (1.0 - alpha) * result
    return result


def stdev(values: list[float], period: int) -> float:
    if len(values) < 2:
        return 0.0
    window = values[-min(period, len(values)):]
    mean = sum(window) / len(window)
    return sqrt(sum((value - mean) ** 2 for value in window) / max(1, len(window) - 1))


def atr(candles: list[Candle], period: int = 14) -> float:
    if len(candles) < 2:
        return max(candles[-1].high - candles[-1].low, 0.0001) if candles else 0.0001
    ranges: list[float] = []
    for prev, cur in zip(candles[-period - 1:-1], candles[-period:]):
        ranges.append(max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close)))
    return max(sum(ranges) / len(ranges), 0.0001)


def momentum(values: list[float], period: int) -> float:
    if len(values) <= period or values[-period - 1] == 0:
        return 0.0
    return values[-1] / values[-period - 1] - 1.0


def highest(candles: list[Candle], period: int) -> float:
    window = candles[-min(period, len(candles)):]
    return max(candle.high for candle in window) if window else 0.0


def lowest(candles: list[Candle], period: int) -> float:
    window = candles[-min(period, len(candles)):]
    return min(candle.low for candle in window) if window else 0.0
