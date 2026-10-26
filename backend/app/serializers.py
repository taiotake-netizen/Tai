from sqlalchemy import inspect as sa_inspect

from .models import Event, EventStatus, ForecastVersion, Indicator, Outcome, ResearchReport

STATUS_JA = {
    EventStatus.UPCOMING: "今後",
    EventStatus.FORECASTED: "事前予測済み",
    EventStatus.AWAITING_DATA: "発表済み・データ待ち",
    EventStatus.VERIFYING: "検証中",
    EventStatus.VERIFIED: "検証完了",
    EventStatus.HISTORICAL_UNVERIFIED: "過去・未検証",
}


def _cols(obj) -> dict:
    return {c.key: getattr(obj, c.key) for c in sa_inspect(obj).mapper.column_attrs}


def indicator(i: Indicator) -> dict:
    return _cols(i)


def forecast(f: ForecastVersion) -> dict:
    return _cols(f)


def outcome(o: Outcome) -> dict:
    d = _cols(o)
    d["reversed"] = d.pop("reversed_")
    return d


def report(r: ResearchReport) -> dict:
    return _cols(r)


def event_summary(e: Event) -> dict:
    d = {k: getattr(e, k) for k in (
        "id", "slug", "title", "category", "categories", "release_at", "release_time_confirmed",
        "date_label", "importance", "status", "is_composite", "parent_id", "cluster", "origin", "notes",
    )}
    d["status_ja"] = STATUS_JA.get(e.status, e.status)
    d["indicators"] = [indicator(i) for i in e.indicators]
    latest = e.forecasts[-1] if e.forecasts else None
    d["forecast_count"] = len(e.forecasts)
    d["latest_forecast"] = forecast(latest) if latest else None
    oc = next((o for o in e.outcomes if o.kind == "price_bars" and o.base_price is not None), None) or (
        e.outcomes[0] if e.outcomes else None)
    d["outcome"] = outcome(oc) if oc else None
    rep = next((r for r in reversed(e.reports) if r.generated_by != "conversation_import"), None)
    conv = next((r for r in e.reports if r.generated_by == "conversation_import"), None)
    d["report"] = report(rep) if rep else None
    d["conversation_report"] = report(conv) if conv else None
    return d
