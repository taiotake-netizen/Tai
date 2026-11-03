"""Scheduler tick: plan slots, enqueue jobs, expire missed work, recover dead leases. Idempotent; safe to run
from several processes (all inserts go through UNIQUE keys)."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from . import ideas as idea_bank
from . import jobs
from .context import Ctx
from .db import row, rows, tx
from .reports import period_for
from .settings import AccountSettingsModel, Policy, reconcile_policy
from .store import active_policy, emit, get_settings, is_test_scope, list_accounts, set_state
from .timeutil import iso, now, now_iso, parse, tz


def _local_at(day, hhmm: str, zone) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=zone)


def _treatment_day(day, share: float, exp_id: int) -> bool:
    h = int(hashlib.sha256(f"day:{exp_id}:{day.isoformat()}".encode()).hexdigest()[:8], 16) % 1000
    return h < share * 1000


def planned_times(day, s: AccountSettingsModel, policy: Policy, exp: dict | None) -> list[tuple[str, int | None, str | None]]:
    times = list(policy.post_times)[: s.schedule.posts_per_day]
    out = []
    for t in times:
        if exp and exp["variable"] == "post_time" and t == exp["control_value"]:
            if _treatment_day(day, s.improvement.treatment_share, exp["id"]):
                out.append((exp["treatment_value"], exp["id"], "treatment"))
            else:
                out.append((t, exp["id"], "control"))
        else:
            out.append((t, None, None))
    return out


def tick(ctx: Ctx) -> dict:
    conn = ctx.conn
    summary = {"planned": 0, "expired": 0, "recovered": 0}
    for j in jobs.recover_expired(conn):
        summary["recovered"] += 1
        if j["kind"] == "publish_post" and j["post_id"]:
            with tx(conn):
                conn.execute("UPDATE posts SET status='unknown', last_error=?, updated_at=? WHERE id=? AND status='publishing'",
                             ("公開処理中にワーカーが停止", now_iso(), j["post_id"]))
            jobs.enqueue(conn, j["account_id"], "reconcile_post", f"reconcile:{j['post_id']}:1", now(),
                         post_id=j["post_id"], payload={"round": 1}, max_attempts=1)
    for acct in list_accounts(conn, None):
        summary["planned"] += _plan_account(ctx, acct)
        summary["expired"] += _expire(ctx, acct)
    with tx(conn):
        set_state(conn, "scheduler", {"last_tick": now_iso(), **summary})
    return summary


def _plan_account(ctx: Ctx, acct: dict) -> int:
    conn = ctx.conn
    s, _ = get_settings(conn, acct["id"])
    zone = tz(s.schedule.timezone)
    t = now()
    today = t.astimezone(zone).date()
    test = is_test_scope(acct)
    live_capable = (ctx.cfg.publish_mode == "live" and s.live_publish_enabled and acct["data_scope"] == "live")
    created = 0
    if s.autopilot_enabled:
        policy = reconcile_policy(Policy.model_validate(active_policy(conn, acct["id"])["policy"]), s)
        exp = row(conn.execute("SELECT * FROM experiments WHERE account_id=? AND status='running'", (acct["id"],)).fetchone())
        wanted: set[str] = set()
        for day in (today, today + timedelta(days=1)):
            for hhmm, exp_id, arm in planned_times(day, s, policy, exp):
                slot = _local_at(day, hhmm, zone)
                if slot <= t:
                    continue
                slot_iso = iso(slot)
                wanted.add(slot_iso)
                with tx(conn):
                    exists = conn.execute("SELECT 1 FROM posts WHERE account_id=? AND slot_at=? AND origin='schedule'",
                                          (acct["id"], slot_iso)).fetchone()
                    inserted = False
                    if not exists:
                        cur = conn.execute(
                            "INSERT OR IGNORE INTO posts(account_id, slot_at, status, experiment_id, experiment_arm, origin,"
                            " is_test, created_at, updated_at) VALUES (?,?,'planned',?,?,'schedule',?,?,?)",
                            (acct["id"], slot_iso, exp_id, arm, int(test or not live_capable), now_iso(), now_iso()))
                        inserted = cur.rowcount == 1
                    if inserted:
                        created += 1
                        emit(conn, acct["id"], "post.planned", f"投稿枠を作成 {slot.strftime('%m/%d %H:%M')}",
                             post_id=cur.lastrowid, payload={"slot_at": slot_iso})
                p = row(conn.execute("SELECT id, status FROM posts WHERE account_id=? AND slot_at=? AND origin='schedule'",
                                     (acct["id"], slot_iso)).fetchone())
                if p and p["status"] == "planned":
                    run_at = max(t, slot - timedelta(minutes=s.schedule.generation_lead_minutes))
                    jobs.enqueue(conn, acct["id"], "generate_post", f"gen:{p['id']}", run_at, post_id=p["id"],
                                 max_attempts=2)
        # future planned slots that no longer match the schedule are cancelled (not yet generated → nothing lost)
        stale = rows(conn.execute(
            "SELECT id, slot_at FROM posts WHERE account_id=? AND origin='schedule' AND status='planned' AND slot_at>?",
            (acct["id"], iso(t))).fetchall())
        for p in stale:
            if p["slot_at"] not in wanted:
                with tx(conn):
                    conn.execute("UPDATE posts SET status='cancelled', last_error=?, updated_at=? WHERE id=?",
                                 ("スケジュール変更により不要になった枠", now_iso(), p["id"]))
                    conn.execute("UPDATE jobs SET status='cancelled', finished_at=?, updated_at=? WHERE post_id=?"
                                 " AND status='queued'", (now_iso(), now_iso(), p["id"]))
        if idea_bank.ready_count(conn, acct["id"], test) < s.ideas.refill_when_ready_below:
            local = t.astimezone(zone)
            jobs.enqueue(conn, acct["id"], "refill_ideas", f"refill:{acct['id']}:{local.date()}:{local.hour // 6}", t,
                         max_attempts=1)
    local_now = t.astimezone(zone)
    if s.improvement.enabled and s.autopilot_enabled:
        at = _local_at(today, s.improvement.analysis_time, zone)
        jobs.enqueue(conn, acct["id"], "analyze", f"analyze:{acct['id']}:{today}", at,
                     max_attempts=2)
    if s.reports.enabled:
        at = _local_at(today, s.reports.daily_time, zone)
        if t >= at:
            ps, pe = period_for("daily", t, zone)
            jobs.enqueue(conn, acct["id"], "daily_report", f"report:daily:{acct['id']}:{iso(ps)}", at,
                         payload={"kind": "daily", "period_start": iso(ps), "period_end": iso(pe)}, max_attempts=3)
        if local_now.weekday() == s.reports.weekly_weekday:
            at = _local_at(today, s.reports.weekly_time, zone)
            if t >= at:
                ps, pe = period_for("weekly", t, zone)
                jobs.enqueue(conn, acct["id"], "weekly_report", f"report:weekly:{acct['id']}:{iso(ps)}", at,
                             payload={"kind": "weekly", "period_start": iso(ps), "period_end": iso(pe)}, max_attempts=3)
    if acct["data_scope"] == "live" and acct.get("token_env"):
        jobs.enqueue(conn, acct["id"], "check_connection",
                     f"conn:{acct['id']}:{local_now.date()}:{local_now.hour // 6}", t, max_attempts=1)
    return created


def _expire(ctx: Ctx, acct: dict) -> int:
    conn = ctx.conn
    s, _ = get_settings(conn, acct["id"])
    cutoff = iso(now() - timedelta(minutes=s.schedule.missed_grace_minutes))
    n = 0
    stale = rows(conn.execute(
        "SELECT id, status FROM posts WHERE account_id=? AND origin='schedule' AND status IN ('planned','awaiting_approval')"
        " AND slot_at<?", (acct["id"], cutoff)).fetchall())
    for p in stale:
        reason = "承認されないまま予定時刻を過ぎました" if p["status"] == "awaiting_approval" else "予定時刻までに生成できませんでした"
        idea_bank.release(conn, p["id"])
        with tx(conn):
            cur = conn.execute("UPDATE posts SET status='skipped', last_error=?, updated_at=? WHERE id=? AND status=?",
                               (reason, now_iso(), p["id"], p["status"]))
            if cur.rowcount:
                n += 1
                emit(conn, acct["id"], "post.skipped", reason, severity="warning", post_id=p["id"])
                conn.execute("UPDATE jobs SET status='cancelled', finished_at=?, updated_at=? WHERE post_id=? AND"
                             " status='queued' AND kind='generate_post'", (now_iso(), now_iso(), p["id"]))
    return n


def next_runs(conn, account_id: str) -> dict:
    def nxt(kinds: tuple[str, ...]) -> str | None:
        r = conn.execute(f"SELECT MIN(run_at) t FROM jobs WHERE account_id=? AND status='queued' AND kind IN ({','.join('?' * len(kinds))})",
                         (account_id, *kinds)).fetchone()
        return r["t"]
    nxt_post = conn.execute(
        "SELECT id, slot_at, status FROM posts WHERE account_id=? AND status IN ('planned','generating','awaiting_approval','scheduled')"
        " AND slot_at>=? ORDER BY slot_at LIMIT 1", (account_id, now_iso())).fetchone()
    return {"next_post": dict(nxt_post) if nxt_post else None, "next_analysis_at": nxt(("analyze",)),
            "next_report_at": nxt(("daily_report", "weekly_report")), "next_metrics_at": nxt(("collect_metrics",))}


def stale_threshold(ts: str | None, seconds: int) -> bool:
    return ts is None or (now() - parse(ts)).total_seconds() > seconds
