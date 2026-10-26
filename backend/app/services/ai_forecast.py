"""LLM（Claude）による事前予測の作成。

研究材料として、同カテゴリの過去イベントの予測・実績・誤差・反省（検証済み/未検証を明示）、
検証済みデータの統計、直近の価格を渡す。予測時点より後の情報は渡さない。
出力は構造化出力で受け取り、通常の予測と同じ整合性チェックを通ったものだけを保存する。
"""

import json
import logging
from datetime import timedelta
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..config import REACH_THRESHOLDS, settings
from ..models import Evaluation, Event, ForecastVersion, JobRun, PriceBar, utcnow
from . import baseline
from .forecasts import ForecastRejected, create_forecast

log = logging.getLogger(__name__)
MODEL_VERSION = "prompt-v1"


class AiUnavailable(RuntimeError):
    pass


class ReachRowAI(BaseModel):
    threshold: int
    up: float
    down: float
    either: float
    both: float


class IndicatorForecastAI(BaseModel):
    code: str
    point: float
    rationale: str


class ScenarioAI(BaseModel):
    label: str
    indicator_code: str | None
    min: float | None
    max: float | None
    reaction_min: float
    reaction_max: float
    window: Literal["5m", "30m", "60m"]


class AiForecast(BaseModel):
    prob_up: float = Field(description="上昇確率(%)。prob_up+prob_down+prob_flat=100")
    prob_down: float
    prob_flat: float
    importance: int = Field(description="1-10")
    confidence: float = Field(description="予測の信頼度(%)")
    d1: float = Field(description="発表直前価格からの1分後の価格差(ドル、符号付き)")
    d5: float
    d15: float
    d30: float
    d60: float
    max_up_5m: float = Field(description="発表後5分間の最大上昇幅(ドル、0以上)")
    max_down_5m: float = Field(description="発表後5分間の最大下落幅(ドル、0以上)")
    max_excursion_5m: float = Field(description="max(max_up_5m, max_down_5m)")
    max_excursion_5m_low: float
    max_excursion_5m_high: float
    range_5m: float = Field(description="5分間の高値−安値")
    range_30m: float
    range_60m: float
    reach: list[ReachRowAI] = Field(description="10,15,20,30,50,70,100ドルの各到達確率(%)")
    initial_direction: Literal["up", "down", "flat"]
    initial_move: float = Field(description="初動の最大値幅(符号付き)")
    reversal_prob: float
    reversal_size: float
    indicator_forecasts: list[IndicatorForecastAI]
    scenarios: list[ScenarioAI] = Field(description="指標結果ごとの条件付き反応")
    rationale: str
    key_risks: list[str]


SYSTEM = """あなたはXAUUSD（金）の米国経済指標発表時の値動きを研究するアナリストです。
与えられたデータだけを根拠に、指定フォーマットで事前予測を作成してください。

厳守事項:
- 予測時点より後の情報は存在しないものとして扱う。データに無いニュース・数値・URLを作らない。
- 「検証済み」と「未検証（会話由来）」の記録を区別し、未検証の記録は参考程度にとどめる。
- 5分間の最大変動幅（max_up/max_down/max_excursion）と5分後の終着地（d5）を混同しない。
- 高値安値レンジ（range）と最大到達幅（max_excursion）を混同しない。range_30m>=range_5m、range_60m>=range_30m。
- 方向確率の合計は100。到達確率は値幅が大きいほど小さく（単調非増加）、either>=max(up,down)、both<=min(up,down)、
  either<=up+down とする。
- 指標数値の予測は、市場予想がある場合はその値との差と根拠を書く。
- 過去の反省・改善点があれば、それをどう反映したかを rationale に書く。
- 日本語で書く。"""


def _bars_snapshot(db: Session, now) -> dict:
    out = {}
    for sym in ("XAUUSD", "DXY", "US02Y", "US10Y"):
        b = db.scalar(select(PriceBar).where(PriceBar.symbol == sym, PriceBar.ts <= now,
                                             PriceBar.ts >= now - timedelta(days=3)).order_by(PriceBar.ts.desc()).limit(1))
        if b:
            out[sym] = {"close": b.close, "bar_time_utc": b.ts.isoformat(), "timeframe_min": b.timeframe_min}
    return out


def build_context(db: Session, ev: Event, now) -> dict:
    cats = set(ev.categories or [ev.category]) | {ev.category}
    past = db.scalars(select(Event).options(
        selectinload(Event.forecasts), selectinload(Event.outcomes), selectinload(Event.indicators),
        selectinload(Event.reports)).where(Event.release_at < now, Event.release_at.is_not(None))).all()
    research = []
    for p in sorted(past, key=lambda e: e.release_at, reverse=True):
        if not (cats & (set(p.categories or []) | {p.category})):
            continue
        f = p.forecasts[-1] if p.forecasts else None
        evals = db.scalars(select(Evaluation).where(Evaluation.forecast_id == f.id)).all() if f else []
        research.append({
            "title": p.title, "release_at_utc": p.release_at.isoformat(),
            "indicators": [{"name": i.name, "previous": i.previous, "consensus": i.consensus, "actual": i.actual,
                            "actual_verified": i.actual_verified} for i in p.indicators],
            "last_forecast": {k: getattr(f, k) for k in ("prob_up", "prob_down", "prob_flat", "d5", "d30",
                                                         "max_excursion_5m", "headline_move")} if f else None,
            "outcomes": [{"verified": o.verified, "kind": o.kind, "d1": o.d1, "d5": o.d5, "d30": o.d30, "d60": o.d60,
                          "max_up_5m": o.max_up_5m, "max_down_5m": o.max_down_5m, "range_5m": o.range_5m,
                          "range_60m": o.range_60m, "headline_move": o.headline_move,
                          "observations": o.observations} for o in p.outcomes],
            "evaluation_metrics": [e.metrics for e in evals][-1:],
            "lessons": [x for r in p.reports for x in (r.reflections + r.improvements)],
        })
        if len(research) >= 8:
            break
    stats = None
    samples = baseline.training_outcomes(db, ev.category, now)
    if len(samples) >= baseline.MIN_SAMPLES:
        stats = baseline.fit_predict(samples)
    prior = [{"version": f.version_no, "label": f.label, "model": f.model_name, "prob_up": f.prob_up,
              "prob_down": f.prob_down, "d5": f.d5, "max_excursion_5m": f.max_excursion_5m} for f in ev.forecasts]
    return {
        "forecast_time_utc": now.isoformat(),
        "event": {"title": ev.title, "category": ev.category, "categories": ev.categories,
                  "release_at_utc": ev.release_at.isoformat(), "importance": ev.importance, "notes": ev.notes,
                  "release_time_confirmed": ev.release_time_confirmed},
        "indicators": [{"code": i.code, "name": i.name, "unit": i.unit, "previous": i.previous,
                        "previous_revised": i.previous_revised, "consensus": i.consensus,
                        "consensus_source": i.consensus_source} for i in ev.indicators],
        "latest_prices": _bars_snapshot(db, now) or "価格データなし",
        "news": "ニュースデータは未接続（使用不可）",
        "previous_versions_for_this_event": prior,
        "research_same_category": research,
        "verified_statistics": stats or "検証済みデータ不足（統計なし）",
    }


def to_forecast_data(out: AiForecast, ctx: dict, label: str) -> dict:
    reach = {}
    for r in out.reach:
        if r.threshold in REACH_THRESHOLDS:
            reach[str(r.threshold)] = {"up": r.up, "down": r.down, "either": r.either, "both": r.both}
    return {
        "label": label,
        "market_snapshot": {"prices": ctx["latest_prices"], "info_cutoff_utc": ctx["forecast_time_utc"],
                            "research_events": [r["title"] for r in ctx["research_same_category"]]},
        **{k: getattr(out, k) for k in (
            "prob_up", "prob_down", "prob_flat", "importance", "confidence", "d1", "d5", "d15", "d30", "d60",
            "max_up_5m", "max_down_5m", "max_excursion_5m", "max_excursion_5m_low", "max_excursion_5m_high",
            "range_5m", "range_30m", "range_60m", "initial_direction", "initial_move", "reversal_prob", "reversal_size")},
        "reach_probs": reach,
        "indicator_forecasts": [x.model_dump() for x in out.indicator_forecasts],
        "scenarios": [s.model_dump() for s in out.scenarios],
        "rationale": out.rationale + ("\n\n主なリスク:\n- " + "\n- ".join(out.key_risks) if out.key_risks else ""),
    }


def generate(db: Session, ev: Event, label: str = "AI予測", client=None) -> ForecastVersion:
    if not settings.anthropic_api_key and client is None:
        raise AiUnavailable("ANTHROPIC_API_KEY が未設定のため、AI予測を作成できません。")
    now = utcnow()
    if ev.release_at is None or ev.release_at <= now:
        raise ForecastRejected(["発表前のイベントにのみ事前予測を作成できます。"])
    ctx = build_context(db, ev, now)
    if client is None:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    messages = [{"role": "user", "content": "以下のデータで事前予測を作成してください。\n" +
                 json.dumps(ctx, ensure_ascii=False, default=str)}]
    last_errors: list[str] = []
    for _ in range(2):
        resp = client.messages.parse(
            model=settings.llm_model, max_tokens=16000, system=SYSTEM, messages=messages,
            output_format=AiForecast, output_config={"effort": "high"},
            extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
            extra_body={"fallbacks": "default"},
        )
        if resp.stop_reason == "refusal":
            raise AiUnavailable("モデルが応答を拒否しました。")
        out: AiForecast | None = resp.parsed_output
        if out is None:
            raise AiUnavailable(f"構造化出力を取得できませんでした（stop_reason={resp.stop_reason}）。")
        data = to_forecast_data(out, ctx, label)
        try:
            return create_forecast(db, ev, data, source="llm", model_name=settings.llm_model, model_version=MODEL_VERSION)
        except ForecastRejected as e:
            db.rollback()
            last_errors = e.errors
            messages += [{"role": "assistant", "content": resp.content},
                         {"role": "user", "content": "整合性チェックで以下のエラーが出ました。修正した予測を再出力してください:\n- "
                          + "\n- ".join(e.errors)}]
    raise ForecastRejected(last_errors)


def auto_generate_due(db: Session, now=None) -> list[str]:
    """重要イベントの前日（発表26〜2時間前）と直前（2時間〜10分前）にAI予測を1回ずつ自動作成する。"""
    if not (settings.anthropic_api_key and settings.auto_ai_forecast):
        return []
    now = now or utcnow()
    events = db.scalars(select(Event).options(selectinload(Event.forecasts), selectinload(Event.indicators)).where(
        Event.release_at > now + timedelta(minutes=10), Event.release_at <= now + timedelta(hours=26),
        Event.importance >= settings.auto_ai_min_importance, Event.parent_id.is_(None))).all()
    made = []
    for ev in events:
        ttr = ev.release_at - now
        label = "AI前日予測" if ttr > timedelta(hours=2) else "AI直前予測"
        if any(f.source == "llm" and f.label == label for f in ev.forecasts):
            continue
        job = f"ai_forecast:{ev.id}:{label}"
        if db.scalar(select(JobRun.id).where(JobRun.job == job, JobRun.started_at >= now - timedelta(minutes=60))):
            continue  # 失敗直後に連続で再試行しない（API費用の暴走防止）
        run = JobRun(job=job)
        db.add(run)
        db.commit()
        try:
            fv = generate(db, ev, label=label)
            db.commit()
            run.status, run.message = "success", f"{ev.title}: {label} Ver.{fv.version_no}"
            made.append(run.message)
        except Exception as e:  # noqa: BLE001
            db.rollback()
            run.status, run.message = "failed", f"{ev.title}: {e}"[:2000]
            log.warning("auto AI forecast failed for %s: %s", ev.slug, e)
        run.finished_at = utcnow()
        db.add(run)
        db.commit()
    return made
