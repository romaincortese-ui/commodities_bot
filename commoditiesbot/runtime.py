from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from commoditiesbot.backtest.data import FixtureMarketDataProvider
from commoditiesbot.config import CommodityConfig, SYMBOL_BUCKETS
from commoditiesbot.models import CommodityPosition, CommoditySignal
from commoditiesbot.oanda_client import OandaClient
from commoditiesbot.risk import can_open, position_from_signal
from commoditiesbot.state import StateStore
from commoditiesbot.strategies import generate_signal
from commoditiesbot.telegram import TelegramNotifier


LAST_HEARTBEAT_AT_KEY = "last_telegram_heartbeat_at"


def _side_label(side: str) -> str:
    return "🟢 LONG" if side.upper() == "LONG" else "🔴 SHORT"


def _provider_label(provider: str) -> str:
    return "📡 OANDA" if provider == "oanda" else "🧪 Fixture"


def _pretty_strategy(strategy: str) -> str:
    return strategy.replace("_", " ").title()


def _format_time(value: object) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _execution_label(config: CommodityConfig) -> str:
    if config.paper_trade:
        return "paper signals"
    if config.live_trading_enabled:
        return "live orders"
    return "signals only"


def _format_live_issue(row: dict[str, object]) -> str:
    subject = row.get("symbol") or row.get("instrument") or "unknown"
    stage = row.get("stage") or "live"
    detail = row.get("reason") or row.get("error") or "blocked"
    text = str(detail)
    if len(text) > 160:
        text = text[:157] + "..."
    return f"{subject} | {stage}: {text}"


def _signed_oanda_units(units: float, side: str) -> int:
    whole_units = int(abs(units))
    if whole_units < 1:
        return 0
    return whole_units if side.upper() == "LONG" else -whole_units


def _coerce_time(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)


def _order_id(response: dict[str, object]) -> str:
    for key in ("orderFillTransaction", "orderCreateTransaction", "orderCancelTransaction"):
        item = response.get(key)
        if isinstance(item, dict) and item.get("id"):
            return str(item["id"])
    return "live"


def _json_safe(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _account_equity(config: CommodityConfig, client: OandaClient, state: dict[str, Any]) -> float:
    if not config.paper_trade and config.has_oanda_credentials:
        try:
            equity = client.account_nav()
            if equity > 0:
                state["equity"] = equity
                return equity
        except RuntimeError as exc:
            state["last_account_nav_error"] = str(exc)
    try:
        return float(state.get("equity") or config.backtest_initial_balance)
    except (TypeError, ValueError):
        return config.backtest_initial_balance


def _position_from_state(row: dict[str, object]) -> CommodityPosition | None:
    try:
        symbol = str(row.get("symbol") or "").upper()
        return CommodityPosition(
            symbol=symbol,
            side=str(row.get("side") or "LONG").upper(),
            strategy=str(row.get("strategy") or "LIVE"),
            entry_price=float(row.get("entry_price") or 0.0),
            units=abs(float(row.get("units") or 0.0)),
            sl_price=float(row.get("sl_price") or 0.0),
            tp_price=float(row.get("tp_price") or 0.0),
            opened_at=_coerce_time(row.get("opened_at")),
            risk_amount=float(row.get("risk_amount") or 0.0),
            bucket=str(row.get("bucket") or SYMBOL_BUCKETS.get(symbol, "OTHER")),
            order_id=str(row.get("order_id") or "live"),
            metadata=dict(row.get("metadata") or {}),
        )
    except (TypeError, ValueError):
        return None


def _state_position_rows(state: dict[str, Any]) -> list[dict[str, object]]:
    rows = state.get("open_positions", [])
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _sync_open_position_rows(config: CommodityConfig, client: OandaClient, state: dict[str, Any]) -> tuple[list[dict[str, object]], set[str], list[dict[str, object]]]:
    rows = _state_position_rows(state)
    errors: list[dict[str, object]] = []
    open_instruments: set[str] = set()
    if not config.has_oanda_credentials:
        return rows, open_instruments, errors
    try:
        open_instruments = client.open_positions()
        rows = [row for row in rows if str(row.get("instrument") or "").upper() in open_instruments]
        state["open_positions"] = rows
    except RuntimeError as exc:
        errors.append({"stage": "open_positions", "error": str(exc)})
    return rows, open_instruments, errors


def _position_row(position: CommodityPosition, instrument: str, signed_units: float) -> dict[str, object]:
    return {
        "symbol": position.symbol,
        "instrument": instrument,
        "side": position.side,
        "strategy": position.strategy,
        "entry_price": position.entry_price,
        "units": position.units,
        "order_units": signed_units,
        "sl_price": position.sl_price,
        "tp_price": position.tp_price,
        "opened_at": position.opened_at.isoformat(),
        "risk_amount": position.risk_amount,
        "bucket": position.bucket,
        "order_id": position.order_id,
        "metadata": _json_safe(position.metadata),
    }


def _execute_live_orders(signals: list[CommoditySignal], config: CommodityConfig, client: OandaClient, state: dict[str, Any]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    if config.paper_trade or not config.live_trading_enabled:
        return [], []
    rows, open_instruments, errors = _sync_open_position_rows(config, client, state)
    positions = [position for position in (_position_from_state(row) for row in rows) if position is not None]
    equity = _account_equity(config, client, state)
    orders: list[dict[str, object]] = []
    for signal in signals:
        if len(orders) >= config.max_live_orders_per_scan:
            break
        if len(positions) >= config.max_open_positions or len(open_instruments) >= config.max_open_positions:
            break
        if str(signal.metadata.get("data_provider") or "") != "oanda":
            continue
        instrument = str(signal.metadata.get("oanda_instrument") or config.oanda_instrument_for(signal.symbol)).strip().upper()
        if not instrument or instrument in open_instruments:
            continue
        allowed, reason = can_open(signal, positions, equity, config)
        if not allowed:
            errors.append({"symbol": signal.symbol, "stage": "risk", "reason": reason})
            continue
        position = position_from_signal(signal, equity, config)
        if position.units <= 0:
            continue
        signed_units = _signed_oanda_units(position.units, signal.side)
        if signed_units == 0:
            errors.append({"symbol": signal.symbol, "stage": "units", "reason": "position_size_below_one_oanda_unit"})
            continue
        try:
            response = client.place_market_order(
                instrument,
                signed_units,
                f"commodities-{signal.symbol.lower()}",
                stop_loss=position.sl_price,
                take_profit=position.tp_price,
            )
        except RuntimeError as exc:
            errors.append({"symbol": signal.symbol, "instrument": instrument, "stage": "order", "error": str(exc)})
            continue
        position.order_id = _order_id(response)
        row = _position_row(position, instrument, signed_units)
        rows.append(row)
        positions.append(position)
        open_instruments.add(instrument)
        orders.append(
            {
                "symbol": signal.symbol,
                "side": signal.side,
                "instrument": instrument,
                "units": round(signed_units, 4),
                "order_id": position.order_id,
                "score": round(signal.score, 2),
            }
        )
    state["open_positions"] = rows
    state["last_live_orders"] = orders
    state["last_live_order_errors"] = errors
    return orders, errors


def _format_scan_message(snapshot: dict[str, object], config: CommodityConfig) -> str:
    counts = snapshot.get("data_provider_counts", {})
    oanda_count = int(counts.get("oanda", 0)) if isinstance(counts, dict) else 0
    fixture_count = int(counts.get("fixture", 0)) if isinstance(counts, dict) else 0
    total_count = max(oanda_count + fixture_count, len(config.universe))
    failures = snapshot.get("oanda_failures", [])
    failure_count = len(failures) if isinstance(failures, list) else 0
    execution = _execution_label(config)
    mode_icon = "🔴" if not config.paper_trade else "🧪"
    mode_text = "LIVE config" if not config.paper_trade else "PAPER"

    lines = [
        "🌾 Commodities Bot",
        f"{mode_icon} Mode: {mode_text} | Execution: {execution}",
        f"🕒 Scan: {_format_time(snapshot.get('time', ''))}",
        f"📊 Data: OANDA {oanda_count}/{total_count} | Fixture {fixture_count}/{total_count} | Instruments {snapshot.get('oanda_instrument_count', 0)}",
    ]
    if failure_count:
        failed_symbols = ", ".join(str(item).split(":", 1)[0] for item in failures[:3]) if isinstance(failures, list) else "some symbols"
        suffix = "" if failure_count <= 3 else f" +{failure_count - 3} more"
        lines.append(f"⚠️ Fallbacks: {failure_count} OANDA fetch issue(s): {failed_symbols}{suffix}")

    top_signals = snapshot.get("top_signals", [])
    if isinstance(top_signals, list) and top_signals:
        lines.append("")
        lines.append("🏆 Top Signals")
        for index, row in enumerate(top_signals[:5], start=1):
            if not isinstance(row, dict):
                continue
            provider = str(row.get("data_provider", "fixture"))
            instrument = row.get("oanda_instrument")
            instrument_text = f" | {instrument}" if provider == "oanda" and instrument else ""
            lines.append(
                f"{index}. {_side_label(str(row.get('side', '')))} {row.get('symbol', '?')} | Score {float(row.get('score', 0.0)):.1f} | {_provider_label(provider)}{instrument_text}"
            )
            lines.append(f"   ↳ {_pretty_strategy(str(row.get('strategy', '')))}")
    else:
        lines.append("😴 No qualified signals this scan.")

    live_orders = snapshot.get("live_orders", [])
    if isinstance(live_orders, list) and live_orders:
        lines.append("")
        lines.append("✅ Live Orders")
        for row in live_orders[:3]:
            if isinstance(row, dict):
                lines.append(f"{row.get('side', '?')} {row.get('symbol', '?')} | {row.get('instrument', '?')} | units {row.get('units', '?')}")

    live_errors = snapshot.get("live_order_errors", [])
    if isinstance(live_errors, list) and live_errors:
        lines.append(f"⚠️ Live order issue(s): {len(live_errors)}")
        for row in live_errors[:2]:
            if isinstance(row, dict):
                lines.append(f"   ↳ {_format_live_issue(row)}")

    return "\n".join(lines)


def _should_send_heartbeat(state: dict[str, object], now_ts: float, heartbeat_seconds: int) -> bool:
    try:
        last_sent = float(state.get(LAST_HEARTBEAT_AT_KEY, 0.0) or 0.0)
    except (TypeError, ValueError):
        last_sent = 0.0
    if last_sent <= 0.0:
        return True
    return now_ts - last_sent >= max(0, heartbeat_seconds)


def run_scan(config: CommodityConfig, client: OandaClient, state_store: StateStore, notifier: TelegramNotifier) -> dict[str, object]:
    state = state_store.load()
    instrument_count = 0
    if config.has_oanda_credentials:
        try:
            instrument_count = len(client.tradeable_instruments())
        except RuntimeError:
            instrument_count = 0

    provider = FixtureMarketDataProvider(days=max(90, config.backtest_days + 45))
    data_provider_counts = {"oanda": 0, "fixture": 0}
    oanda_failures: list[str] = []
    signals = []
    for symbol in config.universe:
        candles = []
        data_provider = "fixture"
        oanda_instrument = config.oanda_instrument_for(symbol)
        if config.has_oanda_credentials and oanda_instrument:
            try:
                candles = client.candles(oanda_instrument, count=max(90, config.backtest_days + 45), granularity="D")
            except RuntimeError as exc:
                oanda_failures.append(f"{symbol}:{exc}")
            if len(candles) >= 45:
                data_provider = "oanda"
            else:
                candles = []
        if not candles:
            candles = provider.history(symbol)
        data_provider_counts[data_provider] += 1
        signal = generate_signal(symbol, candles, config)
        if signal is not None:
            signal.metadata["data_provider"] = data_provider
            if oanda_instrument:
                signal.metadata["oanda_instrument"] = oanda_instrument
            signals.append(signal)

    signals.sort(key=lambda item: item.score, reverse=True)
    live_orders, live_order_errors = _execute_live_orders(signals, config, client, state)
    snapshot = {
        "time": datetime.now(timezone.utc).isoformat(),
        "paper_trade": config.paper_trade,
        "configured_symbols": list(config.universe),
        "oanda_instrument_count": instrument_count,
        "data_provider_counts": data_provider_counts,
        "oanda_failures": oanda_failures[:5],
        "live_orders": live_orders,
        "live_order_errors": live_order_errors[:5],
        "top_signals": [
            {
                "symbol": signal.symbol,
                "side": signal.side,
                "score": round(signal.score, 2),
                "strategy": signal.strategy,
                "data_provider": signal.metadata.get("data_provider", "fixture"),
                "oanda_instrument": signal.metadata.get("oanda_instrument", ""),
            }
            for signal in signals[:5]
        ],
    }
    message = _format_scan_message(snapshot, config)
    print(message, flush=True)
    state["last_snapshot"] = snapshot
    now_ts = time.time()
    if _should_send_heartbeat(state, now_ts, config.heartbeat_seconds):
        state[LAST_HEARTBEAT_AT_KEY] = now_ts
        state["last_telegram_heartbeat_time"] = snapshot["time"]
        notifier.send(message)
    state_store.save(state)
    return snapshot


def run_bot() -> None:
    config = CommodityConfig.from_env()
    notifier = TelegramNotifier(config.telegram_token, config.telegram_chat_id)
    state_store = StateStore(config.state_file)
    client = OandaClient(config)

    if not config.paper_trade and not config.has_oanda_credentials:
        raise RuntimeError("Live trading requested but OANDA_ACCOUNT_ID/OANDA_API_TOKEN are missing")

    while True:
        run_scan(config, client, state_store, notifier)
        if config.run_once:
            return
        time.sleep(max(30, config.scan_interval_seconds))
