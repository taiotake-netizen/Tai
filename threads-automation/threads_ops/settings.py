"""Per-account operating settings (user-owned) and the improvable policy layer (auto-tuned, versioned).

Settings are the fixed frame: business facts, brand, banned phrases, caps, budget, locks.
Policy is what the improvement loop may change, always validated against Settings.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
THREADS_TEXT_LIMIT = 500  # Threads API text post limit (characters). Verify against official docs before go-live.


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


class CtaOption(BaseModel):
    key: str = Field(min_length=1, max_length=40, pattern=r"^[a-z0-9_\-]+$")
    text: str = Field(min_length=1, max_length=120)
    url: str | None = None


class ApprovedFact(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    statement: str = Field(min_length=1, max_length=300)
    source: str = Field(min_length=1, max_length=200)


class BusinessSettings(BaseModel):
    service_name: str = ""          # empty = not provided yet (never invent)
    target: str = ""
    offer_summary: str = ""
    tone: str = "親しみやすく誠実。煽らない。断定しすぎない。"
    approved_facts: list[ApprovedFact] = Field(default_factory=list)
    cta_options: list[CtaOption] = Field(default_factory=lambda: [
        CtaOption(key="none", text="（CTAなし）"),
        CtaOption(key="follow", text="参考になったらフォローしてね"),
        CtaOption(key="save", text="あとで見返せるように保存しておいてね"),
    ])
    allowed_domains: list[str] = Field(default_factory=list)


class ContentSettings(BaseModel):
    min_chars: int = Field(60, ge=1, le=THREADS_TEXT_LIMIT)
    max_chars: int = Field(400, ge=20, le=THREADS_TEXT_LIMIT)
    themes: list[str] = Field(default_factory=lambda: [
        "副業の始め方", "時間の使い方", "スキルの選び方", "続けるコツ", "失敗から学ぶこと",
    ], min_length=1)
    hook_styles: list[str] = Field(default_factory=lambda: ["問いかけ", "共感", "結論先出し", "意外な事実", "手順"])
    appeals: list[str] = Field(default_factory=lambda: ["不安の解消", "時間効率", "学びの楽しさ", "小さな一歩"])
    structures: list[str] = Field(default_factory=lambda: ["箇条書き", "短い段落", "問いと答え"])
    banned_phrases: list[str] = Field(default_factory=lambda: [
        "必ず稼げる", "絶対稼げる", "誰でも簡単に", "確実に儲かる", "不労所得", "楽して稼ぐ", "元本保証",
    ])

    @model_validator(mode="after")
    def _range(self) -> ContentSettings:
        if self.min_chars >= self.max_chars:
            raise ValueError("min_chars must be < max_chars")
        return self


class ScheduleSettings(BaseModel):
    timezone: str = "Asia/Tokyo"
    posts_per_day: int = Field(3, ge=0, le=10)
    max_posts_per_day: int = Field(5, ge=0, le=20)      # hard cap: improvement cannot exceed
    post_times: list[str] = Field(default_factory=lambda: ["07:30", "12:15", "18:00", "21:00"])  # candidates
    window_start: str = "07:00"
    window_end: str = "23:00"
    generation_lead_minutes: int = Field(90, ge=10, le=24 * 60)
    missed_grace_minutes: int = Field(20, ge=1, le=180)

    @field_validator("post_times")
    @classmethod
    def _times(cls, v: list[str]) -> list[str]:
        for t in v:
            if not HHMM.match(t):
                raise ValueError(f"invalid time {t!r}")
        if len(set(v)) != len(v):
            raise ValueError("duplicate post time")
        return sorted(v)

    @model_validator(mode="after")
    def _consistency(self) -> ScheduleSettings:
        for t in (self.window_start, self.window_end):
            if not HHMM.match(t):
                raise ValueError(f"invalid time {t!r}")
        if self.posts_per_day > self.max_posts_per_day:
            raise ValueError("posts_per_day exceeds max_posts_per_day")
        if len(self.post_times) < self.posts_per_day:
            raise ValueError("post_times must have at least posts_per_day entries")
        ws, we = _minutes(self.window_start), _minutes(self.window_end)
        for t in self.post_times:
            if not ws <= _minutes(t) <= we:
                raise ValueError(f"post time {t} outside allowed window")
        return self


class CheckSettings(BaseModel):
    similarity_window_days: int = Field(45, ge=1, le=365)
    similarity_threshold: float = Field(0.5, gt=0, lt=1)
    theme_max_consecutive: int = Field(2, ge=1, le=10)
    cta_max_consecutive: int = Field(2, ge=1, le=10)
    max_regenerations: int = Field(2, ge=0, le=5)
    ai_review_enabled: bool = True


class IdeaSettings(BaseModel):
    reuse_interval_days: int = Field(21, ge=0, le=365)
    new_theme_share: float = Field(0.2, ge=0, le=0.8)
    refill_when_ready_below: int = Field(5, ge=0, le=100)
    refill_batch: int = Field(5, ge=1, le=20)
    refill_max_per_day: int = Field(10, ge=0, le=100)
    derive_top_performers: bool = True


class ImprovementSettings(BaseModel):
    enabled: bool = True
    observation_hours: list[int] = Field(default_factory=lambda: [24, 72])
    primary_bucket_hours: int = 24
    min_samples_per_arm: int = Field(5, ge=2, le=100)
    treatment_share: float = Field(0.3, ge=0.1, le=0.5)
    max_weight_step: float = Field(0.15, gt=0, le=0.5)
    min_lift: float = Field(0.1, ge=0, le=2)
    experiment_max_days: int = Field(14, ge=3, le=60)
    analysis_time: str = "10:00"
    rollback_window_posts: int = Field(6, ge=3, le=50)
    rollback_drop_threshold: float = Field(0.25, gt=0, lt=1)

    @model_validator(mode="after")
    def _check(self) -> ImprovementSettings:
        if self.primary_bucket_hours not in self.observation_hours:
            raise ValueError("primary_bucket_hours must be one of observation_hours")
        if not HHMM.match(self.analysis_time):
            raise ValueError("invalid analysis_time")
        if any(h < 1 or h > 24 * 14 for h in self.observation_hours):
            raise ValueError("observation_hours out of range")
        return self


class ReportSettings(BaseModel):
    enabled: bool = True
    daily_time: str = "09:00"
    weekly_weekday: int = Field(0, ge=0, le=6)   # 0 = Monday
    weekly_time: str = "09:15"
    ai_summary: bool = True

    @model_validator(mode="after")
    def _check(self) -> ReportSettings:
        for t in (self.daily_time, self.weekly_time):
            if not HHMM.match(t):
                raise ValueError("invalid report time")
        return self


class BudgetSettings(BaseModel):
    daily_usd: float | None = Field(None, ge=0)
    monthly_usd: float | None = Field(None, ge=0)
    price_input_per_mtok_usd: float | None = Field(None, ge=0)
    price_output_per_mtok_usd: float | None = Field(None, ge=0)
    max_output_tokens: int = Field(900, ge=64, le=8000)


LOCKABLE = Literal["hook", "theme", "cta", "appeal", "length", "structure", "post_time"]


class AccountSettingsModel(BaseModel):
    autopilot_enabled: bool = False
    live_publish_enabled: bool = False   # also requires PUBLISH_MODE=live on the server
    require_approval: bool = True
    business: BusinessSettings = Field(default_factory=BusinessSettings)
    content: ContentSettings = Field(default_factory=ContentSettings)
    schedule: ScheduleSettings = Field(default_factory=ScheduleSettings)
    checks: CheckSettings = Field(default_factory=CheckSettings)
    ideas: IdeaSettings = Field(default_factory=IdeaSettings)
    improvement: ImprovementSettings = Field(default_factory=ImprovementSettings)
    reports: ReportSettings = Field(default_factory=ReportSettings)
    budget: BudgetSettings = Field(default_factory=BudgetSettings)
    locked: list[LOCKABLE] = Field(default_factory=list)

    @model_validator(mode="after")
    def _cta_domains(self) -> AccountSettingsModel:
        from .quality import url_domain  # local import to avoid cycle

        for c in self.business.cta_options:
            if c.url:
                d = url_domain(c.url)
                if d is None or not any(d == a or d.endswith("." + a) for a in self.business.allowed_domains):
                    raise ValueError(f"CTA url domain not in allowed_domains: {c.key}")
        return self


# ---------------------------------------------------------------- policy (auto-tunable)

LENGTHS = {"short": (0.0, 0.45), "medium": (0.35, 0.75), "long": (0.65, 1.0)}
VARIABLES = ("hook", "theme", "cta", "appeal", "length", "structure", "post_time")


class Policy(BaseModel):
    hook_weights: dict[str, float]
    theme_weights: dict[str, float]
    cta_weights: dict[str, float]
    appeal_weights: dict[str, float]
    length_weights: dict[str, float]
    structure_weights: dict[str, float]
    post_times: list[str]


def weights_key(variable: str) -> str:
    return {"hook": "hook_weights", "theme": "theme_weights", "cta": "cta_weights", "appeal": "appeal_weights",
            "length": "length_weights", "structure": "structure_weights"}[variable]


def allowed_values(s: AccountSettingsModel, variable: str) -> list[str]:
    return {
        "hook": s.content.hook_styles,
        "theme": s.content.themes,
        "cta": [c.key for c in s.business.cta_options],
        "appeal": s.content.appeals,
        "length": list(LENGTHS),
        "structure": s.content.structures,
        "post_time": s.schedule.post_times,
    }[variable]


def _uniform(keys: list[str]) -> dict[str, float]:
    return {k: round(1 / len(keys), 6) for k in keys} if keys else {}


def initial_policy(s: AccountSettingsModel) -> Policy:
    return Policy(
        hook_weights=_uniform(s.content.hook_styles),
        theme_weights=_uniform(s.content.themes),
        cta_weights=_uniform([c.key for c in s.business.cta_options]),
        appeal_weights=_uniform(s.content.appeals),
        length_weights={"short": 0.3, "medium": 0.5, "long": 0.2},
        structure_weights=_uniform(s.content.structures),
        post_times=s.schedule.post_times[: s.schedule.posts_per_day],
    )


class PolicyViolation(ValueError):
    pass


def normalize(w: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, v) for v in w.values())
    if total <= 0:
        return _uniform(list(w))
    return {k: round(max(0.0, v) / total, 6) for k, v in w.items()}


def reconcile_policy(p: Policy, s: AccountSettingsModel) -> Policy:
    """Align a stored policy with current settings (new/removed themes, CTAs...). Keeps learned weights."""
    data = p.model_dump()
    for var in ("hook", "theme", "cta", "appeal", "structure"):
        key = weights_key(var)
        allowed = allowed_values(s, var)
        old = data[key]
        fresh = {k: old.get(k, 1 / max(1, len(allowed))) for k in allowed}
        data[key] = normalize(fresh)
    times = [t for t in data["post_times"] if t in s.schedule.post_times]
    if "post_time" in s.locked or len(times) != s.schedule.posts_per_day:
        times = s.schedule.post_times[: s.schedule.posts_per_day]
    data["post_times"] = sorted(times)
    return Policy.model_validate(data)


def validate_policy_change(old: Policy, new: Policy, s: AccountSettingsModel, *, max_step: float | None) -> None:
    """Reject any change outside the permitted envelope. max_step=None means manual edit (no step limit)."""
    for var in ("hook", "theme", "cta", "appeal", "length", "structure"):
        key = weights_key(var)
        o, n = getattr(old, key), getattr(new, key)
        allowed = set(allowed_values(s, var))
        if set(n) != allowed:
            raise PolicyViolation(f"{var}: keys must equal allowed values")
        if any(v < 0 for v in n.values()) or abs(sum(n.values()) - 1) > 1e-3:
            raise PolicyViolation(f"{var}: weights must be non-negative and sum to 1")
        changed = any(abs(n[k] - o.get(k, 0)) > 1e-9 for k in n)
        if changed and var in s.locked:
            raise PolicyViolation(f"{var} is locked by the user")
        if max_step is not None and any(abs(n[k] - o.get(k, 0)) > max_step + 1e-6 for k in n):
            raise PolicyViolation(f"{var}: change exceeds max step {max_step}")
        if var in ("hook", "theme", "cta", "appeal", "structure") and any(v < 0.03 for v in n.values()):
            # keep exploration alive: every option keeps a minimum share
            raise PolicyViolation(f"{var}: every option must keep at least 3% weight")
    if new.post_times != old.post_times:
        if "post_time" in s.locked:
            raise PolicyViolation("post_time is locked by the user")
        if len(new.post_times) != s.schedule.posts_per_day:
            raise PolicyViolation("post_times count must equal posts_per_day")
        if len(new.post_times) > s.schedule.max_posts_per_day:
            raise PolicyViolation("post_times exceeds max_posts_per_day")
        if any(t not in s.schedule.post_times for t in new.post_times):
            raise PolicyViolation("post_times must be chosen from configured candidate times")
