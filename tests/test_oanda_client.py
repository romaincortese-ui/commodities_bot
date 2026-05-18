from __future__ import annotations

import unittest
from dataclasses import replace

from commoditiesbot.config import CommodityConfig
import commoditiesbot.oanda_client as oanda_module
from commoditiesbot.oanda_client import OandaClient


class FakeOandaClient(OandaClient):
    def __init__(self, payload: dict[str, object]) -> None:
        super().__init__(CommodityConfig.from_env())
        self.payload = payload
        self.requests: list[tuple[str, str, dict[str, object] | None]] = []

    def _request(self, method: str, path: str, payload: dict[str, object] | None = None) -> dict[str, object]:
        self.requests.append((method, path, payload))
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

    def test_close_trade_requests_full_trade_close(self) -> None:
        client = FakeOandaClient({"ok": True})

        client.close_trade("159")

        method, path, payload = client.requests[-1]
        self.assertEqual(method, "PUT")
        self.assertEqual(path, "/v3/accounts//trades/159/close")
        self.assertEqual(payload, {"units": "ALL"})

    def test_candles_can_include_incomplete_current_bar(self) -> None:
        client = FakeOandaClient(
            {
                "candles": [
                    {"complete": True, "time": "2026-05-14T21:00:00Z", "mid": {"o": "4.40", "h": "4.50", "l": "4.35", "c": "4.46"}, "volume": 100},
                    {"complete": False, "time": "2026-05-17T21:00:00Z", "mid": {"o": "4.46", "h": "4.70", "l": "4.45", "c": "4.67"}, "volume": 50},
                ]
            }
        )

        complete_only = client.candles("CORN_USD")
        with_current = client.candles("CORN_USD", include_incomplete=True)

        self.assertEqual(len(complete_only), 1)
        self.assertEqual(len(with_current), 2)
        self.assertEqual(with_current[-1].close, 4.67)

    def test_request_wraps_read_timeout_as_runtime_error(self) -> None:
        config = replace(CommodityConfig.from_env(), oanda_account_id="acct", oanda_api_token="token")
        client = OandaClient(config)

        def raise_timeout(*args, **kwargs):
            raise TimeoutError("The read operation timed out")

        original_urlopen = oanda_module.urlopen
        oanda_module.urlopen = raise_timeout
        try:
            with self.assertRaisesRegex(RuntimeError, "OANDA request timed out"):
                client._request("GET", "/v3/accounts/acct/summary")
        finally:
            oanda_module.urlopen = original_urlopen


if __name__ == "__main__":
    unittest.main()