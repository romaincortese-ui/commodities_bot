from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone

from commoditiesbot.config import CommodityConfig
from commoditiesbot.models import CommoditySignal
from commoditiesbot.runtime import _execute_live_orders, _format_scan_message, _should_send_heartbeat


class FakeOandaClient:
    def __init__(self) -> None:
        self.orders: list[dict[str, object]] = []

    def account_nav(self) -> float:
        return 10000.0

    def open_positions(self) -> set[str]:
        return set()

    def place_market_order(self, instrument: str, units: float, tag: str, *, stop_loss: float | None = None, take_profit: float | None = None) -> dict[str, object]:
        self.orders.append({"instrument": instrument, "units": units, "tag": tag, "stop_loss": stop_loss, "take_profit": take_profit})
        return {"orderFillTransaction": {"id": "order-1"}}


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

    def test_heartbeat_gate_limits_routine_telegram_messages(self) -> None:
        self.assertTrue(_should_send_heartbeat({}, 1000.0, 3600))
        self.assertFalse(_should_send_heartbeat({"last_telegram_heartbeat_at": 900.0}, 1000.0, 3600))
        self.assertTrue(_should_send_heartbeat({"last_telegram_heartbeat_at": 900.0}, 4600.0, 3600))

    def test_live_config_executes_oanda_signal_with_brackets(self) -> None:
        config = replace(
            CommodityConfig.from_env(),
            paper_trade=False,
            live_trading_enabled=True,
            oanda_account_id="acct",
            oanda_api_token="token",
            max_live_orders_per_scan=1,
        )
        signal = CommoditySignal(
            symbol="WTI",
            side="LONG",
            strategy="CRUDE_INVENTORY_TREND",
            score=91.0,
            price=80.0,
            sl_price=78.0,
            tp_price=84.0,
            atr=1.0,
            expected_hold_bars=8,
            data_freshness_minutes=10.0,
            event_risk="NORMAL",
            bucket="ENERGY",
            metadata={"data_provider": "oanda", "oanda_instrument": "WTICO_USD", "time": datetime(2026, 5, 4, tzinfo=timezone.utc)},
        )
        state: dict[str, object] = {}
        client = FakeOandaClient()

        orders, errors = _execute_live_orders([signal], config, client, state)

        self.assertEqual(errors, [])
        self.assertEqual(len(orders), 1)
        self.assertEqual(client.orders[0]["instrument"], "WTICO_USD")
        self.assertGreater(client.orders[0]["units"], 0)
        self.assertEqual(client.orders[0]["stop_loss"], 78.0)
        self.assertEqual(client.orders[0]["take_profit"], 84.0)
        self.assertEqual(state["open_positions"][0]["order_id"], "order-1")


if __name__ == "__main__":
    unittest.main()