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


if __name__ == "__main__":
    unittest.main()
