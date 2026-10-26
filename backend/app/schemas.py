from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .models import CATEGORIES

Direction = Literal["up", "down", "flat"]


class EventCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    category: str
    categories: list[str] | None = None
    release_at: datetime | None = None
    release_time_confirmed: bool = False
    importance: int = Field(5, ge=1, le=10)
    is_composite: bool = False
    parent_id: int | None = None
    notes: str | None = None
    indicators: list["IndicatorCreate"] = []

    @field_validator("category")
    @classmethod
    def _category(cls, v: str) -> str:
        if v not in CATEGORIES:
            raise ValueError(f"未対応のカテゴリです: {v}")
        return v


class EventUpdate(BaseModel):
    title: str | None = None
    release_at: datetime | None = None
    release_time_confirmed: bool | None = None
    importance: int | None = Field(None, ge=1, le=10)
    notes: str | None = None


class IndicatorCreate(BaseModel):
    code: str = Field(min_length=1, max_length=60)
    name: str
    unit: str = ""
    previous: float | None = None
    previous_revised: float | None = None
    consensus: float | None = None
    consensus_source: str | None = None


class IndicatorUpdate(BaseModel):
    previous: float | None = None
    previous_revised: float | None = None
    consensus: float | None = None
    consensus_source: str | None = None
    actual: float | None = None
    actual_source: str | None = None
    actual_verified: bool | None = None
    notes: str | None = None


class NewsRef(BaseModel):
    title: str
    url: str | None = None
    source: str
    published_at: datetime | None = None


class ReachRow(BaseModel):
    up: float | None = None
    down: float | None = None
    either: float | None = None
    both: float | None = None


class IndicatorForecast(BaseModel):
    code: str
    point: float | None = None
    upside_risk: str | None = None
    downside_risk: str | None = None
    rationale: str | None = None


class Scenario(BaseModel):
    label: str
    value: str | None = None
    indicator_code: str | None = None
    min: float | None = None
    max: float | None = None
    reaction_min: float | None = None
    reaction_max: float | None = None
    window: str | None = None


class ForecastCreate(BaseModel):
    label: str | None = None
    model_name: str = "manual"
    model_version: str = "1"
    market_snapshot: dict = {}
    news_used: list[NewsRef] = []
    indicator_forecasts: list[IndicatorForecast] = []
    prob_up: float | None = None
    prob_down: float | None = None
    prob_flat: float | None = None
    dominant_direction: Direction | None = None
    importance: int | None = None
    confidence: float | None = None
    d1: float | None = None
    d5: float | None = None
    d15: float | None = None
    d30: float | None = None
    d60: float | None = None
    max_up_5m: float | None = None
    max_down_5m: float | None = None
    max_excursion_5m: float | None = None
    max_excursion_5m_low: float | None = None
    max_excursion_5m_high: float | None = None
    range_5m: float | None = None
    range_30m: float | None = None
    range_60m: float | None = None
    reach_probs: dict[str, ReachRow] = {}
    initial_direction: Direction | None = None
    initial_move: float | None = None
    reversal_prob: float | None = None
    reversal_size: float | None = None
    scenarios: list[Scenario] = []
    phase_analysis: dict = {}
    rationale: str | None = None
    change_summary: str | None = None

    def to_data(self) -> dict:
        d = self.model_dump(exclude={"model_name", "model_version"})
        d["news_used"] = [n.model_dump(mode="json") for n in self.news_used]
        d["reach_probs"] = {k: v.model_dump() for k, v in self.reach_probs.items()}
        return d


EventCreate.model_rebuild()
