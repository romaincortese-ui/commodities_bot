from __future__ import annotations

import os
from collections import defaultdict

from commoditiesbot.config import CommodityConfig, SYMBOL_BUCKETS
from commoditiesbot.models import CommodityPosition, CommoditySignal


BASE_RISK_BY_BUCKET = {"ENERGY": 0.004375, "GRAINS": 0.00375, "SOFTS": 0.003125}


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def risk_pct_for_signal(signal: CommoditySignal, config: CommodityConfig) -> float:
    base = BASE_RISK_BY_BUCKET.get(signal.bucket, 0.0025)
    quality_mult = max(0.35, min(1.15, signal.score / 82.0))
    if signal.symbol == "NATGAS":
        quality_mult *= _env_float("NATGAS_RISK_PENALTY", 0.55)
    if signal.event_risk == "HIGH":
        quality_mult *= 0.50
    pct = min(base * quality_mult, config.bucket_cap(signal.bucket) * 0.45)
    return pct * max(0.0, _env_float("RISK_AMOUNT_MULTIPLIER", 1.7))



def open_risk_pct(positions: list[CommodityPosition], equity: float) -> float:
    if equity <= 0:
        return 0.0
    return sum(position.risk_amount for position in positions) / equity


def bucket_risk_pct(positions: list[CommodityPosition], equity: float) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    if equity <= 0:
        return {}
    for position in positions:
        totals[position.bucket] += position.risk_amount / equity
    return dict(totals)


def can_open(signal: CommoditySignal, positions: list[CommodityPosition], equity: float, config: CommodityConfig) -> tuple[bool, str]:
    if len(positions) >= config.max_open_positions:
        return False, "max_positions"
    if any(position.symbol == signal.symbol for position in positions):
        return False, "symbol_already_open"
    total_risk = open_risk_pct(positions, equity)
    if total_risk >= config.max_total_risk_pct:
        return False, "portfolio_risk_cap"
    buckets = bucket_risk_pct(positions, equity)
    if buckets.get(signal.bucket, 0.0) >= config.bucket_cap(signal.bucket):
        return False, "bucket_risk_cap"
    return True, "ok"


def position_from_signal(signal: CommoditySignal, equity: float, config: CommodityConfig) -> CommodityPosition:
    risk_pct = risk_pct_for_signal(signal, config)
    risk_amount = equity * risk_pct
    # Minimum meaningful trade size floor (env-tunable). Defaults to 0 so legacy
    # behavior is unchanged when the var is not set. When set, ensures we don't
    # open dust trades on small balances (e.g. a £51 NAV would otherwise size at
    # ~£0.20 per ENERGY signal). Capped at 50% of equity for safety.
    risk_floor = max(0.0, _env_float("RISK_AMOUNT_FLOOR", 0.0))
    if risk_floor > 0.0:
        risk_amount = max(risk_amount, min(risk_floor, equity * 0.5))
    stop_distance = max(abs(signal.price - signal.sl_price), signal.price * 0.002)
    units = risk_amount / stop_distance
    notional_cap_mult = max(0.1, _env_float("NOTIONAL_CAP_MULT", 2.0))
    notional_cap = equity * notional_cap_mult / max(signal.price, 0.0001)
    units = min(units, notional_cap)
    return CommodityPosition(
        symbol=signal.symbol,
        side=signal.side,
        strategy=signal.strategy,
        entry_price=signal.price,
        units=units,
        sl_price=signal.sl_price,
        tp_price=signal.tp_price,
        opened_at=signal.metadata.get("time"),
        risk_amount=risk_amount,
        bucket=SYMBOL_BUCKETS.get(signal.symbol, "OTHER"),
        metadata=dict(signal.metadata),
    )
