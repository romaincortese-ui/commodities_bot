from __future__ import annotations

import unittest

from commoditiesbot.backtest.data import FixtureMarketDataProvider
from commoditiesbot.config import CommodityConfig
from commoditiesbot.strategies import generate_signal


class StrategyTests(unittest.TestCase):
    def test_strategy_generates_commodity_specific_signal(self) -> None:
        config = CommodityConfig.from_env()
        provider = FixtureMarketDataProvider(days=90)
        signal = generate_signal("WTI", provider.history("WTI"), config)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.strategy, "CRUDE_INVENTORY_TREND")
        self.assertIn(signal.side, {"LONG", "SHORT"})
        self.assertNotEqual(signal.tp_price, signal.sl_price)


if __name__ == "__main__":
    unittest.main()
