from __future__ import annotations

import time
from datetime import datetime, timezone

from commoditiesbot.backtest.data import FixtureMarketDataProvider
from commoditiesbot.config import CommodityConfig
from commoditiesbot.oanda_client import OandaClient
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


def _format_scan_message(snapshot: dict[str, object], config: CommodityConfig) -> str:
    counts = snapshot.get("data_provider_counts", {})
    oanda_count = int(counts.get("oanda", 0)) if isinstance(counts, dict) else 0
    fixture_count = int(counts.get("fixture", 0)) if isinstance(counts, dict) else 0
    total_count = max(oanda_count + fixture_count, len(config.universe))
    failures = snapshot.get("oanda_failures", [])
    failure_count = len(failures) if isinstance(failures, list) else 0
    execution = "signals only" if not config.paper_trade else "paper signals"
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
    snapshot = {
        "time": datetime.now(timezone.utc).isoformat(),
        "paper_trade": config.paper_trade,
        "configured_symbols": list(config.universe),
        "oanda_instrument_count": instrument_count,
        "data_provider_counts": data_provider_counts,
        "oanda_failures": oanda_failures[:5],
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
