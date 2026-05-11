from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


DEFAULT_UNIVERSE = (
    "WTI",
    "BRENT",
    "NATGAS",
    "GASOLINE",
    "HEATING_OIL",
    "CORN",
    "WHEAT",
    "SOYBEANS",
    "SUGAR",
    "COFFEE",
    "COCOA",
    "COTTON",
)

DEFAULT_STRATEGIES = ("CRUDE", "NATGAS", "PRODUCTS", "CORN", "WHEAT", "SOYBEANS", "SOFTS")

SYMBOL_BUCKETS = {
    "WTI": "ENERGY",
    "BRENT": "ENERGY",
    "NATGAS": "ENERGY",
    "GASOLINE": "ENERGY",
    "HEATING_OIL": "ENERGY",
    "CORN": "GRAINS",
    "WHEAT": "GRAINS",
    "SOYBEANS": "GRAINS",
    "SUGAR": "SOFTS",
    "COFFEE": "SOFTS",
    "COCOA": "SOFTS",
    "COTTON": "SOFTS",
}

YAHOO_SYMBOLS = {
    "WTI": "CL=F",
    "BRENT": "BZ=F",
    "NATGAS": "NG=F",
    "GASOLINE": "RB=F",
    "HEATING_OIL": "HO=F",
    "CORN": "ZC=F",
    "WHEAT": "ZW=F",
    "SOYBEANS": "ZS=F",
    "SUGAR": "SB=F",
    "COFFEE": "KC=F",
    "COCOA": "CC=F",
    "COTTON": "CT=F",
}

OANDA_INSTRUMENTS = {
    "WTI": "WTICO_USD",
    "BRENT": "BCO_USD",
    "NATGAS": "NATGAS_USD",
    "CORN": "CORN_USD",
    "WHEAT": "WHEAT_USD",
    "SOYBEANS": "SOYBN_USD",
    "SUGAR": "SUGAR_USD",
    "COFFEE": "COFFEE_USD",
    "COCOA": "COCOA_USD",
    "COTTON": "COTTON_USD",
}

BASE_PRICES = {
    "WTI": 78.0,
    "BRENT": 82.0,
    "NATGAS": 3.1,
    "GASOLINE": 2.35,
    "HEATING_OIL": 2.55,
    "CORN": 460.0,
    "WHEAT": 610.0,
    "SOYBEANS": 1180.0,
    "SUGAR": 22.5,
    "COFFEE": 230.0,
    "COCOA": 8600.0,
    "COTTON": 82.0,
}


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.environ.get(name)
    if not raw:
        return default
    values = tuple(part.strip().upper() for part in re.split(r"[,\s]+", raw) if part.strip())
    return values or default


@dataclass(slots=True)
class CommodityConfig:
    oanda_env: str
    oanda_account_id: str
    oanda_api_token: str
    paper_trade: bool
    live_trading_enabled: bool
    state_file: Path
    universe: tuple[str, ...]
    strategies: tuple[str, ...]
    oanda_instruments: dict[str, str]
    scan_interval_seconds: int
    heartbeat_seconds: int
    max_open_positions: int
    max_live_orders_per_scan: int
    max_total_risk_pct: float
    energy_bucket_risk_pct: float
    grains_bucket_risk_pct: float
    softs_bucket_risk_pct: float
    daily_loss_halt_pct: float
    rolling_dd_throttle_pct: float
    rolling_dd_halt_pct: float
    profit_lock_enabled: bool
    profit_lock_trigger_pct: float
    profit_lock_pullback_pct: float
    backtest_initial_balance: float
    backtest_days: int
    backtest_data_provider: str
    backtest_output_dir: Path
    telegram_token: str
    telegram_chat_id: str
    eia_api_key: str
    usda_nass_api_key: str
    noaa_cdo_token: str
    fred_api_key: str
    run_once: bool

    @classmethod
    def from_env(cls) -> "CommodityConfig":
        paper_trade = _bool("PAPER_TRADE", True)
        return cls(
            oanda_env=os.environ.get("OANDA_ENV", "practice").strip().lower(),
            oanda_account_id=os.environ.get("OANDA_ACCOUNT_ID", "").strip(),
            oanda_api_token=os.environ.get("OANDA_API_TOKEN", "").strip(),
            paper_trade=paper_trade,
            live_trading_enabled=_bool("LIVE_TRADING_ENABLED", not paper_trade),
            state_file=Path(os.environ.get("COMMODITIES_STATE_FILE", "runtime_state.json")),
            universe=_csv("COMMODITIES_UNIVERSE", DEFAULT_UNIVERSE),
            strategies=_csv("COMMODITIES_STRATEGIES", DEFAULT_STRATEGIES),
            oanda_instruments={
                symbol: os.environ.get(f"OANDA_INSTRUMENT_{symbol}", OANDA_INSTRUMENTS.get(symbol, "")).strip().upper()
                for symbol in DEFAULT_UNIVERSE
            },
            scan_interval_seconds=_int("SCAN_INTERVAL_SECONDS", 300),
            heartbeat_seconds=_int("COMMODITIES_HEARTBEAT_SECONDS", _int("HEARTBEAT_SECONDS", 21600)),
            max_open_positions=_int("MAX_OPEN_POSITIONS", 4),
            max_live_orders_per_scan=_int("MAX_LIVE_ORDERS_PER_SCAN", 1),
            max_total_risk_pct=_float("MAX_TOTAL_RISK_PCT", 0.030),
            energy_bucket_risk_pct=_float("ENERGY_BUCKET_RISK_PCT", 0.0125),
            grains_bucket_risk_pct=_float("GRAINS_BUCKET_RISK_PCT", 0.0100),
            softs_bucket_risk_pct=_float("SOFTS_BUCKET_RISK_PCT", 0.0075),
            daily_loss_halt_pct=_float("DAILY_LOSS_HALT_PCT", 0.015),
            rolling_dd_throttle_pct=_float("ROLLING_DD_THROTTLE_PCT", 0.050),
            rolling_dd_halt_pct=_float("ROLLING_DD_HALT_PCT", 0.090),
            profit_lock_enabled=_bool("PROFIT_LOCK_ENABLED", True),
            profit_lock_trigger_pct=_float("PROFIT_LOCK_TRIGGER_PCT", 15.0),
            profit_lock_pullback_pct=_float("PROFIT_LOCK_PULLBACK_PCT", 2.0),
            backtest_initial_balance=_float("BACKTEST_INITIAL_BALANCE", 10000.0),
            backtest_days=_int("BACKTEST_DAYS", 30),
            backtest_data_provider=os.environ.get("BACKTEST_DATA_PROVIDER", "fixture").strip().lower(),
            backtest_output_dir=Path(os.environ.get("BACKTEST_OUTPUT_DIR", "backtest_output")),
            telegram_token=os.environ.get("TELEGRAM_TOKEN", "").strip(),
            telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID", "").strip(),
            eia_api_key=os.environ.get("EIA_API_KEY", "").strip(),
            usda_nass_api_key=os.environ.get("USDA_NASS_API_KEY", "").strip(),
            noaa_cdo_token=os.environ.get("NOAA_CDO_TOKEN", "").strip(),
            fred_api_key=os.environ.get("FRED_API_KEY", "").strip(),
            run_once=_bool("RUN_ONCE", False),
        )

    @property
    def oanda_base_url(self) -> str:
        if self.oanda_env == "live":
            return "https://api-fxtrade.oanda.com"
        return "https://api-fxpractice.oanda.com"

    @property
    def has_oanda_credentials(self) -> bool:
        return bool(self.oanda_account_id and self.oanda_api_token)

    def oanda_instrument_for(self, symbol: str) -> str:
        return self.oanda_instruments.get(symbol.upper(), "")

    def bucket_cap(self, bucket: str) -> float:
        if bucket == "ENERGY":
            return self.energy_bucket_risk_pct
        if bucket == "GRAINS":
            return self.grains_bucket_risk_pct
        if bucket == "SOFTS":
            return self.softs_bucket_risk_pct
        return min(self.energy_bucket_risk_pct, self.grains_bucket_risk_pct, self.softs_bucket_risk_pct)
