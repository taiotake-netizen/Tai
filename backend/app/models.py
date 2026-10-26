"""データモデル。

設計方針:
- 事前予測(ForecastVersion)は不変。新しい予測は必ず新バージョンとして追加する。
- 実績(Outcome)は「会話由来の暫定記録」と「価格データから算出した実績」を別レコードで保持し、混同しない。
- 経済指標の数値(Indicator)はイベント（価格変動の単位）に複数ぶら下がる。GDP+PCEのような同時発表は
  1イベント・複数指標として扱う。
"""

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EventStatus:
    UPCOMING = "upcoming"
    FORECASTED = "forecasted"
    AWAITING_DATA = "awaiting_data"
    VERIFYING = "verifying"
    VERIFIED = "verified"
    HISTORICAL_UNVERIFIED = "historical_unverified"

    FUTURE = {UPCOMING, FORECASTED}
    ALL = [UPCOMING, FORECASTED, AWAITING_DATA, VERIFYING, VERIFIED, HISTORICAL_UNVERIFIED]


CATEGORIES = [
    "FOMC", "FOMC_MINUTES", "FED_SPEECH", "CPI", "NFP", "GDP", "PCE", "ADP", "ISM",
    "RETAIL_SALES", "JOLTS", "JOBLESS_CLAIMS", "ECI", "DURABLE_GOODS", "NEW_HOME_SALES",
    "CONSUMER_CONFIDENCE", "OTHER",
]


class Event(Base):
    """価格変動を分析する単位となる発表イベント（複合イベントを含む）。"""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(40), index=True)
    # 複合イベントでは主カテゴリ以外もここに入れる（例: ["GDP","PCE"]）
    categories: Mapped[list] = mapped_column(JSON, default=list)
    release_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    release_time_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    date_label: Mapped[str | None] = mapped_column(String(120))  # 会話記録上の日付表記など
    importance: Mapped[int] = mapped_column(Integer, default=5)  # 1-10
    status: Mapped[str] = mapped_column(String(30), default=EventStatus.UPCOMING, index=True)
    is_composite: Mapped[bool] = mapped_column(Boolean, default=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("events.id"))
    cluster: Mapped[str | None] = mapped_column(String(120))  # 同日の関連イベント群
    origin: Mapped[str] = mapped_column(String(40), default="manual")  # conversation|manual|api
    notes: Mapped[str | None] = mapped_column(Text)
    # 発表スケジュールの根拠 [{"name","url"}]
    schedule_sources: Mapped[list] = mapped_column(JSON, default=list)
    schedule_rev: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    indicators: Mapped[list["Indicator"]] = relationship(
        back_populates="event", cascade="all, delete-orphan", order_by="Indicator.sort_order"
    )
    forecasts: Mapped[list["ForecastVersion"]] = relationship(
        back_populates="event", order_by="ForecastVersion.version_no"
    )
    outcomes: Mapped[list["Outcome"]] = relationship(back_populates="event", order_by="Outcome.id")
    reports: Mapped[list["ResearchReport"]] = relationship(
        back_populates="event", order_by="ResearchReport.id"
    )
    children: Mapped[list["Event"]] = relationship(back_populates="parent")
    parent: Mapped["Event | None"] = relationship(back_populates="children", remote_side=[id])


class Indicator(Base):
    """経済指標の数値（個別管理）。"""

    __tablename__ = "indicators"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    code: Mapped[str] = mapped_column(String(60))  # 例: NFP, UNRATE, CORE_PCE_MOM
    name: Mapped[str] = mapped_column(String(120))
    unit: Mapped[str] = mapped_column(String(30), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    previous: Mapped[float | None] = mapped_column(Float)
    previous_revised: Mapped[float | None] = mapped_column(Float)
    consensus: Mapped[float | None] = mapped_column(Float)
    consensus_source: Mapped[str | None] = mapped_column(String(200))
    actual: Mapped[float | None] = mapped_column(Float)
    actual_source: Mapped[str | None] = mapped_column(String(300))
    # 公式データと照合済みか。会話由来の値は False のまま。
    actual_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    actual_recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)

    event: Mapped[Event] = relationship(back_populates="indicators")

    __table_args__ = (UniqueConstraint("event_id", "code"),)


class ForecastVersion(Base):
    """事前予測の1バージョン（不変）。"""

    __tablename__ = "forecast_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(60), default="")  # 初回/中間/前日/直前/最新 等
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # 予測が作られた時点（会話記録では日付のみ/不明のことがある）
    as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    as_of_label: Mapped[str | None] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(String(40))  # chatgpt_conversation|manual|baseline_stat|llm
    model_name: Mapped[str] = mapped_column(String(80))
    model_version: Mapped[str] = mapped_column(String(40))

    market_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    news_used: Mapped[list] = mapped_column(JSON, default=list)
    indicator_forecasts: Mapped[list] = mapped_column(JSON, default=list)

    prob_up: Mapped[float | None] = mapped_column(Float)
    prob_down: Mapped[float | None] = mapped_column(Float)
    prob_flat: Mapped[float | None] = mapped_column(Float)
    dominant_direction: Mapped[str | None] = mapped_column(String(10))  # up|down|flat
    importance: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float | None] = mapped_column(Float)  # 0-100

    # 発表直前価格からの価格差（ドル、符号付き）
    d1: Mapped[float | None] = mapped_column(Float)
    d5: Mapped[float | None] = mapped_column(Float)
    d15: Mapped[float | None] = mapped_column(Float)
    d30: Mapped[float | None] = mapped_column(Float)
    d60: Mapped[float | None] = mapped_column(Float)
    # 時間幅が明示されていない一点予想（会話記録用）。終着地とは比較しない。
    headline_move: Mapped[float | None] = mapped_column(Float)

    # 発表後5分間の最大変動（いずれも基準価格からの絶対値・ドル）
    max_up_5m: Mapped[float | None] = mapped_column(Float)
    max_down_5m: Mapped[float | None] = mapped_column(Float)
    max_excursion_5m: Mapped[float | None] = mapped_column(Float)  # 上下どちらかへの最大到達幅
    max_excursion_5m_low: Mapped[float | None] = mapped_column(Float)
    max_excursion_5m_high: Mapped[float | None] = mapped_column(Float)
    range_5m: Mapped[float | None] = mapped_column(Float)  # 高値−安値
    range_30m: Mapped[float | None] = mapped_column(Float)
    range_60m: Mapped[float | None] = mapped_column(Float)

    # {"10": {"up":..,"down":..,"either":..,"both":..}, ...} 確率は0-100
    reach_probs: Mapped[dict] = mapped_column(JSON, default=dict)

    initial_direction: Mapped[str | None] = mapped_column(String(10))
    initial_move: Mapped[float | None] = mapped_column(Float)  # 符号付き
    reversal_prob: Mapped[float | None] = mapped_column(Float)
    reversal_size: Mapped[float | None] = mapped_column(Float)

    # 条件付きシナリオ: [{"label","indicator_code","min","max","reaction_min","reaction_max","window"}]
    scenarios: Mapped[list] = mapped_column(JSON, default=list)
    # 構造化フィールドに入らない記録（時間幅不明の値幅など）。[{"label","value"}]
    extras: Mapped[list] = mapped_column(JSON, default=list)
    # FOMC等のフェーズ別分析: {"statement": {...}, "press_conference": {...}}
    phase_analysis: Mapped[dict] = mapped_column(JSON, default=dict)

    rationale: Mapped[str | None] = mapped_column(Text)
    change_summary: Mapped[str | None] = mapped_column(Text)
    warnings: Mapped[list] = mapped_column(JSON, default=list)

    event: Mapped[Event] = relationship(back_populates="forecasts")

    __table_args__ = (UniqueConstraint("event_id", "version_no"),)


@event.listens_for(ForecastVersion, "before_update")
def _forbid_update(mapper, connection, target):  # noqa: ARG001
    raise ValueError("予測バージョンは不変です。新しいバージョンを作成してください。")


@event.listens_for(ForecastVersion, "before_delete")
def _forbid_delete(mapper, connection, target):  # noqa: ARG001
    raise ValueError("予測バージョンは削除できません。")


class Outcome(Base):
    """発表後の実際の値動き。kind で出所を区別する。"""

    __tablename__ = "outcomes"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    # conversation_record: 会話由来の暫定記録 / price_bars: インポート価格データから算出
    kind: Mapped[str] = mapped_column(String(30))
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(200))
    symbol: Mapped[str] = mapped_column(String(20), default="XAUUSD")
    timeframe_min: Mapped[int | None] = mapped_column(Integer)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    base_price: Mapped[float | None] = mapped_column(Float)
    base_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    d1: Mapped[float | None] = mapped_column(Float)
    d5: Mapped[float | None] = mapped_column(Float)
    d15: Mapped[float | None] = mapped_column(Float)
    d30: Mapped[float | None] = mapped_column(Float)
    d60: Mapped[float | None] = mapped_column(Float)
    headline_move: Mapped[float | None] = mapped_column(Float)  # 時間幅不明の観測値動き
    high_5m: Mapped[float | None] = mapped_column(Float)
    low_5m: Mapped[float | None] = mapped_column(Float)
    max_up_5m: Mapped[float | None] = mapped_column(Float)
    max_down_5m: Mapped[float | None] = mapped_column(Float)
    max_excursion_5m: Mapped[float | None] = mapped_column(Float)
    range_5m: Mapped[float | None] = mapped_column(Float)
    range_30m: Mapped[float | None] = mapped_column(Float)
    range_60m: Mapped[float | None] = mapped_column(Float)
    direction_5m: Mapped[str | None] = mapped_column(String(10))
    observed_direction: Mapped[str | None] = mapped_column(String(10))  # 時間幅不明の観測方向
    initial_direction: Mapped[str | None] = mapped_column(String(10))
    initial_move: Mapped[float | None] = mapped_column(Float)
    reversed_: Mapped[bool | None] = mapped_column("reversed", Boolean)
    reversal_size: Mapped[float | None] = mapped_column(Float)
    # 関連市場（DXY・米金利）の変化: {"DXY": {"d5":..,"d60":..}, "US10Y": {...}}
    related_markets: Mapped[dict] = mapped_column(JSON, default=dict)
    observations: Mapped[list] = mapped_column(JSON, default=list)  # [{"label","value"}]
    missing: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str | None] = mapped_column(Text)

    event: Mapped[Event] = relationship(back_populates="outcomes")


class Evaluation(Base):
    """予測バージョン × 実績 の比較結果。"""

    __tablename__ = "evaluations"

    id: Mapped[int] = mapped_column(primary_key=True)
    forecast_id: Mapped[int] = mapped_column(ForeignKey("forecast_versions.id"), index=True)
    outcome_id: Mapped[int] = mapped_column(ForeignKey("outcomes.id"), index=True)
    tentative: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[list] = mapped_column(JSON, default=list)

    forecast: Mapped[ForecastVersion] = relationship()
    outcome: Mapped[Outcome] = relationship()

    __table_args__ = (UniqueConstraint("forecast_id", "outcome_id"),)


class ResearchReport(Base):
    """検証レポート。確認できた事実とAIの仮説を分けて保存する。"""

    __tablename__ = "research_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    outcome_id: Mapped[int | None] = mapped_column(ForeignKey("outcomes.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    tentative: Mapped[bool] = mapped_column(Boolean, default=True)
    generated_by: Mapped[str] = mapped_column(String(80))  # rule_engine|llm:<model>|conversation_import
    summary: Mapped[str] = mapped_column(Text, default="")
    confirmed_facts: Mapped[list] = mapped_column(JSON, default=list)
    hypotheses: Mapped[list] = mapped_column(JSON, default=list)
    reflections: Mapped[list] = mapped_column(JSON, default=list)
    improvements: Mapped[list] = mapped_column(JSON, default=list)
    checklist: Mapped[dict] = mapped_column(JSON, default=dict)

    event: Mapped[Event] = relationship(back_populates="reports")


class PriceBar(Base):
    __tablename__ = "price_bars"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    timeframe_min: Mapped[int] = mapped_column(Integer)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)  # バー開始時刻(UTC)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(60))
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"))

    __table_args__ = (UniqueConstraint("symbol", "timeframe_min", "ts", "source"),)


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(300))
    symbol: Mapped[str] = mapped_column(String(20))
    timeframe_min: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(60))
    assumed_tz: Mapped[str | None] = mapped_column(String(60))
    rows_total: Mapped[int] = mapped_column(Integer, default=0)
    rows_inserted: Mapped[int] = mapped_column(Integer, default=0)
    rows_skipped: Mapped[int] = mapped_column(Integer, default=0)
    first_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="success")
    message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NewsItem(Base):
    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id"), index=True)
    title: Mapped[str] = mapped_column(String(400))
    url: Mapped[str | None] = mapped_column(String(800))  # 不明なら NULL。捏造しない。
    source: Mapped[str] = mapped_column(String(120))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    summary: Mapped[str | None] = mapped_column(Text)


class ModelVersion(Base):
    """予測モデルの登録簿。改善が実証された場合のみ active を切り替える。"""

    __tablename__ = "model_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    version: Mapped[str] = mapped_column(String(40))
    scope: Mapped[str] = mapped_column(String(40), default="ALL")  # 指標カテゴリ or ALL
    kind: Mapped[str] = mapped_column(String(40))  # conversation|statistical|ml|llm|manual
    status: Mapped[str] = mapped_column(String(20), default="candidate")  # active|candidate|retired|reference
    description: Mapped[str | None] = mapped_column(Text)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    backtest: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    adopted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("name", "version", "scope"),)


class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job: Mapped[str] = mapped_column(String(60), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="running")  # running|success|failed|skipped
    message: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
