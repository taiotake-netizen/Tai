"""Time helpers. Store UTC, compute business days in Asia/Tokyo."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")

_clock_override: datetime | None = None


def set_clock(dt: datetime | None) -> None:
    """Test hook: freeze 'now'."""
    global _clock_override
    _clock_override = dt


def now() -> datetime:
    return _clock_override if _clock_override is not None else datetime.now(UTC)


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("naive datetime")
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def now_iso() -> str:
    return iso(now())


def parse(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)


def tz(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def local_midnight(dt: datetime, zone: ZoneInfo) -> datetime:
    loc = dt.astimezone(zone)
    return loc.replace(hour=0, minute=0, second=0, microsecond=0)


def daily_period(ref: datetime, zone: ZoneInfo) -> tuple[datetime, datetime]:
    """Previous local day: [yesterday 00:00, today 00:00) local, returned in UTC."""
    end = local_midnight(ref, zone)
    start = datetime.combine(end.date() - timedelta(days=1), datetime.min.time(), zone)
    return start.astimezone(UTC), end.astimezone(UTC)


def weekly_period(ref: datetime, zone: ZoneInfo) -> tuple[datetime, datetime]:
    """Previous week: [last Monday 00:00, this Monday 00:00) local, returned in UTC."""
    loc = ref.astimezone(zone)
    this_monday = loc.date() - timedelta(days=loc.weekday())
    end = datetime.combine(this_monday, datetime.min.time(), zone)
    start = datetime.combine(this_monday - timedelta(days=7), datetime.min.time(), zone)
    return start.astimezone(UTC), end.astimezone(UTC)
