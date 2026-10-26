from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Event, EventStatus, ForecastVersion, utcnow
from .validation import derive_dominant, validate_forecast

FIELDS = [
    "label", "as_of", "as_of_label", "market_snapshot", "news_used", "indicator_forecasts",
    "prob_up", "prob_down", "prob_flat", "dominant_direction", "importance", "confidence",
    "d1", "d5", "d15", "d30", "d60", "headline_move", "max_up_5m", "max_down_5m", "max_excursion_5m",
    "max_excursion_5m_low", "max_excursion_5m_high", "range_5m", "range_30m", "range_60m",
    "reach_probs", "initial_direction", "initial_move", "reversal_prob", "reversal_size",
    "scenarios", "extras", "phase_analysis", "rationale", "change_summary",
]

COMPARE_FIELDS = [
    "prob_up", "prob_down", "prob_flat", "d1", "d5", "d15", "d30", "d60", "headline_move",
    "max_excursion_5m", "range_5m", "range_30m", "range_60m",
]


class ForecastRejected(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def auto_change_summary(prev: ForecastVersion | None, data: dict) -> str | None:
    if prev is None:
        return None
    diffs = []
    for k in COMPARE_FIELDS:
        a, b = getattr(prev, k), data.get(k)
        if a != b and not (a is None and b is None):
            diffs.append(f"{k}: {a if a is not None else '—'} → {b if b is not None else '—'}")
    return "前バージョンからの変更: " + ", ".join(diffs) if diffs else "数値の変更なし"


def create_forecast(
    db: Session, event: Event, data: dict, *, source: str, model_name: str, model_version: str,
    validation_now: datetime | None = None,
) -> ForecastVersion:
    """新しい予測バージョンを追加する（既存バージョンは変更しない）。"""
    now = utcnow()
    errors, warnings = validate_forecast(data, event.release_at, validation_now or now)
    if errors:
        raise ForecastRejected(errors)
    next_no = (db.scalar(select(func.max(ForecastVersion.version_no)).where(ForecastVersion.event_id == event.id)) or 0) + 1
    prev = event.forecasts[-1] if event.forecasts else None
    payload = {k: data.get(k) for k in FIELDS if k in data}
    payload["dominant_direction"] = derive_dominant(data)
    if not payload.get("change_summary"):
        payload["change_summary"] = auto_change_summary(prev, data)
    for k, default in (("market_snapshot", {}), ("news_used", []), ("indicator_forecasts", []),
                       ("reach_probs", {}), ("scenarios", []), ("extras", []), ("phase_analysis", {})):
        payload[k] = payload.get(k) or default
    payload["label"] = payload.get("label") or f"Ver.{next_no}"
    fv = ForecastVersion(
        event_id=event.id, version_no=next_no, source=source, model_name=model_name,
        model_version=model_version, warnings=warnings, created_at=now, **payload,
    )
    db.add(fv)
    event.forecasts.append(fv)
    if event.status == EventStatus.UPCOMING:
        event.status = EventStatus.FORECASTED
    db.flush()
    return fv
