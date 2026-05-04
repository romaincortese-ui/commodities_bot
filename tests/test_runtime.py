from __future__ import annotations

import unittest

from commoditiesbot.config import CommodityConfig
from commoditiesbot.runtime import _format_scan_message


class RuntimeMessageTests(unittest.TestCase):
    def test_scan_message_is_clear_and_visual(self) -> None:
        config = CommodityConfig.from_env()
        snapshot = {
            "time": "2026-05-04T17:15:00+00:00",
            "data_provider_counts": {"oanda": 7, "fixture": 5},
            "oanda_instrument_count": 123,
            "oanda_failures": ["COFFEE:OANDA request failed"],
            "top_signals": [
                {
                    "symbol": "BRENT",
                    "side": "LONG",
                    "score": 91.21,
                    "strategy": "CRUDE_INVENTORY_TREND",
                    "data_provider": "oanda",
                    "oanda_instrument": "BCO_USD",
                }
            ],
        }

        message = _format_scan_message(snapshot, config)

        self.assertIn("🌾 Commodities Bot", message)
        self.assertIn("📊 Data: OANDA 7/12", message)
        self.assertIn("⚠️ Fallbacks", message)
        self.assertIn("🟢 LONG BRENT", message)
        self.assertIn("📡 OANDA | BCO_USD", message)


if __name__ == "__main__":
    unittest.main()