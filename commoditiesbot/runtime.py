from __future__ import annotations

import time
from datetime import datetime, timezone

from commoditiesbot.backtest.data import FixtureMarketDataProvider
from commoditiesbot.config import CommodityConfig
from commoditiesbot.oanda_client import OandaClient
from commoditiesbot.state import StateStore
from commoditiesbot.strategies import generate_signal
from commoditiesbot.telegram import TelegramNotifier


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
            }
            for signal in signals[:5]
        ],
    }
    state["last_snapshot"] = snapshot
    state_store.save(state)

    message = "Commodities bot scan complete\n" + "\n".join(
        f"{row['symbol']} {row['side']} score={row['score']} {row['strategy']}" for row in snapshot["top_signals"]
    )
    print(message)
    notifier.send(message)
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
