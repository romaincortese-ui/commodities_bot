from __future__ import annotations

import os
import unittest
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
