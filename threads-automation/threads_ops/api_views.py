"""Read models for the API (overview, agents, KPIs)."""

from __future__ import annotations

from datetime import timedelta

from . import ideas as idea_bank
from .context import Ctx
from .db import loads, rows
from .llm import usage_summary
from .scheduler import next_runs
from .store import active_policy, get_account, get_settings, get_state, is_test_scope
from .timeutil import iso, now, tz

HEARTBEAT_STALE_S = 180

AGENTS = [
    {"id": "orchestrator", "name": "集客統括", "role": "スケジュール作成・全体の進行管理",
     "kinds": ("refill_ideas",), "needs": "scheduler"},
    {"id": "threads_ops", "name": "Threads運用", "role": "予約投稿の公開・結果照会・実績取得",
     "kinds": ("publish_post", "reconcile_post", "collect_metrics", "check_connection"), "needs": "threads"},
    {"id": "content", "name": "コンテンツ制作", "role": "ネタ選択・投稿文の生成と品質チェック",
     "kinds": ("generate_post", "assistant"), "needs": "llm"},
    {"id": "analytics", "name": "集客分析", "role": "実績分析・改善実験・日次/週次レポート",
     "kinds": ("analyze", "daily_report", "weekly_report"), "needs": "llm_optional"},
]


def _fresh(state: dict | None, key: str) -> bool:
    if not state:
        return False
    from .timeutil import parse
    ts = state["value"].get(key) or state["updated_at"]
    return (now() - parse(ts)).total_seconds() < HEARTBEAT_STALE_S


def runtime(ctx: Ctx) -> dict:
    sched = get_state(ctx.conn, "scheduler")
    workers = [dict(r) for r in ctx.conn.execute("SELECT key, value_json, updated_at FROM runtime_state WHERE key LIKE 'worker:%'")]
    worker_alive = any(_fresh({"value": loads(w["value_json"]), "updated_at": w["updated_at"]}, "last_seen") for w in workers)
    return {
        "scheduler_alive": _fresh(sched, "last_tick"),
        "scheduler_last_tick": sched["value"].get("last_tick") if sched else None,
        "worker_alive": worker_alive,
        "worker_last_seen": max((w["updated_at"] for w in workers), default=None),
    }


def agents(ctx: Ctx, account_id: str, rt: dict, s, account: dict) -> list[dict]:
    conn = ctx.conn
    llm = ctx.llm.availability()
    since = iso(now() - timedelta(hours=24))
    out = []
    for a in AGENTS:
        kinds = a["kinds"]
        ph = ",".join("?" * len(kinds))
        running = rows(conn.execute(
            f"SELECT id, kind, post_id, started_at FROM jobs WHERE account_id=? AND status IN ('running','cancel_requested')"
            f" AND kind IN ({ph}) ORDER BY started_at", (account_id, *kinds)).fetchall())
        last = conn.execute(
            f"SELECT status, kind, last_error, finished_at FROM jobs WHERE account_id=? AND kind IN ({ph})"
            f" AND status IN ('succeeded','failed') AND finished_at>=? ORDER BY finished_at DESC LIMIT 1",
            (account_id, *kinds, since)).fetchone()
        queued = conn.execute(f"SELECT COUNT(*) c FROM jobs WHERE account_id=? AND status='queued' AND kind IN ({ph})",
                              (account_id, *kinds)).fetchone()["c"]
        connected, reason, tool = True, None, None
        if a["needs"] == "scheduler":
            tool = "scheduler"
            if not rt["scheduler_alive"]:
                connected, reason = False, "スケジューラーが停止しています"
            elif not s.autopilot_enabled:
                reason = "自動運用OFF"
        elif a["needs"] == "threads":
            if ctx.cfg.publish_mode != "live" or not s.live_publish_enabled or account["data_scope"] != "live":
                tool, reason = "dry-run（実投稿なし）", "テストモード（実投稿しません）"
            else:
                tool = "Threads API"
                if account["connection_status"] != "connected":
                    connected, reason = False, f"Threads未接続（{account['connection_status']}）"
        else:
            tool = f"{llm['provider']}:{llm['model']}" if llm["model"] else llm["provider"]
            if not llm["available"]:
                connected = a["needs"] == "llm_optional"
                reason = llm["reason"]
        if not rt["worker_alive"]:
            connected, reason = False, "ワーカーが停止しています"
        if not connected:
            state = "unavailable"
        elif running:
            state = "running"
        elif last and last["status"] == "failed":
            state = "error"
        elif queued:
            state = "waiting"
        else:
            state = "idle"
        out.append({"id": a["id"], "name": a["name"], "role": a["role"], "state": state, "connected": connected,
                    "reason": reason, "tool": tool, "queued": queued, "running": running,
                    "last": dict(last) if last else None})
    return out


def overview(ctx: Ctx, account_id: str) -> dict:
    conn = ctx.conn
    account = get_account(conn, account_id)
    s, sver = get_settings(conn, account_id)
    test = int(is_test_scope(account))
    zone = tz(s.schedule.timezone)
    local = now().astimezone(zone)
    day_start = iso(local.replace(hour=0, minute=0, second=0, microsecond=0))
    rt = runtime(ctx)
    published_today = conn.execute(
        "SELECT COUNT(*) c FROM posts WHERE account_id=? AND status='published' AND published_at>=? AND is_test=?",
        (account_id, day_start, test)).fetchone()["c"]
    att = {r["outcome"]: r["c"] for r in conn.execute(
        "SELECT a.outcome, COUNT(*) c FROM post_attempts a JOIN posts p ON p.id=a.post_id WHERE p.account_id=? AND p.is_test=?"
        " AND a.kind='publish' AND a.outcome<>'started' AND a.created_at>=? GROUP BY a.outcome", (account_id, test, day_start))}
    since7 = iso(now() - timedelta(days=7))
    m7 = conn.execute(
        "SELECT COUNT(*) n, SUM(views) views, SUM(likes) likes, SUM(replies) replies, SUM(reposts) reposts, SUM(quotes) quotes,"
        " MAX(observed_at) last FROM metrics m JOIN posts p ON p.id=m.post_id WHERE m.account_id=? AND m.is_test=? AND m.status='ok'"
        " AND m.bucket_hours=? AND p.published_at>=?", (account_id, test, s.improvement.primary_bucket_hours, since7)).fetchone()
    m7 = dict(m7)
    er = None
    if m7["views"]:
        er = sum((m7[k] or 0) for k in ("likes", "replies", "reposts", "quotes")) / m7["views"]
    attention = rows(conn.execute(
        "SELECT 'post' kind, id, status, last_error message, updated_at FROM posts WHERE account_id=? AND"
        " (status IN ('unknown','awaiting_approval') OR (status IN ('failed','skipped') AND updated_at>=?))"
        " ORDER BY updated_at DESC LIMIT 20", (account_id, iso(now() - timedelta(hours=48)))).fetchall())
    attention += rows(conn.execute(
        "SELECT 'job' kind, id, status, kind || ': ' || COALESCE(last_error,'') message, updated_at FROM jobs WHERE account_id=?"
        " AND status='failed' AND updated_at>=? ORDER BY updated_at DESC LIMIT 10",
        (account_id, iso(now() - timedelta(hours=48)))).fetchall())
    pol = active_policy(conn, account_id)
    exp = conn.execute("SELECT id, variable, control_value, treatment_value, hypothesis, started_at FROM experiments"
                       " WHERE account_id=? AND status='running'", (account_id,)).fetchone()
    live = ctx.cfg.publish_mode == "live" and s.live_publish_enabled and account["data_scope"] == "live"
    return {
        "account": {k: account[k] for k in ("id", "display_name", "platform", "data_scope", "connection_status",
                                            "connection_checked_at", "connection_error")},
        "mode": {"app_env": ctx.cfg.app_env, "publish_mode": ctx.cfg.publish_mode, "live_publishing": live,
                 "data": "demo" if account["data_scope"] == "demo" else ("test" if test else "live")},
        "autopilot_enabled": s.autopilot_enabled,
        "require_approval": s.require_approval,
        "improvement_enabled": s.improvement.enabled,
        "settings_version": sver,
        "runtime": rt,
        "llm": ctx.llm.availability(),
        "next": next_runs(conn, account_id),
        "kpi": {
            "published_today": published_today,
            "publish_attempts_today": {"success": att.get("ok", 0), "failed": att.get("error", 0), "unknown": att.get("unknown", 0)},
            "success_rate_today": (att.get("ok", 0) / (att.get("ok", 0) + att.get("error", 0))) if (att.get("ok", 0) + att.get("error", 0)) else None,
            "metrics_7d": {"posts": m7["n"], "views": m7["views"], "likes": m7["likes"], "replies": m7["replies"],
                           "reposts": m7["reposts"], "er": er, "last_observed_at": m7["last"]},
            "ideas_ready": idea_bank.ready_count(conn, account_id, bool(test)),
            "pending_approvals": conn.execute("SELECT COUNT(*) c FROM posts WHERE account_id=? AND status='awaiting_approval'",
                                              (account_id,)).fetchone()["c"],
        },
        "policy": {"version": pol["version"], "source": pol["source"], "reason": pol["reason"], "created_at": pol["created_at"]},
        "experiment": dict(exp) if exp else None,
        "budget": usage_summary(conn, account_id, s),
        "agents": agents(ctx, account_id, rt, s, account),
        "attention": attention,
        "generated_at": iso(now()),
    }
