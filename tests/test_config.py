from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from commoditiesbot.config import CommodityConfig, DEFAULT_UNIVERSE


class ConfigTests(unittest.TestCase):
    def test_config_defaults_are_paper_safe(self) -> None:
        env = {key: value for key, value in os.environ.items() if key not in {"OANDA_ACCOUNT_ID", "OANDA_API_TOKEN", "PAPER_TRADE"}}
        with patch.dict(os.environ, env, clear=True):
            config = CommodityConfig.from_env()
        self.assertTrue(config.paper_trade)
        self.assertFalse(config.has_oanda_credentials)
        self.assertEqual(config.universe, DEFAULT_UNIVERSE)
        self.assertEqual(config.scan_interval_seconds, 3600)

    def test_list_variables_accept_commas_or_whitespace(self) -> None:
        env = {"COMMODITIES_UNIVERSE": "WTI BRENT,NATGAS", "COMMODITIES_STRATEGIES": "CRUDE NATGAS"}
        with patch.dict(os.environ, env, clear=True):
            config = CommodityConfig.from_env()
        self.assertEqual(config.universe, ("WTI", "BRENT", "NATGAS"))
        self.assertEqual(config.strategies, ("CRUDE", "NATGAS"))

    def test_oanda_instrument_override(self) -> None:
        with patch.dict(os.environ, {"OANDA_INSTRUMENT_GASOLINE": "RB_USD"}, clear=True):
            config = CommodityConfig.from_env()
        self.assertEqual(config.oanda_instrument_for("WTI"), "WTICO_USD")
        self.assertEqual(config.oanda_instrument_for("GASOLINE"), "RB_USD")


if __name__ == "__main__":
    unittest.main()
