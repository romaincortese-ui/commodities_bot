from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone

from commoditiesbot.config import CommodityConfig
from commoditiesbot.models import CommoditySignal
from commoditiesbot.runtime import _apply_profit_protection, _execute_live_orders, _format_boot_message, _format_scan_message, _poll_telegram_commands, _send_trade_lifecycle_alerts, _should_send_heartbeat


class FakeOandaClient:
    def __init__(self) -> None:
        self.orders: list[dict[str, object]] = []
        self.tradeable = True
        self.open_position_symbols: set[str] = set()
        self.open_trade_rows: list[dict[str, object]] = []
        self.closed_trades: list[str] = []
        self.bid = 79.99
        self.ask = 80.0
        self.order_response: dict[str, object] = {"orderFillTransaction": {"id": "fill-1", "price": "80.125", "tradeOpened": {"tradeID": "trade-1"}}}

    def account_nav(self) -> float:
        return 10000.0

    def account_available_balance(self) -> float:
        return 9876.54

    def open_positions(self) -> set[str]:
        return set(self.open_position_symbols)

    def open_trades(self) -> list[dict[str, object]]:
        if self.open_trade_rows:
            return list(self.open_trade_rows)
        return [
            {
                "id": "trade-1",
                "instrument": instrument,
                "price": "80.0",
                "currentUnits": "12.5",
                "openTime": "2026-05-04T17:00:00Z",
                "initialMarginRequired": "35.0",
                "unrealizedPL": "0.0",
                "stopLossOrder": {"price": "78.0"},
                "takeProfitOrder": {"price": "84.0"},
            }
            for instrument in sorted(self.open_position_symbols)
        ]

    def instrument_tradeable(self, instrument: str) -> tuple[bool, str]:
        return self.tradeable, "tradeable" if self.tradeable else "pricing_status_non_tradeable"

    def current_bid_ask(self, instrument: str) -> tuple[float, float]:
        return self.bid, self.ask

    def place_market_order(self, instrument: str, units: float, tag: str, *, stop_loss: float | None = None, take_profit: float | None = None) -> dict[str, object]:
        self.orders.append({"instrument": instrument, "units": units, "tag": tag, "stop_loss": stop_loss, "take_profit": take_profit})
        return self.order_response

    def close_trade(self, trade_id: str) -> dict[str, object]:
        self.closed_trades.append(trade_id)
        return {"orderFillTransaction": {"tradeClosed": {"tradeID": trade_id}}}


class FakeNotifier:
    def __init__(self, updates: list[dict[str, object]] | None = None, chat_id: str = "chat") -> None:
        self.chat_id = chat_id
        self.updates = updates or []
        self.update_offsets: list[int] = []
        self.messages: list[tuple[str, str | None]] = []

    @property
    def enabled(self) -> bool:
        return True

    def send(self, message: str, parse_mode: str | None = None) -> None:
        self.messages.append((message, parse_mode))

    def get_updates(self, offset: int, timeout: int = 1) -> list[dict[str, object]]:
        self.update_offsets.append(offset)
        return self.updates


class FakeStateStore:
    def __init__(self, state: dict[str, object]) -> None:
        self.state = state
        self.saved: list[dict[str, object]] = []

    def load(self) -> dict[str, object]:
        return self.state

    def save(self, state: dict[str, object]) -> None:
        self.state = state
        self.saved.append(dict(state))


def _live_config() -> CommodityConfig:
    return replace(
        CommodityConfig.from_env(),
        paper_trade=False,
        live_trading_enabled=True,
        oanda_account_id="acct",
        oanda_api_token="token",
        max_live_orders_per_scan=1,
    )


def _oanda_signal() -> CommoditySignal:
    return CommoditySignal(
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


class RuntimeMessageTests(unittest.TestCase):
    def test_scan_message_is_clear_and_visual(self) -> None:
        config = CommodityConfig.from_env()
        snapshot = {
            "time": "2026-05-04T17:15:00+00:00",
            "data_provider_counts": {"oanda": 7, "fixture": 5},
            "oanda_instrument_count": 123,
            "oanda_failures": ["COFFEE:OANDA request failed"],
            "available_balance": 9876.54,
            "open_positions": [
                {
                    "symbol": "SUGAR",
                    "side": "LONG",
                    "entry_budget": 100.0,
                    "unrealized_pl": 12.5,
                    "current_value": 112.5,
                }
            ],
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
        self.assertIn("💷 Total P&L: +12.50% | +£12.50", message)
        self.assertIn("💰 Available Balance: £9876.54", message)
        self.assertIn("🟢 SUGAR LONG", message)
        self.assertNotIn("🏆 Top Signals", message)
        self.assertNotIn("BRENT", message)

    def test_heartbeat_gate_limits_routine_telegram_messages(self) -> None:
        self.assertTrue(_should_send_heartbeat({}, 1000.0, 3600))
        self.assertFalse(_should_send_heartbeat({"last_telegram_heartbeat_at": 900.0}, 1000.0, 3600))
        self.assertTrue(_should_send_heartbeat({"last_telegram_heartbeat_at": 900.0}, 4600.0, 3600))

    def test_boot_message_confirms_activation(self) -> None:
        config = replace(
            CommodityConfig.from_env(),
            paper_trade=False,
            live_trading_enabled=True,
            universe=("WTI", "BRENT"),
            scan_interval_seconds=300,
            heartbeat_seconds=3600,
        )
        state = {"open_positions": [{"instrument": "WTICO_USD"}]}

        message = _format_boot_message(config, state, datetime(2026, 5, 5, 19, 0, tzinfo=timezone.utc))

        self.assertIn("<b>Commodities Bot Boot</b>", message)
        self.assertIn("Mode: 🔴 LIVE config | Execution: live orders", message)
        self.assertIn("Universe: 2 symbols", message)
        self.assertIn("Open positions after OANDA sync: 1", message)
        self.assertIn("Started: 2026-05-05 19:00 UTC", message)

    def test_status_command_replies_to_authorized_chat(self) -> None:
        config = _live_config()
        state: dict[str, object] = {
            "last_snapshot": {
                "time": "2026-05-05T19:00:00+00:00",
                "data_provider_counts": {"oanda": 1, "fixture": 1},
                "top_signals": [{"symbol": "WTI", "side": "LONG", "score": 91.0, "data_provider": "oanda"}],
            },
            "open_positions": [
                {
                    "symbol": "WTI",
                    "instrument": "WTICO_USD",
                    "side": "LONG",
                    "strategy": "CRUDE_INVENTORY_TREND",
                    "entry_price": 80.0,
                    "units": 12.5,
                    "sl_price": 78.0,
                    "tp_price": 84.0,
                    "opened_at": "2026-05-04T17:00:00+00:00",
                    "risk_amount": 35.0,
                    "bucket": "ENERGY",
                    "order_id": "trade-1",
                    "metadata": {},
                }
            ],
        }
        client = FakeOandaClient()
        client.open_position_symbols = {"WTICO_USD"}
        notifier = FakeNotifier(
            updates=[{"update_id": 42, "message": {"text": "/status", "chat": {"id": "chat"}}}],
            chat_id="chat",
        )
        state_store = FakeStateStore(state)

        _poll_telegram_commands(config, client, state_store, notifier)

        self.assertEqual(notifier.update_offsets, [1])
        self.assertEqual(state_store.state["last_telegram_update_id"], 42)
        self.assertEqual(len(notifier.messages), 1)
        message, parse_mode = notifier.messages[0]
        self.assertEqual(parse_mode, "HTML")
        self.assertIn("<b>Commodities Status</b>", message)
        self.assertIn("Open positions: 1", message)
        self.assertIn("Top signal: LONG WTI", message)

    def test_status_command_ignores_other_chats(self) -> None:
        config = _live_config()
        notifier = FakeNotifier(
            updates=[{"update_id": 9, "message": {"text": "/status", "chat": {"id": "other"}}}],
            chat_id="chat",
        )
        state_store = FakeStateStore({})

        _poll_telegram_commands(config, FakeOandaClient(), state_store, notifier)

        self.assertEqual(notifier.messages, [])
        self.assertEqual(state_store.state["last_telegram_update_id"], 9)

    def test_live_config_executes_oanda_signal_with_brackets(self) -> None:
        config = _live_config()
        signal = _oanda_signal()
        state: dict[str, object] = {}
        client = FakeOandaClient()

        orders, errors = _execute_live_orders([signal], config, client, state)

        self.assertEqual(errors, [])
        self.assertEqual(len(orders), 1)
        self.assertEqual(client.orders[0]["instrument"], "WTICO_USD")
        self.assertGreater(client.orders[0]["units"], 0)
        self.assertEqual(client.orders[0]["stop_loss"], 78.0)
        self.assertEqual(client.orders[0]["take_profit"], 84.0)
        self.assertEqual(state["open_positions"][0]["order_id"], "trade-1")
        self.assertEqual(state["open_positions"][0]["entry_price"], 80.125)

    def test_live_config_requires_oanda_fill_before_recording_order(self) -> None:
        config = _live_config()
        signal = _oanda_signal()
        state: dict[str, object] = {}
        client = FakeOandaClient()
        client.order_response = {"orderCancelTransaction": {"id": "cancel-1", "reason": "STOP_LOSS_ON_FILL_LOSS"}}

        orders, errors = _execute_live_orders([signal], config, client, state)

        self.assertEqual(orders, [])
        self.assertEqual(state["open_positions"], [])
        self.assertEqual(errors[0]["stage"], "order")
        self.assertEqual(errors[0]["reason"], "STOP_LOSS_ON_FILL_LOSS")

    def test_live_config_recenters_brackets_on_current_quote(self) -> None:
        config = _live_config()
        signal = _oanda_signal()
        state: dict[str, object] = {}
        client = FakeOandaClient()
        client.bid = 74.9
        client.ask = 75.0

        orders, errors = _execute_live_orders([signal], config, client, state)

        self.assertEqual(errors, [])
        self.assertEqual(len(orders), 1)
        self.assertEqual(client.orders[0]["stop_loss"], 73.0)
        self.assertEqual(client.orders[0]["take_profit"], 79.0)

    def test_live_order_alert_matches_forex_lifecycle_style(self) -> None:
        config = _live_config()
        signal = _oanda_signal()
        state: dict[str, object] = {}
        client = FakeOandaClient()
        notifier = FakeNotifier()

        orders, errors = _execute_live_orders([signal], config, client, state)
        _send_trade_lifecycle_alerts(notifier, orders, [])

        self.assertEqual(errors, [])
        self.assertEqual(len(notifier.messages), 1)
        message, parse_mode = notifier.messages[0]
        self.assertEqual(parse_mode, "HTML")
        self.assertIn("<b>TRADE OPENED</b>", message)
        self.assertIn("🟢 WTI LONG", message)
        self.assertIn("Entry Budget:", message)
        self.assertIn("P&L: +0.00%", message)

    def test_profit_protection_closes_after_peak_pullback(self) -> None:
        config = replace(_live_config(), profit_lock_trigger_pct=15.0, profit_lock_pullback_pct=2.0)
        state: dict[str, object] = {
            "open_positions": [
                {
                    "symbol": "WTI",
                    "instrument": "WTICO_USD",
                    "side": "LONG",
                    "entry_price": 80.0,
                    "units": 10.0,
                    "sl_price": 78.0,
                    "entry_budget": 100.0,
                    "unrealized_pl": 37.0,
                    "order_id": "trade-1",
                    "metadata": {"peak_pnl_pct": 39.0},
                }
            ]
        }
        client = FakeOandaClient()

        updates, errors = _apply_profit_protection(config, client, state)

        self.assertEqual(errors, [])
        self.assertEqual(len(updates), 1)
        self.assertEqual(client.closed_trades, ["trade-1"])
        self.assertEqual(state["open_positions"], [])
        self.assertAlmostEqual(float(updates[0]["peak_pnl_pct"]), 39.0, places=4)
        self.assertAlmostEqual(float(updates[0]["pullback_from_peak_pct"]), 2.0, places=4)

    def test_profit_protection_records_new_peak_without_closing(self) -> None:
        config = replace(_live_config(), profit_lock_trigger_pct=15.0, profit_lock_pullback_pct=2.0)
        state: dict[str, object] = {
            "open_positions": [
                {
                    "symbol": "WTI",
                    "instrument": "WTICO_USD",
                    "side": "LONG",
                    "entry_price": 80.0,
                    "units": 10.0,
                    "entry_budget": 100.0,
                    "unrealized_pl": 39.0,
                    "order_id": "trade-1",
                    "metadata": {"peak_pnl_pct": 37.0},
                }
            ]
        }
        client = FakeOandaClient()

        updates, errors = _apply_profit_protection(config, client, state)

        self.assertEqual(errors, [])
        self.assertEqual(updates, [])
        self.assertEqual(client.closed_trades, [])
        self.assertAlmostEqual(float(state["open_positions"][0]["metadata"]["peak_pnl_pct"]), 39.0, places=4)

    def test_closed_oanda_position_generates_broker_close_alert(self) -> None:
        config = _live_config()
        state: dict[str, object] = {
            "open_positions": [
                {
                    "symbol": "WTI",
                    "instrument": "WTICO_USD",
                    "side": "LONG",
                    "strategy": "CRUDE_INVENTORY_TREND",
                    "entry_price": 80.0,
                    "units": 12.5,
                    "sl_price": 78.0,
                    "tp_price": 84.0,
                    "opened_at": "2026-05-04T17:00:00+00:00",
                    "risk_amount": 35.0,
                    "bucket": "ENERGY",
                    "order_id": "trade-1",
                    "metadata": {},
                }
            ]
        }
        client = FakeOandaClient()
        notifier = FakeNotifier()

        orders, errors = _execute_live_orders([], config, client, state)
        _send_trade_lifecycle_alerts(notifier, orders, state["last_closed_positions"])

        self.assertEqual(orders, [])
        self.assertEqual(errors, [])
        self.assertEqual(state["open_positions"], [])
        self.assertEqual(len(notifier.messages), 1)
        message, parse_mode = notifier.messages[0]
        self.assertEqual(parse_mode, "HTML")
        self.assertIn("<b>Crude Inventory Trend Closed at broker</b> | WTI", message)
        self.assertIn("Exit: broker reported closed", message)
        self.assertIn("Reason: OANDA position no longer open", message)

    def test_live_config_skips_order_when_oanda_market_is_not_tradeable(self) -> None:
        config = _live_config()
        signal = _oanda_signal()
        state: dict[str, object] = {}
        client = FakeOandaClient()
        client.tradeable = False

        orders, errors = _execute_live_orders([signal], config, client, state)

        self.assertEqual(orders, [])
        self.assertEqual(client.orders, [])
        self.assertEqual(errors[0]["stage"], "market")
        self.assertEqual(errors[0]["instrument"], "WTICO_USD")
        self.assertIn("non_tradeable", str(errors[0]["reason"]))


if __name__ == "__main__":
    unittest.main()