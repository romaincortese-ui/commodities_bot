from __future__ import annotations

import dataclasses
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class PredictionOverlayDecision:
    allowed: bool
    reason: str
    fresh: bool = False
    event_id: str = ""
    event_title: str = ""
    favourable_probability: float = 0.5
    base_success_probability: float = 0.5
    bayesian_success_probability: float = 0.5
    kelly_fraction: float = 0.0
    size_multiplier: float = 1.0
    score_offset: float = 0.0
    state_age_seconds: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def load_prediction_state_payload(path: str | Path | None) -> Any | None:
    if path is None or str(path).strip() == "":
        return None
    file_path = Path(path)
    if not file_path.exists() or file_path.is_dir():
        return None
    return json.loads(file_path.read_text(encoding="utf-8"))


def parse_prediction_timestamp(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OSError, TypeError, ValueError):
            return None
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def select_point_in_time_prediction_state(payload: Any, now: datetime) -> dict[str, Any] | None:
    if isinstance(payload, Mapping) and not any(key in payload for key in ("timeline", "states", "events_by_time")):
        return dict(payload)
    if not isinstance(payload, (Mapping, list)):
        return None
    items = payload if isinstance(payload, list) else payload.get("timeline") or payload.get("states") or payload.get("events_by_time") or []
    if not isinstance(items, list):
        return None
    current = _utc(now)
    selected: dict[str, Any] | None = None
    for item in items:
        if not isinstance(item, Mapping):
            continue
        start = parse_prediction_timestamp(item.get("from") or item.get("start") or item.get("generated_at") or item.get("timestamp"))
        if start is None or start > current:
            continue
        end = parse_prediction_timestamp(item.get("until") or item.get("end") or item.get("expires_at"))
        if end is not None and current >= end:
            continue
        raw_state = item.get("state") if isinstance(item.get("state"), Mapping) else item
        state = dict(raw_state)
        state.setdefault("generated_at", start.isoformat())
        selected = state
    return selected


def apply_prediction_overlay(
    signal: Any,
    state: Mapping[str, Any] | None,
    now: datetime,
    *,
    enabled: bool = False,
    symbol: str | None = None,
    side: str | None = None,
    stale_seconds: int = 60,
    fallback_mode: str = "neutral",
    min_favourable_probability: float = 0.5,
    min_posterior: float = 0.5,
    event_given_success: float = 0.6,
    kelly_base_fraction: float = 0.04,
    max_size_multiplier: float = 1.0,
    score_scale: float = 20.0,
) -> Any | None:
    decision = evaluate_prediction_overlay(
        signal,
        state,
        now,
        enabled=enabled,
        symbol=symbol,
        side=side,
        stale_seconds=stale_seconds,
        fallback_mode=fallback_mode,
        min_favourable_probability=min_favourable_probability,
        min_posterior=min_posterior,
        event_given_success=event_given_success,
        kelly_base_fraction=kelly_base_fraction,
        max_size_multiplier=max_size_multiplier,
        score_scale=score_scale,
    )
    if not decision.allowed:
        return None
    if not decision.fresh or decision.reason in {"disabled", "neutral_fallback", "no_relevant_prediction_event"}:
        return signal
    return _replace_signal(signal, decision)


def evaluate_prediction_overlay(
    signal: Any,
    state: Mapping[str, Any] | None,
    now: datetime,
    *,
    enabled: bool = False,
    symbol: str | None = None,
    side: str | None = None,
    stale_seconds: int = 60,
    fallback_mode: str = "neutral",
    min_favourable_probability: float = 0.5,
    min_posterior: float = 0.5,
    event_given_success: float = 0.6,
    kelly_base_fraction: float = 0.04,
    max_size_multiplier: float = 1.0,
    score_scale: float = 20.0,
) -> PredictionOverlayDecision:
    if not enabled:
        return PredictionOverlayDecision(True, "disabled")
    fresh, age = _is_state_fresh(state, now, stale_seconds)
    if not fresh or not isinstance(state, Mapping):
        if str(fallback_mode or "neutral").strip().lower() in {"abort", "block", "halt"}:
            return PredictionOverlayDecision(False, "stale_prediction_state", state_age_seconds=age)
        return PredictionOverlayDecision(True, "neutral_fallback", state_age_seconds=age)

    trade_symbol = symbol or _signal_value(signal, ("symbol", "canonical", "instrument", "pair"))
    trade_side = side or _signal_value(signal, ("side", "direction"))
    event = _select_relevant_event(state, trade_symbol, trade_side)
    if event is None:
        return PredictionOverlayDecision(True, "no_relevant_prediction_event", fresh=True, state_age_seconds=age)

    probability = _extract_probability(event)
    if probability is None:
        return PredictionOverlayDecision(True, "prediction_event_missing_probability", fresh=True, state_age_seconds=age)
    favourable_side = _event_favourable_side(event)
    favourable_probability = _favourable_probability(probability, favourable_side, trade_side)
    base_success = _base_success_probability(signal)
    posterior = _bayesian_success_probability(
        base_success=base_success,
        event_probability=max(0.01, favourable_probability),
        event_given_success=_clamp_probability(event.get("event_given_success") or event_given_success),
    )
    reward_risk = _reward_risk(signal)
    kelly = max(0.0, favourable_probability - ((1.0 - favourable_probability) / max(0.01, reward_risk)))
    size_multiplier = max(0.0, min(max_size_multiplier, kelly / max(0.001, kelly_base_fraction)))
    score_offset = (posterior - base_success) * max(0.0, score_scale)
    reason = "prediction_overlay_pass"
    allowed = True
    if favourable_probability < min_favourable_probability:
        allowed = False
        reason = "prediction_unfavourable_probability"
    elif posterior < min_posterior:
        allowed = False
        reason = "prediction_low_bayesian_success"
    elif kelly <= 0.0 or size_multiplier <= 0.0:
        allowed = False
        reason = "prediction_nonpositive_kelly"
    metadata = {
        "prediction_overlay": 1.0,
        "prediction_reason": reason,
        "prediction_event_id": str(event.get("event_id") or event.get("id") or event.get("slug") or ""),
        "prediction_event_title": str(event.get("title") or event.get("question") or event.get("name") or ""),
        "prediction_favourable_probability": round(favourable_probability, 4),
        "prediction_base_success_probability": round(base_success, 4),
        "prediction_bayesian_success_probability": round(posterior, 4),
        "prediction_kelly_fraction": round(kelly, 6),
        "prediction_size_multiplier": round(size_multiplier if allowed else 0.0, 4),
        "prediction_reward_risk": round(reward_risk, 4),
    }
    if age is not None:
        metadata["prediction_state_age_seconds"] = round(age, 1)
    return PredictionOverlayDecision(
        allowed,
        reason,
        fresh=True,
        event_id=str(metadata["prediction_event_id"]),
        event_title=str(metadata["prediction_event_title"]),
        favourable_probability=favourable_probability,
        base_success_probability=base_success,
        bayesian_success_probability=posterior,
        kelly_fraction=kelly,
        size_multiplier=size_multiplier if allowed else 0.0,
        score_offset=score_offset if allowed else 0.0,
        state_age_seconds=age,
        metadata=metadata,
    )


def prediction_size_multiplier(metadata: Mapping[str, Any] | None) -> float:
    if not isinstance(metadata, Mapping):
        return 1.0
    return max(0.0, min(1.0, _optional_float(metadata.get("prediction_size_multiplier")) or 1.0))


def _is_state_fresh(state: Mapping[str, Any] | None, now: datetime, stale_seconds: int) -> tuple[bool, float | None]:
    if not isinstance(state, Mapping):
        return False, None
    generated_at = parse_prediction_timestamp(state.get("generated_at") or state.get("as_of") or state.get("updated_at") or state.get("timestamp"))
    if generated_at is None:
        return False, None
    age = (_utc(now) - generated_at).total_seconds()
    ttl = _optional_float(state.get("ttl_seconds") or state.get("stale_after_seconds")) or float(stale_seconds)
    return 0.0 <= age <= max(1.0, ttl), max(0.0, age)


def _select_relevant_event(state: Mapping[str, Any], symbol: str, side: str) -> dict[str, Any] | None:
    symbol_key = _normalize_symbol(symbol)
    side_key = _canonical_side(side)
    best: tuple[float, dict[str, Any]] | None = None
    for event in _raw_events(state):
        event_side = _event_favourable_side(event)
        if not event_side:
            continue
        relevance = _event_relevance(event, symbol_key)
        if relevance <= 0.0:
            continue
        probability = _extract_probability(event)
        if probability is None:
            continue
        favourable = _favourable_probability(probability, event_side, side_key)
        edge = abs(favourable - 0.5) * relevance
        if best is None or edge > best[0]:
            best = (edge, dict(event))
    return best[1] if best else None


def _raw_events(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = state.get("events") or state.get("predictions") or state.get("markets") or []
    if isinstance(raw, Mapping):
        raw = list(raw.values())
    return [dict(item) for item in raw if isinstance(item, Mapping)]


def _event_relevance(event: Mapping[str, Any], symbol_key: str) -> float:
    raw_symbols = event.get("symbols") or event.get("symbol") or event.get("instruments") or event.get("instrument") or []
    if isinstance(raw_symbols, str):
        raw_symbols = [raw_symbols]
    symbols = {_normalize_symbol(item) for item in raw_symbols if str(item).strip()}
    if symbols:
        return 1.2 if symbol_key in symbols else 0.0
    scope = str(event.get("scope") or "").strip().lower()
    return 1.0 if scope in {"", "global", "macro", "market", "all"} else 0.0


def _event_favourable_side(event: Mapping[str, Any]) -> str:
    raw = str(event.get("favourable_side") or event.get("favorable_side") or event.get("trade_side") or event.get("side") or event.get("direction") or event.get("bias") or "").lower()
    if raw in {"long", "buy", "bullish", "risk_on", "positive", "up"}:
        return "LONG"
    if raw in {"short", "sell", "bearish", "risk_off", "negative", "down"}:
        return "SHORT"
    return ""


def _extract_probability(event: Mapping[str, Any]) -> float | None:
    for key in ("primary_probability", "probability", "implied_probability", "yes_probability", "yes_price", "price", "last_price"):
        parsed = _optional_float(event.get(key))
        if parsed is not None:
            return _clamp_probability(parsed)
    no_price = _optional_float(event.get("no_price") or event.get("no_probability"))
    return 1.0 - _clamp_probability(no_price) if no_price is not None else None


def _replace_signal(signal: Any, decision: PredictionOverlayDecision) -> Any:
    if isinstance(signal, dict):
        updated = dict(signal)
        metadata = dict(updated.get("metadata") or {})
        metadata.update(decision.metadata)
        metadata["risk_multiplier"] = round((_optional_float(metadata.get("risk_multiplier")) or 1.0) * decision.size_multiplier, 4)
        updated["metadata"] = metadata
        updated["score"] = round(max(0.0, float(updated.get("score", 0.0) or 0.0) + decision.score_offset), 2)
        if "selection_score" in updated:
            updated["selection_score"] = round(max(0.0, float(updated.get("selection_score", 0.0) or 0.0) + decision.score_offset), 2)
        return updated
    if not dataclasses.is_dataclass(signal):
        return signal
    fields = {field.name for field in dataclasses.fields(signal)}
    changes: dict[str, Any] = {}
    if "metadata" in fields:
        metadata = dict(getattr(signal, "metadata", None) or {})
        metadata.update(decision.metadata)
        metadata["risk_multiplier"] = round((_optional_float(metadata.get("risk_multiplier")) or 1.0) * decision.size_multiplier, 4)
        changes["metadata"] = metadata
    if "score" in fields:
        changes["score"] = round(max(0.0, float(getattr(signal, "score", 0.0) or 0.0) + decision.score_offset), 2)
    if "risk_multiplier" in fields:
        changes["risk_multiplier"] = max(0.0, float(getattr(signal, "risk_multiplier", 1.0) or 1.0) * decision.size_multiplier)
    return dataclasses.replace(signal, **changes) if changes else signal


def _signal_value(signal: Any, names: tuple[str, ...]) -> str:
    if isinstance(signal, Mapping):
        for name in names:
            value = signal.get(name)
            if value not in (None, ""):
                return str(value)
    for name in names:
        value = getattr(signal, name, None)
        if value not in (None, ""):
            return str(value)
    return ""


def _base_success_probability(signal: Any) -> float:
    metadata = dict(signal.get("metadata") or {}) if isinstance(signal, Mapping) else dict(getattr(signal, "metadata", None) or {})
    for key in ("prediction_base_win_rate", "historical_win_rate", "calibration_win_rate", "win_rate"):
        parsed = _optional_float(metadata.get(key))
        if parsed is not None:
            return _clamp_probability(parsed)
    return 0.5


def _reward_risk(signal: Any) -> float:
    value = _optional_float(_get(signal, "risk_reward"))
    if value is not None and value > 0:
        return value
    entry = _optional_float(_get(signal, "entry_price") or _get(signal, "price")) or 0.0
    stop = _optional_float(_get(signal, "stop_price") or _get(signal, "sl_price")) or 0.0
    target = _optional_float(_get(signal, "take_profit_price") or _get(signal, "tp_price")) or 0.0
    if entry > 0 and stop > 0 and target > 0:
        return max(0.01, abs(target - entry) / max(abs(entry - stop), 0.0001))
    tp_pips = _optional_float(_get(signal, "tp_pips")) or 0.0
    sl_pips = _optional_float(_get(signal, "sl_pips")) or 0.0
    return max(0.01, tp_pips / sl_pips) if tp_pips > 0 and sl_pips > 0 else 1.0


def _get(signal: Any, name: str) -> Any:
    return signal.get(name) if isinstance(signal, Mapping) else getattr(signal, name, None)


def _bayesian_success_probability(*, base_success: float, event_probability: float, event_given_success: float) -> float:
    return _clamp_probability(_clamp_probability(event_given_success) * _clamp_probability(base_success) / max(0.01, _clamp_probability(event_probability)))


def _favourable_probability(probability: float, event_side: str, trade_side: str) -> float:
    event_key = _canonical_side(event_side)
    trade_key = _canonical_side(trade_side)
    return probability if not event_key or not trade_key or event_key == trade_key else 1.0 - probability


def _canonical_side(value: str) -> str:
    text = str(value or "").strip().lower()
    if text in {"long", "buy", "bullish", "up"}:
        return "LONG"
    if text in {"short", "sell", "bearish", "down"}:
        return "SHORT"
    return ""


def _normalize_symbol(value: Any) -> str:
    return "".join(ch for ch in str(value).upper() if ch.isalnum())


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _optional_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _clamp_probability(value: Any) -> float:
    parsed = _optional_float(value)
    if parsed is None:
        return 0.5
    if parsed > 1.0 and parsed <= 100.0:
        parsed /= 100.0
    return max(0.0, min(1.0, parsed))