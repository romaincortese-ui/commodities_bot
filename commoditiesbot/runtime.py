from __future__ import annotations

from datetime import datetime, timezone

from commoditiesbot.backtest.data import FixtureMarketDataProvider
from commoditiesbot.config import CommodityConfig
from commoditiesbot.oanda_client import OandaClient
from commoditiesbot.state import StateStore
from commoditiesbot.strategies import generate_signal
from commoditiesbot.telegram import TelegramNotifier


def run_bot() -> None:
    config = CommodityConfig.from_env()
    notifier = TelegramNotifier(config.telegram_token, config.telegram_chat_id)
    state_store = StateStore(config.state_file)
    state = state_store.load()
    client = OandaClient(config)

    if not config.paper_trade and not config.has_oanda_credentials:
        raise RuntimeError("Live trading requested but OANDA_ACCOUNT_ID/OANDA_API_TOKEN are missing")

    instrument_count = 0
    if config.has_oanda_credentials:
        try:
            instrument_count = len(client.tradeable_instruments())
        except RuntimeError:
            instrument_count = 0

    provider = FixtureMarketDataProvider(days=max(90, config.backtest_days + 45))
    signals = []
    for symbol in config.universe:
        candles = provider.history(symbol)
        signal = generate_signal(symbol, candles, config)
        if signal is not None:
            signals.append(signal)

    signals.sort(key=lambda item: item.score, reverse=True)
    snapshot = {
        "time": datetime.now(timezone.utc).isoformat(),
        "paper_trade": config.paper_trade,
        "configured_symbols": list(config.universe),
        "oanda_instrument_count": instrument_count,
        "top_signals": [
            {"symbol": signal.symbol, "side": signal.side, "score": round(signal.score, 2), "strategy": signal.strategy}
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
