# Implementation Review

This repo implements the first production-shaped slice of the natural commodities bot assessment.

The design follows the assessment's main conclusion: reuse the live bots' deployment shape, but keep the strategy layer commodity-specific. The MVP includes OANDA-ready runtime hooks, Telegram notifications, persistent state, bucket risk caps, deterministic event/weather proxies, a fixture-backed backtester, and a Railway-compatible entrypoint.

Important scope decisions:

- The bot starts in paper mode and refuses live orders without OANDA credentials.
- The default backtest uses deterministic fixture data because no OANDA credentials are available during setup.
- EIA/USDA/NOAA/FRED keys are optional placeholders in this MVP; strategy metadata is structured so those feeds can replace deterministic proxies without changing the runtime contract.
- Live OANDA instrument discovery is implemented as a client method, but the runtime remains safe if credentials are missing.
