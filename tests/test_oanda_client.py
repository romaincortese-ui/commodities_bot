from __future__ import annotations

import unittest

from commoditiesbot.config import CommodityConfig
from commoditiesbot.oanda_client import OandaClient


class FakeOandaClient(OandaClient):
    def __init__(self, payload: dict[str, object]) -> None:
        super().__init__(CommodityConfig.from_env())
        self.payload = payload

    def _request(self, method: str, path: str, payload: dict[str, object] | None = None) -> dict[str, object]:
        return self.payload


class OandaClientTests(unittest.TestCase):
    def test_instrument_tradeable_accepts_tradeable_pricing_with_bid_ask(self) -> None:
        client = FakeOandaClient(
            {
                "prices": [
                    {
                        "instrument": "CORN_USD",
                        "status": "tradeable",
                        "tradeable": True,
                        "bids": [{"price": "4.66900"}],
                        "asks": [{"price": "4.67100"}],
                    }
                ]
            }
        )

        self.assertEqual(client.instrument_tradeable("CORN_USD"), (True, "tradeable"))

    def test_instrument_tradeable_blocks_non_tradeable_pricing(self) -> None:
        client = FakeOandaClient(
            {
                "prices": [
                    {
                        "instrument": "CORN_USD",
                        "status": "non-tradeable",
                        "tradeable": False,
                        "bids": [],
                        "asks": [],
                    }
                ]
            }
        )

        self.assertEqual(client.instrument_tradeable("CORN_USD"), (False, "pricing_status_non_tradeable"))


if __name__ == "__main__":
    unittest.main()