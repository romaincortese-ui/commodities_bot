# Commodities Bot

Natural-commodities trading bot scaffold for an OANDA sub-account. The first build is paper-first and operator-ready: it can deploy to Railway without secrets, run deterministic 30-day validation backtests, and switch to OANDA practice/live execution once the operator adds OANDA and Telegram credentials.

## What It Trades

The configured universe is intentionally focused on natural commodities:

- Energy: `WTI`, `BRENT`, `NATGAS`, `GASOLINE`, `HEATING_OIL`
- Grains/oilseeds: `CORN`, `WHEAT`, `SOYBEANS`
- Softs: `SUGAR`, `COFFEE`, `COCOA`, `COTTON`

Every symbol routes through a commodity-specific strategy sleeve. Energy trades inventory/weather/trend confirmation, grains trade crop-stage/weather trend confirmation, and softs trade higher-timeframe weather/supply trend continuation. The MVP uses deterministic event/weather proxy fields until live data keys are added.

## Quick Start

```bash
python -m commoditiesbot.backtest.run_backtest
python bot.py
```

The runtime stays in paper mode unless `PAPER_TRADE=false` and valid OANDA credentials are present.

## Railway Variables

Copy `.env.example` into Railway variables. The operator only needs to fill:

- `OANDA_ACCOUNT_ID`
- `OANDA_API_TOKEN`
- `TELEGRAM_TOKEN`
- `TELEGRAM_CHAT_ID`

Optional data keys can be added later for richer event/weather inputs: `EIA_API_KEY`, `USDA_NASS_API_KEY`, `NOAA_CDO_TOKEN`, `FRED_API_KEY`.

The runtime uses OANDA daily candles when credentials are present for mapped symbols (`WTICO_USD`, `BCO_USD`, `NATGAS_USD`, grains, and softs). `GASOLINE` and `HEATING_OIL` stay on fixture data unless the operator sets `OANDA_INSTRUMENT_GASOLINE` and `OANDA_INSTRUMENT_HEATING_OIL` to tradeable OANDA instruments for the account.

## Deployment

`railway.toml` uses the same pattern as the live bots:

```toml
[build]
builder = "NIXPACKS"

[deploy]
startCommand = "python bot.py"
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 5
```

Mount a Railway volume at `/data` before live trading so runtime state survives restarts.

## Backtest Standard

The default 30-day validation backtest uses built-in deterministic fixture data because broker credentials are not available during CI/deployment setup. The backtest report clearly records `data_provider=fixture`. Once OANDA credentials are configured, set `BACKTEST_DATA_PROVIDER=oanda` to pull broker candles for mapped symbols and fall back to fixtures for unmapped products.

Live go/no-go should require:

- positive 30-day PnL after costs
- no open-risk cap violations
- no single bucket dominating PnL
- 30 calendar days of paper trading with OANDA practice credentials

## Live Profit Protection

Live OANDA positions track their best unrealized P&L in runtime state after every open-trade sync. By default, `PROFIT_LOCK_TRIGGER_PCT=3.0` arms the lock once a trade has been at least 3% profitable, and `PROFIT_LOCK_PULLBACK_PCT=1.5` closes the trade at market if it gives back 1.5 percentage points from that peak. The close still fires if the pullback happens quickly enough to move the trade below breakeven before the next scan.

Broker-sync closures are reconciled against recent OANDA close transactions when available, so Telegram can show the broker reason and realized P&L instead of only saying the position is no longer open. If OANDA cannot confirm a profitable take-profit close, the bot pauses fresh entries for that symbol for `COMMODITIES_BROKER_REENTRY_COOLDOWN_MINUTES` minutes to avoid closing and reopening the same setup in the same scan.

The default risk sizing multiplier is `RISK_AMOUNT_MULTIPLIER=1.35`; portfolio and bucket caps still apply before any live order is sent.
