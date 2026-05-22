from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from commoditiesbot.backtest import run_backtest
from commoditiesbot.backtest.data import FixtureMarketDataProvider
from commoditiesbot.backtest.engine import BacktestEngine
from commoditiesbot.config import CommodityConfig


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

    def test_backtest_command_succeeds_when_metrics_are_negative(self) -> None:
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
            self.assertEqual(run_backtest.main(), 0)


if __name__ == "__main__":
    unittest.main()
