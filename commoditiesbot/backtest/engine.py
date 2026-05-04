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
