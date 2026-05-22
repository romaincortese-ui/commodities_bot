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
        self.assertEqual(config.scan_interval_seconds, 300)
        self.assertEqual(config.heartbeat_seconds, 21600)
        self.assertTrue(config.profit_lock_enabled)
        self.assertEqual(config.profit_lock_trigger_pct, 3.0)
        self.assertEqual(config.profit_lock_pullback_pct, 1.5)
        self.assertEqual(config.broker_reentry_cooldown_minutes, 360)

    def test_list_variables_accept_commas_or_whitespace(self) -> None:
        env = {"COMMODITIES_UNIVERSE": "WTI BRENT,NATGAS", "COMMODITIES_STRATEGIES": "CRUDE NATGAS"}
        with patch.dict(os.environ, env, clear=True):
            config = CommodityConfig.from_env()
        self.assertEqual(config.universe, ("WTI", "BRENT", "NATGAS"))
        self.assertEqual(config.strategies, ("CRUDE", "NATGAS"))

    def test_heartbeat_env_is_clamped_to_six_hours(self) -> None:
        with patch.dict(os.environ, {"COMMODITIES_HEARTBEAT_SECONDS": "3600"}, clear=True):
            config = CommodityConfig.from_env()
        self.assertEqual(config.heartbeat_seconds, 21600)
        with patch.dict(os.environ, {"HEARTBEAT_SECONDS": "3600"}, clear=True):
            config = CommodityConfig.from_env()
        self.assertEqual(config.heartbeat_seconds, 21600)

    def test_oanda_instrument_override(self) -> None:
        with patch.dict(os.environ, {"OANDA_INSTRUMENT_GASOLINE": "RB_USD"}, clear=True):
            config = CommodityConfig.from_env()
        self.assertEqual(config.oanda_instrument_for("WTI"), "WTICO_USD")
        self.assertEqual(config.oanda_instrument_for("GASOLINE"), "RB_USD")

    def test_profit_lock_env_overrides_defaults(self) -> None:
        env = {"PROFIT_LOCK_ENABLED": "false", "PROFIT_LOCK_TRIGGER_PCT": "4.5", "PROFIT_LOCK_PULLBACK_PCT": "2.25"}
        with patch.dict(os.environ, env, clear=True):
            config = CommodityConfig.from_env()
        self.assertFalse(config.profit_lock_enabled)
        self.assertEqual(config.profit_lock_trigger_pct, 4.5)
        self.assertEqual(config.profit_lock_pullback_pct, 2.25)

    def test_broker_reentry_cooldown_env_override(self) -> None:
        with patch.dict(os.environ, {"COMMODITIES_BROKER_REENTRY_COOLDOWN_MINUTES": "45"}, clear=True):
            config = CommodityConfig.from_env()
        self.assertEqual(config.broker_reentry_cooldown_minutes, 45)


if __name__ == "__main__":
    unittest.main()
