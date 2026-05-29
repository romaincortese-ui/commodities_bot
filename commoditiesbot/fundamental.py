"""Fundamental data providers: EIA, USDA WASDE calendar, NOAA HDD, FRED USD.

Each function returns a float bias in a documented range (typically -3.0 to +3.0).
Positive bias = bullish signal adjustment; negative = bearish.

All network calls are cached for 6 hours and degrade gracefully to 0.0 on any
error (missing key, network failure, unexpected API shape).  The backtest uses
fixture candles and no API keys, so every function returns 0.0 there.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import date, timedelta

# ---------------------------------------------------------------------------
# In-process cache: key -> (float value, expiry unix timestamp)
# ---------------------------------------------------------------------------
_CACHE: dict[str, tuple[float, float]] = {}
_CACHE_TTL = 6 * 3600  # 6 hours


def _cached(key: str, fn, *args: object) -> float:
    now = time.monotonic()
    if key in _CACHE:
        value, expiry = _CACHE[key]
        if now < expiry:
            return value
    try:
        value = float(fn(*args))
    except Exception:
        value = 0.0
    _CACHE[key] = (value, now + _CACHE_TTL)
    return value


def _get_json(url: str, headers: dict[str, str] | None = None) -> object:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=12) as resp:
        return json.loads(resp.read().decode())


# ---------------------------------------------------------------------------
# EIA: Natural gas underground storage (weekly, Lower 48 states)
# ---------------------------------------------------------------------------
def _eia_rows(api_key: str, route: str, series: str, count: int) -> list[float]:
    """Return up to `count` weekly values (most recent first) for an EIA series."""
    url = (
        f"https://api.eia.gov/v2/{route}/data/"
        f"?api_key={api_key}"
        f"&frequency=weekly"
        f"&data[0]=value"
        f"&facets[series][]={series}"
        f"&sort[0][column]=period"
        f"&sort[0][direction]=desc"
        f"&length={count}"
    )
    data = _get_json(url)
    rows = data.get("response", {}).get("data", []) if isinstance(data, dict) else []  # type: ignore[union-attr]
    values: list[float] = []
    for row in rows:
        raw = row.get("value") if isinstance(row, dict) else None
        if raw not in (None, "", "null", "."):
            try:
                values.append(float(raw))
            except (TypeError, ValueError):
                pass
    return values


def _eia_natgas_storage_bias_live(api_key: str) -> float:
    """
    Compare current Lower-48 underground natgas storage (Bcf) to the same week
    one year ago.  Excess supply is bearish; deficit is bullish.

    Bias range: -3.0 (heavily oversupplied) … +3.0 (heavily undersupplied).
    """
    # Need 54 weeks: current + 52-week lag + 1 buffer
    vals = _eia_rows(api_key, "natural-gas/stor/wkly", "NW2_EPG0_SWO_R48_BCF", 55)
    if len(vals) < 53:
        return 0.0
    current = vals[0]
    year_ago = vals[52]
    if year_ago <= 0:
        return 0.0
    diff_pct = (current - year_ago) / year_ago
    # ±10% vs year-ago maps to ∓2.0 bias
    bias = -diff_pct * 20.0
    return max(-3.0, min(3.0, bias))


def natgas_storage_bias(eia_api_key: str) -> float:
    """Return EIA natgas storage year-on-year bias for NATGAS signal.  0.0 if no key."""
    if not eia_api_key:
        return 0.0
    return _cached("eia_natgas", _eia_natgas_storage_bias_live, eia_api_key)


# ---------------------------------------------------------------------------
# EIA: US crude oil stocks (weekly, WCRSTUS1 = crude excluding SPR)
# ---------------------------------------------------------------------------
def _eia_crude_inventory_bias_live(api_key: str) -> float:
    """
    Compare current US crude oil inventories to year-ago.
    Excess stocks = bearish (lower price), deficit = bullish.

    Bias range: -2.0 … +2.0.
    """
    vals = _eia_rows(api_key, "petroleum/stoc/wstk", "WCRSTUS1", 55)
    if len(vals) < 53:
        return 0.0
    current = vals[0]
    year_ago = vals[52]
    if year_ago <= 0:
        return 0.0
    diff_pct = (current - year_ago) / year_ago
    # ±10% vs year-ago maps to ∓2.0 bias
    bias = -diff_pct * 20.0
    return max(-2.0, min(2.0, bias))


def crude_inventory_bias(eia_api_key: str) -> float:
    """Return EIA crude inventory year-on-year bias for WTI/BRENT signals.  0.0 if no key."""
    if not eia_api_key:
        return 0.0
    return _cached("eia_crude", _eia_crude_inventory_bias_live, eia_api_key)


# ---------------------------------------------------------------------------
# EIA: US Heating Degree Days (population-weighted, weekly)
# Used as a NATGAS demand proxy: above-normal HDD = bullish.
# ---------------------------------------------------------------------------
def _eia_hdd_bias_live(api_key: str) -> float:
    """
    Compare most recent week's US HDD (EIA series ZWHDPUS) to the trailing
    8-week average as a simple seasonal proxy.

    Bias range: -2.0 … +2.0.
    """
    # Route: total-energy, series ZWHDPUS (US HDD population-weighted)
    vals = _eia_rows(api_key, "total-energy", "ZWHDPUS", 10)
    if len(vals) < 4:
        return 0.0
    recent = vals[0]
    baseline = sum(vals[1:]) / max(len(vals) - 1, 1)
    if baseline <= 0:
        return 0.0
    diff_pct = (recent - baseline) / baseline
    # ±30% above/below 8-week trailing average maps to ±2.0 bias
    bias = diff_pct * 6.5
    return max(-2.0, min(2.0, bias))


def hdd_natgas_demand_bias(eia_api_key: str) -> float:
    """
    Return EIA HDD demand bias for NATGAS.  Positive = higher demand than recent
    average (bullish).  0.0 if EIA key absent or API unavailable.
    """
    if not eia_api_key:
        return 0.0
    return _cached("eia_hdd", _eia_hdd_bias_live, eia_api_key)


# ---------------------------------------------------------------------------
# USDA WASDE: blackout calendar for grain entries
# ---------------------------------------------------------------------------
def _nth_tuesday(year: int, month: int, n: int = 2) -> date:
    """Return the nth Tuesday of a given month."""
    d = date(year, month, 1)
    days_to_first_tue = (1 - d.weekday()) % 7
    return d + timedelta(days=days_to_first_tue + (n - 1) * 7)


def is_wasde_blackout(reference: date | None = None) -> bool:
    """
    Return True if today (or `reference`) falls within the WASDE blackout window.

    USDA WASDE is typically released on the 10th-12th of each month.  Block new
    grain entries in the 2 days before and 1 day after to avoid entering ahead
    of potentially large supply/demand revisions.
    """
    today = reference or date.today()
    # Check current month and the previous month (handles month-boundary wraps)
    for delta_months in (0, -1):
        m = today.month + delta_months
        y = today.year
        if m <= 0:
            m += 12
            y -= 1
        wasde_day = _nth_tuesday(y, m, n=2)
        window_start = wasde_day - timedelta(days=2)
        window_end = wasde_day + timedelta(days=1)
        if window_start <= today <= window_end:
            return True
    return False


# ---------------------------------------------------------------------------
# NOAA CDO: Heating/Cooling Degree Days via Climate Data Online API
# ---------------------------------------------------------------------------
def _noaa_hdd_bias_live(noaa_token: str) -> float:
    """
    Fetch recent HDD from NOAA CDO for Chicago O'Hare (a well-observed US
    inland station representative of heating demand).  Compare to seasonal norm.

    Bias range: -2.0 … +2.0.
    """
    today = date.today()
    end_date = today - timedelta(days=7)
    start_date = end_date - timedelta(days=13)
    url = (
        f"https://www.ncei.noaa.gov/cdo-web/api/v2/data"
        f"?datasetid=GHCND"
        f"&stationid=GHCND:USW00094846"  # Chicago O'Hare
        f"&datatypeid=HDD"
        f"&startdate={start_date}"
        f"&enddate={end_date}"
        f"&limit=30"
        f"&units=standard"
    )
    data = _get_json(url, headers={"token": noaa_token})
    results = data.get("results", []) if isinstance(data, dict) else []  # type: ignore[union-attr]
    if not results:
        return 0.0
    avg_hdd = sum(float(r["value"]) for r in results if isinstance(r, dict) and "value" in r) / max(len(results), 1)
    # Monthly seasonal HDD norms for Chicago (approximate)
    month = today.month
    seasonal_norms = [22, 19, 14, 6, 1, 0, 0, 0, 1, 7, 14, 20]
    norm = seasonal_norms[month - 1]
    if norm <= 0 and avg_hdd <= 0:
        return 0.0
    diff = avg_hdd - norm
    # Each degree-day above norm maps to ~0.07 bullish bias
    bias = diff * 0.07
    return max(-2.0, min(2.0, bias))


def noaa_hdd_natgas_bias(noaa_token: str) -> float:
    """Return NOAA HDD demand bias for NATGAS.  0.0 if no token or API error."""
    if not noaa_token:
        return 0.0
    return _cached("noaa_hdd", _noaa_hdd_bias_live, noaa_token)


# ---------------------------------------------------------------------------
# FRED: US Trade-Weighted Dollar Index (DTWEXBGS)
# Rising USD is broadly bearish for USD-denominated commodities.
# ---------------------------------------------------------------------------
def _fred_dollar_bias_live(fred_api_key: str) -> float:
    """
    Compute 20-day trend in the Fed's Broad Trade-Weighted USD Index.
    Rising dollar → negative commodity bias.

    Bias range: -1.5 … +1.5.
    """
    url = (
        f"https://api.stlouisfed.org/fred/series/observations"
        f"?series_id=DTWEXBGS"
        f"&api_key={fred_api_key}"
        f"&file_type=json"
        f"&sort_order=desc"
        f"&limit=30"
    )
    data = _get_json(url)
    obs = data.get("observations", []) if isinstance(data, dict) else []  # type: ignore[union-attr]
    vals: list[float] = []
    for o in obs:
        raw = o.get("value") if isinstance(o, dict) else None
        if raw not in (None, ".", ""):
            try:
                vals.append(float(raw))
            except (TypeError, ValueError):
                pass
    if len(vals) < 5:
        return 0.0
    recent = vals[0]
    # Use 20-day lag (or whatever is available)
    older = vals[min(19, len(vals) - 1)]
    if older <= 0:
        return 0.0
    trend_pct = (recent - older) / older
    # +2% USD appreciation over 20 days → -1.5 commodity bias
    bias = -trend_pct * 75.0
    return max(-1.5, min(1.5, bias))


def dollar_bias(fred_api_key: str) -> float:
    """Return broad USD trend bias (negative = USD rising = commodity headwind).  0.0 if no key."""
    if not fred_api_key:
        return 0.0
    return _cached("fred_dollar", _fred_dollar_bias_live, fred_api_key)
