"""The risk floor may never dominate the risk model.

Live evidence this guards against: with RISK_AMOUNT_FLOOR=12.5 on a ~£30
account, WTI (-£9.36) and Brent (-£9.18) were opened 3.5 hours apart on
2026-05-29 and together account for 59% of ALL gross losses across 61 trades.
The floor resolved to £12.50 = 41.7% risk per trade, and max_open_positions=2
made the book 83%.
"""
import pytest

from commoditiesbot.config import CommodityConfig
from commoditiesbot.models import CommoditySignal
from commoditiesbot.risk import position_from_signal


def _signal(symbol="SUGAR", bucket="SOFTS", price=100.0, sl=97.0, score=82.0):
    return CommoditySignal(
        symbol=symbol, side="LONG", strategy="TEST", score=score, price=price,
        sl_price=sl, tp_price=price + 6.0, atr=2.0, expected_hold_bars=8,
        data_freshness_minutes=1.0, event_risk="LOW", bucket=bucket, metadata={},
    )


@pytest.fixture
def cfg():
    return CommodityConfig.from_env()


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for k in ("RISK_AMOUNT_FLOOR", "RISK_AMOUNT_FLOOR_MAX_PCT",
              "RISK_AMOUNT_MULTIPLIER", "NOTIONAL_CAP_MULT", "NATGAS_RISK_PENALTY"):
        monkeypatch.delenv(k, raising=False)


def test_the_live_configuration_no_longer_risks_42pc_of_the_account(monkeypatch, cfg):
    # Exactly what was set on Railway when the two crude trades ran.
    monkeypatch.setenv("RISK_AMOUNT_FLOOR", "12.5")
    pos = position_from_signal(_signal(), equity=30.0, config=cfg)
    assert pos.risk_amount <= 30.0 * 0.02 + 1e-9, "floor still dominating the risk model"
    assert pos.risk_amount < 1.0


def test_floor_is_capped_at_two_percent_of_equity_by_default(monkeypatch, cfg):
    monkeypatch.setenv("RISK_AMOUNT_FLOOR", "1000")     # absurd on purpose
    for equity in (30.0, 200.0, 5000.0):
        pos = position_from_signal(_signal(), equity=equity, config=cfg)
        assert pos.risk_amount <= equity * 0.02 + 1e-9, equity


def test_floor_cap_is_tunable_but_still_bounded(monkeypatch, cfg):
    monkeypatch.setenv("RISK_AMOUNT_FLOOR", "1000")
    monkeypatch.setenv("RISK_AMOUNT_FLOOR_MAX_PCT", "0.05")
    pos = position_from_signal(_signal(), equity=100.0, config=cfg)
    assert pos.risk_amount == pytest.approx(5.0)


def test_floor_off_by_default_leaves_the_model_untouched(cfg):
    # No env var set: risk must come from risk_pct_for_signal alone.
    pos = position_from_signal(_signal(), equity=1000.0, config=cfg)
    assert 0.0 < pos.risk_amount < 1000.0 * 0.01


def test_floor_can_still_lift_a_genuinely_tiny_risk(monkeypatch, cfg):
    # Its legitimate purpose survives: on a large account a small floor still
    # raises a sub-floor risk, it just cannot exceed the cap.
    # Model risk here is ~£5.31 (0.53% of £1000), so the floor must exceed that
    # to bind at all, while staying under the 2% cap (£20).
    monkeypatch.setenv("RISK_AMOUNT_FLOOR", "15.0")
    pos = position_from_signal(_signal(), equity=1000.0, config=cfg)
    assert pos.risk_amount == pytest.approx(15.0)


def test_two_concurrent_positions_cannot_exceed_the_book(monkeypatch, cfg):
    monkeypatch.setenv("RISK_AMOUNT_FLOOR", "12.5")
    equity = 30.0
    a = position_from_signal(_signal("SUGAR", "SOFTS"), equity=equity, config=cfg)
    b = position_from_signal(_signal("SOYBEANS", "GRAINS"), equity=equity, config=cfg)
    # Previously 12.5 + 12.5 = 83% of a £30 account.
    assert (a.risk_amount + b.risk_amount) < equity * 0.05
