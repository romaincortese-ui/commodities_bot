from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class Candle:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(slots=True)
class CommoditySignal:
    symbol: str
    side: str
    strategy: str
    score: float
    price: float
    sl_price: float
    tp_price: float
    atr: float
    expected_hold_bars: int
    data_freshness_minutes: float
    event_risk: str
    bucket: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class CommodityPosition:
    symbol: str
    side: str
    strategy: str
    entry_price: float
    units: float
    sl_price: float
    tp_price: float
    opened_at: datetime
    risk_amount: float
    bucket: str
    order_id: str = "paper"
    bars_held: int = 0
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def direction(self) -> int:
        return 1 if self.side == "LONG" else -1


@dataclass(slots=True)
class Trade:
    symbol: str
    side: str
    strategy: str
    bucket: str
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    units: float
    pnl: float
    return_r: float
    exit_reason: str


@dataclass(slots=True)
class BacktestResult:
    initial_balance: float
    final_balance: float
    total_pnl: float
    return_pct: float
    max_drawdown_pct: float
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    profit_factor: float
    data_provider: str
    by_bucket: dict[str, float]
    trades: list[Trade]
