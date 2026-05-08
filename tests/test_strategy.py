from __future__ import annotations

import unittest

from commoditiesbot.backtest.data import FixtureMarketDataProvider
from commoditiesbot.config import CommodityConfig
from commoditiesbot.strategies import generate_signal
from commoditiesbot.strategies.common import _adaptive_stop_distance


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
        self.assertIn("stop_atr_mult", signal.metadata)

    def test_adaptive_stop_tightens_confident_low_noise_setup(self) -> None:
        distance, metadata = _adaptive_stop_distance(
            price=100.0,
            atr_value=0.5,
            atr_mult=1.10,
            trend=3.0,
            score=70.0,
            min_score=58.0,
            volatility=0.006,
            bucket="ENERGY",
        )
        static_distance = max(0.5 * 1.10, 100.0 * 0.006)
        self.assertLess(distance, static_distance)
        self.assertGreaterEqual(distance, 100.0 * 0.0025)
        self.assertGreater(metadata["stop_atr_mult"], 0.0)


if __name__ == "__main__":
    unittest.main()
