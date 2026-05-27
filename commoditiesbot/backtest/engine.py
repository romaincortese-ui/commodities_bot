from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

from commoditiesbot.config import CommodityConfig
from commoditiesbot.exits import evaluate_exit
from commoditiesbot.models import BacktestResult, Candle, CommodityPosition, Trade
from commoditiesbot.risk import can_open, position_from_signal
from commoditiesbot.strategies import generate_signal


FEE_RATE = 0.00035
SLIPPAGE_RATE = 0.00025


class BacktestEngine:
    def __init__(self, config: CommodityConfig, provider) -> None:
        self.config = config
        self.provider = provider

    def run(self) -> BacktestResult:
        histories = {symbol: self.provider.history(symbol) for symbol in self.config.universe}
        min_bars = min(len(candles) for candles in histories.values() if candles)
        start_index = max(30, min_bars - self.config.backtest_days)
        balance = self.config.backtest_initial_balance
        equity_curve = [balance]
        positions: list[CommodityPosition] = []
        trades: list[Trade] = []

        for index in range(start_index, min_bars):
            equity = balance
            for position in list(positions):
                candle = histories[position.symbol][index]
                should_exit, exit_price, reason = evaluate_exit(position, candle)
                profit_lock_exit = _evaluate_profit_lock(position, candle, self.config)
                if profit_lock_exit is not None and (not should_exit or reason in {"stop_loss", "time_stop", "hold"}):
                    should_exit = True
                    exit_price, reason = profit_lock_exit
                no_progress_exit = _evaluate_no_progress_exit(position, candle, self.config)
                if no_progress_exit is not None and (not should_exit or reason in {"time_stop", "hold"}):
                    should_exit = True
                    exit_price, reason = no_progress_exit
                if should_exit:
                    gross = (exit_price - position.entry_price) * position.units * position.direction
                    fees = (abs(position.entry_price * position.units) + abs(exit_price * position.units)) * FEE_RATE
                    slippage = abs(exit_price * position.units) * SLIPPAGE_RATE
                    pnl = gross - fees - slippage
                    balance += pnl
                    risk = max(position.risk_amount, 0.0001)
                    trades.append(
                        Trade(
                            symbol=position.symbol,
                            side=position.side,
                            strategy=position.strategy,
                            bucket=position.bucket,
                            entry_time=position.opened_at,
                            exit_time=candle.time,
                            entry_price=position.entry_price,
                            exit_price=exit_price,
                            units=position.units,
                            pnl=pnl,
                            return_r=pnl / risk,
                            exit_reason=reason,
                        )
                    )
                    positions.remove(position)

            candidates = []
            for symbol, candles in histories.items():
                signal = generate_signal(symbol, candles[: index + 1], self.config)
                if signal is not None:
                    candidates.append(signal)
            candidates.sort(key=lambda signal: signal.score, reverse=True)

            for signal in candidates:
                allowed, _ = can_open(signal, positions, max(balance, 1.0), self.config)
                if not allowed:
                    continue
                position = position_from_signal(signal, max(balance, 1.0), self.config)
                if position.units > 0:
                    positions.append(position)
                if len(positions) >= self.config.max_open_positions:
                    break
            marked = balance + sum(
                (histories[position.symbol][index].close - position.entry_price) * position.units * position.direction
                for position in positions
            )
            equity_curve.append(marked)

        final_index = min_bars - 1
        for position in list(positions):
            candle = histories[position.symbol][final_index]
            gross = (candle.close - position.entry_price) * position.units * position.direction
            fees = (abs(position.entry_price * position.units) + abs(candle.close * position.units)) * FEE_RATE
            pnl = gross - fees
            balance += pnl
            trades.append(
                Trade(
                    symbol=position.symbol,
                    side=position.side,
                    strategy=position.strategy,
                    bucket=position.bucket,
                    entry_time=position.opened_at,
                    exit_time=candle.time,
                    entry_price=position.entry_price,
                    exit_price=candle.close,
                    units=position.units,
                    pnl=pnl,
                    return_r=pnl / max(position.risk_amount, 0.0001),
                    exit_reason="final_mark",
                )
            )

        return build_result(self.config.backtest_initial_balance, balance, trades, equity_curve, self.config.backtest_data_provider)


def build_result(initial_balance: float, final_balance: float, trades: list[Trade], equity_curve: list[float], data_provider: str) -> BacktestResult:
    total_pnl = final_balance - initial_balance
    wins = sum(1 for trade in trades if trade.pnl > 0)
    losses = sum(1 for trade in trades if trade.pnl <= 0)
    gross_profit = sum(trade.pnl for trade in trades if trade.pnl > 0)
    gross_loss = abs(sum(trade.pnl for trade in trades if trade.pnl < 0))
    peak = equity_curve[0] if equity_curve else initial_balance
    max_dd = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        if peak > 0:
            max_dd = max(max_dd, (peak - value) / peak)
    by_bucket: dict[str, float] = defaultdict(float)
    for trade in trades:
        by_bucket[trade.bucket] += trade.pnl
    return BacktestResult(
        initial_balance=initial_balance,
        final_balance=final_balance,
        total_pnl=total_pnl,
        return_pct=total_pnl / initial_balance if initial_balance else 0.0,
        max_drawdown_pct=max_dd,
        total_trades=len(trades),
        wins=wins,
        losses=losses,
        win_rate=wins / len(trades) if trades else 0.0,
        profit_factor=(gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0),
        data_provider=data_provider,
        by_bucket=dict(by_bucket),
        trades=trades,
    )


def _evaluate_profit_lock(position: CommodityPosition, candle: Candle, config: CommodityConfig) -> tuple[float, str] | None:
    if not config.profit_lock_enabled:
        return None
    metadata = position.metadata if isinstance(position.metadata, dict) else {}
    if metadata is not position.metadata:
        position.metadata = metadata
    armed_before = bool(metadata.get("profit_lock_armed"))
    favorable_price = candle.high if position.direction > 0 else candle.low
    peak_pct = _net_pnl_pct(position, favorable_price)
    if peak_pct is None:
        return None
    previous_peak = _float_or_none(metadata.get("profit_lock_peak_pnl_pct"))
    if previous_peak is None or peak_pct > previous_peak:
        previous_peak = peak_pct
        metadata["profit_lock_peak_pnl_pct"] = peak_pct
        metadata["profit_lock_peak_price"] = favorable_price
    trigger_pct = max(0.0, float(config.profit_lock_trigger_pct))
    pullback_pct = max(0.0, float(config.profit_lock_pullback_pct))
    if previous_peak < trigger_pct:
        return None
    floor_pct = max(0.0, previous_peak - pullback_pct)
    metadata["profit_lock_armed"] = True
    metadata["profit_lock_floor_pnl_pct"] = floor_pct
    if not armed_before or floor_pct <= 0.0:
        return None
    exit_price = _price_for_net_pnl_pct(position, floor_pct)
    if exit_price is None or exit_price <= 0:
        return None
    if position.direction > 0 and candle.low <= exit_price:
        return exit_price, "peak_pullback_profit_lock"
    if position.direction < 0 and candle.high >= exit_price:
        return exit_price, "peak_pullback_profit_lock"
    return None


def _evaluate_no_progress_exit(position: CommodityPosition, candle: Candle, config: CommodityConfig) -> tuple[float, str] | None:
    if not config.no_progress_exit_enabled:
        return None
    metadata = position.metadata if isinstance(position.metadata, dict) else {}
    if metadata is not position.metadata:
        position.metadata = metadata
    favorable_price = candle.high if position.direction > 0 else candle.low
    peak_r = _return_r(position, favorable_price)
    previous_peak = _float_or_none(metadata.get("no_progress_peak_r"))
    if previous_peak is None or peak_r > previous_peak:
        previous_peak = peak_r
        metadata["no_progress_peak_r"] = peak_r
    if position.bars_held < max(1, int(config.no_progress_min_bars)):
        return None
    if previous_peak >= max(0.0, float(config.no_progress_min_peak_r)):
        return None
    current_r = _return_r(position, candle.close)
    if current_r > -max(0.0, float(config.no_progress_loss_r)):
        return None
    metadata["no_progress_exit_r"] = current_r
    return candle.close, "no_progress_loss_exit"


def _net_pnl_pct(position: CommodityPosition, price: float) -> float | None:
    budget = max(float(position.risk_amount), 0.0001)
    pnl = _net_pnl(position, price)
    return pnl / budget * 100.0


def _net_pnl(position: CommodityPosition, price: float) -> float:
    gross = (price - position.entry_price) * position.units * position.direction
    fees = (abs(position.entry_price * position.units) + abs(price * position.units)) * FEE_RATE
    slippage = abs(price * position.units) * SLIPPAGE_RATE
    return gross - fees - slippage


def _return_r(position: CommodityPosition, price: float) -> float:
    return _net_pnl(position, price) / max(float(position.risk_amount), 0.0001)


def _price_for_net_pnl_pct(position: CommodityPosition, pnl_pct: float) -> float | None:
    units = abs(float(position.units))
    if units <= 0:
        return None
    target_pnl = max(0.0, float(pnl_pct)) / 100.0 * max(float(position.risk_amount), 0.0001)
    entry = float(position.entry_price)
    if position.direction > 0:
        denominator = 1.0 - FEE_RATE - SLIPPAGE_RATE
        if denominator <= 0:
            return None
        return (target_pnl / units + entry * (1.0 + FEE_RATE)) / denominator
    denominator = 1.0 + FEE_RATE + SLIPPAGE_RATE
    return (entry * (1.0 - FEE_RATE) - target_pnl / units) / denominator


def _float_or_none(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def write_report(result: BacktestResult, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = asdict(result)
    summary.pop("trades")
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    with (output_dir / "trade_journal.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(result.trades[0]).keys()) if result.trades else ["symbol"])
        writer.writeheader()
        for trade in result.trades:
            writer.writerow(asdict(trade))
