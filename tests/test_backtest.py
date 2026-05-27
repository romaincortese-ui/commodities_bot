from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from commoditiesbot.backtest import run_backtest
from commoditiesbot.backtest.data import FixtureMarketDataProvider
from commoditiesbot.backtest.engine import BacktestEngine, _evaluate_no_progress_exit
from commoditiesbot.config import CommodityConfig
from commoditiesbot.models import Candle, CommodityPosition


class BacktestTests(unittest.TestCase):
    def test_fixture_backtest_is_positive(self) -> None:
        env = dict(os.environ)
        env["BACKTEST_DAYS"] = "30"
        with patch.dict(os.environ, env, clear=True):
            config = CommodityConfig.from_env()
        result = BacktestEngine(config, FixtureMarketDataProvider(days=90)).run()
        self.assertGreater(result.total_trades, 0)
        self.assertGreater(result.total_pnl, 0)
        self.assertGreater(result.profit_factor, 1.0)

    def test_profit_lock_backtest_improves_fixture_pnl(self) -> None:
        env = dict(os.environ)
        env["BACKTEST_DAYS"] = "30"
        provider = FixtureMarketDataProvider(days=90)
        with patch.dict(os.environ, {**env, "PROFIT_LOCK_ENABLED": "false"}, clear=True):
            baseline = BacktestEngine(CommodityConfig.from_env(), provider).run()
        with patch.dict(os.environ, {**env, "PROFIT_LOCK_ENABLED": "true"}, clear=True):
            candidate = BacktestEngine(CommodityConfig.from_env(), provider).run()
        self.assertGreater(candidate.total_pnl, baseline.total_pnl)
        self.assertTrue(any(trade.exit_reason == "peak_pullback_profit_lock" for trade in candidate.trades))

    def test_backtest_command_fails_when_metrics_are_negative(self) -> None:
        result = SimpleNamespace(
            data_provider="fixture",
            total_trades=3,
            wins=1,
            losses=2,
            win_rate=1 / 3,
            total_pnl=-12.5,
            return_pct=-0.00125,
            profit_factor=0.7,
            max_drawdown_pct=-0.004,
            by_bucket={"ENERGY": -12.5},
        )

        class FakeBacktestEngine:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def run(self):
                return result

        with patch.object(run_backtest, "BacktestEngine", FakeBacktestEngine), patch.object(run_backtest, "write_report"):
            self.assertEqual(run_backtest.main(), 1)

    def test_no_progress_exit_cuts_trade_that_never_launches(self) -> None:
        env = dict(os.environ)
        env["COMMODITIES_NO_PROGRESS_EXIT_ENABLED"] = "true"
        env["COMMODITIES_NO_PROGRESS_MIN_BARS"] = "3"
        env["COMMODITIES_NO_PROGRESS_MIN_PEAK_R"] = "0.25"
        env["COMMODITIES_NO_PROGRESS_LOSS_R"] = "0.45"
        with patch.dict(os.environ, env, clear=True):
            config = CommodityConfig.from_env()
        position = CommodityPosition(
            symbol="WTI",
            side="LONG",
            strategy="CRUDE_INVENTORY_TREND",
            entry_price=80.0,
            units=10.0,
            sl_price=75.0,
            tp_price=90.0,
            opened_at=datetime.now(timezone.utc),
            risk_amount=50.0,
            bucket="ENERGY",
            bars_held=3,
        )
        candle = Candle(time=datetime.now(timezone.utc), open=79.0, high=80.5, low=77.4, close=77.5, volume=1000.0)

        exit_signal = _evaluate_no_progress_exit(position, candle, config)

        self.assertEqual(exit_signal, (77.5, "no_progress_loss_exit"))


if __name__ == "__main__":
    unittest.main()
