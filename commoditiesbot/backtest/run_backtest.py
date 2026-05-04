from __future__ import annotations

from commoditiesbot.backtest.data import FixtureMarketDataProvider
from commoditiesbot.backtest.engine import BacktestEngine, write_report
from commoditiesbot.config import CommodityConfig


def main() -> int:
    config = CommodityConfig.from_env()
    provider = FixtureMarketDataProvider(days=max(90, config.backtest_days + 45))
    result = BacktestEngine(config, provider).run()
    write_report(result, config.backtest_output_dir)
    print(f"data_provider={result.data_provider}")
    print(f"trades={result.total_trades} wins={result.wins} losses={result.losses} win_rate={result.win_rate:.2%}")
    print(f"pnl={result.total_pnl:.2f} return={result.return_pct:.2%} pf={result.profit_factor:.2f} max_dd={result.max_drawdown_pct:.2%}")
    print("by_bucket=" + ", ".join(f"{bucket}:{pnl:.2f}" for bucket, pnl in sorted(result.by_bucket.items())))
    return 0 if result.total_pnl > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
