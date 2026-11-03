"""Publish, reconcile unknown outcomes, collect metrics.

Rules:
- A publish is attempted at most once per post automatically. Unknown outcomes become status 'unknown'
  and are reconciled by reading the account's recent posts; never blindly re-posted.
- Real publishing requires ALL of: PUBLISH_MODE=live, settings.live_publish_enabled, account.data_scope=live,
  post.is_test=0. Otherwise the dry-run simulator is used, and only for posts flagged is_test=1.
"""

from __future__ import annotations

from datetime import timedelta

from . import ideas as idea_bank
from . import jobs
from .context import Ctx
from .db import dumps, row, tx
from .generator import _record_attempt, local_slot
from .quality import normalize_text
from .store import consume_flag, emit, get_account, get_settings
from .threads_api import ThreadsClient, ThreadsError
from .timeutil import iso, now, now_iso, parse


def live_enabled(ctx: Ctx, account: dict, settings) -> bool:
    return ctx.cfg.publish_mode == "live" and settings.live_publish_enabled and account["data_scope"] == "live"


def publish_post(ctx: Ctx, job: dict) -> dict:
    conn = ctx.conn
    post = row(conn.execute("SELECT * FROM posts WHERE id=?", (job["post_id"],)).fetchone())
    if post is None or post["status"] != "scheduled":
        return {"skipped": f"post status {post['status'] if post else 'missing'}"}
    account = get_account(conn, post["account_id"])
    s, _ = get_settings(conn, account["id"])
    if not s.autopilot_enabled and post["origin"] == "schedule":
        return _not_published(ctx, post, "自動運用がOFFのため公開しませんでした（予約停止）")
    if now() > parse(post["slot_at"]) + timedelta(minutes=s.schedule.missed_grace_minutes):
        return _not_published(ctx, post, "予定時刻から猶予時間を過ぎたため公開しませんでした")
    live = live_enabled(ctx, account, s)
    if not live and not post["is_test"]:
        return _not_published(ctx, post, "本番投稿が無効なため公開しませんでした（テスト投稿ではありません）")
    if live and post["is_test"]:
        return _not_published(ctx, post, "テスト用の投稿は本番に公開しません")
    with tx(conn):
        cur = conn.execute("UPDATE posts SET status='publishing', updated_at=? WHERE id=? AND status='scheduled'",
                           (now_iso(), post["id"]))
        if cur.rowcount != 1:
            return {"skipped": "concurrent state change"}
    _record_attempt(ctx, post["id"], "publish", "started", {"live": live})
    try:
        if live:
            client = ThreadsClient(ctx.cfg, account, transport=ctx.threads_transport)
            quota = client.publishing_quota()
            usage = (quota.get("data") or [{}])[0]
            total = (usage.get("config") or {}).get("quota_total")
            if total is not None and usage.get("quota_usage", 0) >= total:
                raise ThreadsError("Threadsの24時間投稿上限に到達しています", rate_limited=True)
            container = post["external_container_id"]
            if not container:
                container = client.create_container(post["text"])
                with tx(conn):
                    conn.execute("UPDATE posts SET external_container_id=?, updated_at=? WHERE id=?",
                                 (container, now_iso(), post["id"]))
            if jobs.cancel_requested(conn, job["id"]):
                return _not_published(ctx, post, "公開前に取消されました", status="cancelled")
            media_id = client.publish_container(container)
            permalink = client.permalink(media_id)
        else:
            res = ctx.dry.publish(post["text"], fail=consume_flag(conn, "publish_error") or consume_flag(conn, "publish_unknown"))
            container, media_id, permalink = res.container_id, res.post_id, res.permalink
    except ThreadsError as e:
        if e.outcome_unknown:
            with tx(conn):
                conn.execute("UPDATE posts SET status='unknown', last_error=?, updated_at=? WHERE id=?",
                             (str(e), now_iso(), post["id"]))
                emit(conn, post["account_id"], "post.unknown", f"公開結果が不明です（自動照会します）: {e}",
                     severity="error", post_id=post["id"])
            _record_attempt(ctx, post["id"], "publish", "unknown", str(e))
            jobs.enqueue(conn, post["account_id"], "reconcile_post", f"reconcile:{post['id']}:1",
                         now() + timedelta(minutes=3), post_id=post["id"], payload={"round": 1}, max_attempts=1)
            return {"status": "unknown"}
        if e.auth:
            with tx(conn):
                conn.execute("UPDATE accounts SET connection_status='expired', connection_error=?, connection_checked_at=?"
                             " WHERE id=?", (str(e), now_iso(), account["id"]))
        idea_bank.release(conn, post["id"])
        with tx(conn):
            conn.execute("UPDATE posts SET status='failed', last_error=?, updated_at=? WHERE id=?",
                         (str(e), now_iso(), post["id"]))
            emit(conn, post["account_id"], "post.failed", f"公開に失敗しました: {e}", severity="error", post_id=post["id"])
        _record_attempt(ctx, post["id"], "publish", "error", str(e))
        raise
    _mark_published(ctx, post, container, media_id, permalink, live=live)
    return {"status": "published", "external_post_id": media_id, "live": live}


def _not_published(ctx: Ctx, post: dict, reason: str, status: str = "skipped") -> dict:
    idea_bank.release(ctx.conn, post["id"])
    with tx(ctx.conn):
        ctx.conn.execute("UPDATE posts SET status=?, last_error=?, updated_at=? WHERE id=?",
                         (status, reason, now_iso(), post["id"]))
        emit(ctx.conn, post["account_id"], "post.not_published", reason, severity="warning", post_id=post["id"])
    return {"skipped": reason}


def _mark_published(ctx: Ctx, post: dict, container: str | None, media_id: str, permalink: str | None, *,
                    live: bool) -> None:
    conn = ctx.conn
    ts = now()
    with tx(conn):
        conn.execute(
            "UPDATE posts SET status='published', external_container_id=COALESCE(?, external_container_id),"
            " external_post_id=?, permalink=?, published_at=?, last_error=NULL, updated_at=? WHERE id=?",
            (container, media_id, permalink, iso(ts), iso(ts), post["id"]))
        emit(conn, post["account_id"], "post.published",
             "Threadsに公開しました" if live else "テスト公開（実際には投稿していません）", severity="success",
             post_id=post["id"], payload={"external_post_id": media_id, "live": live})
    _record_attempt(ctx, post["id"], "publish", "ok", {"external_post_id": media_id, "live": live})
    idea_bank.mark_used(conn, post["id"])
    s, _ = get_settings(conn, post["account_id"])
    for h in s.improvement.observation_hours:
        jobs.enqueue(conn, post["account_id"], "collect_metrics", f"metrics:{post['id']}:{h}", ts + timedelta(hours=h),
                     post_id=post["id"], payload={"bucket_hours": h}, max_attempts=4)


def reconcile_post(ctx: Ctx, job: dict) -> dict:
    """Find out whether an 'unknown' publish actually happened."""
    conn = ctx.conn
    post = row(conn.execute("SELECT * FROM posts WHERE id=?", (job["post_id"],)).fetchone())
    if post is None or post["status"] != "unknown":
        return {"skipped": "not unknown"}
    account = get_account(conn, post["account_id"])
    s, _ = get_settings(conn, account["id"])
    rnd = int(job["payload"].get("round", 1))
    if live_enabled(ctx, account, s) and not post["is_test"]:
        client = ThreadsClient(ctx.cfg, account, transport=ctx.threads_transport)
        target = normalize_text(post["text"] or "")
        for item in client.recent_posts(limit=25):
            if normalize_text(item.get("text") or "") == target:
                _mark_published(ctx, post, None, str(item["id"]), item.get("permalink"), live=True)
                return {"resolved": "published", "external_post_id": item["id"]}
    else:
        # dry-run never actually posts, so an unknown dry-run publish is known to be unpublished
        with tx(conn):
            conn.execute("UPDATE posts SET status='failed', last_error=?, updated_at=? WHERE id=?",
                         ("照会の結果、公開されていませんでした（テスト）", now_iso(), post["id"]))
            emit(conn, post["account_id"], "post.reconciled", "照会の結果、公開されていませんでした（テスト）",
                 severity="warning", post_id=post["id"])
        idea_bank.release(conn, post["id"])
        return {"resolved": "not_published"}
    if rnd < 3:
        jobs.enqueue(conn, post["account_id"], "reconcile_post", f"reconcile:{post['id']}:{rnd + 1}",
                     now() + timedelta(minutes=10 * rnd), post_id=post["id"], payload={"round": rnd + 1}, max_attempts=1)
        return {"resolved": None, "next_round": rnd + 1}
    with tx(conn):
        emit(conn, post["account_id"], "post.needs_attention",
             "公開結果を確認できません。Threadsアプリで投稿の有無を確認し、管理画面で状態を確定してください",
             severity="error", post_id=post["id"])
    return {"resolved": None, "needs_human": True}


def resolve_unknown_manually(ctx: Ctx, account_id: str, post_id: int, outcome: str, actor: str,
                             external_post_id: str | None = None) -> dict:
    from .store import audit
    conn = ctx.conn
    post = row(conn.execute("SELECT * FROM posts WHERE id=? AND account_id=?", (post_id, account_id)).fetchone())
    if post is None or post["status"] != "unknown":
        from .store import Conflict
        raise Conflict("結果不明の投稿ではありません")
    if outcome == "published":
        _mark_published(ctx, post, None, external_post_id or f"manual-{post_id}", None, live=not post["is_test"])
    else:
        idea_bank.release(conn, post_id)
        with tx(conn):
            conn.execute("UPDATE posts SET status='failed', last_error=?, updated_at=? WHERE id=?",
                         ("手動確認：公開されていない", now_iso(), post_id))
    with tx(conn):
        audit(conn, account_id, actor, "post.resolve_unknown", f"post:{post_id}", {"outcome": outcome})
    return {"status": "published" if outcome == "published" else "failed"}


def collect_metrics(ctx: Ctx, job: dict) -> dict:
    conn = ctx.conn
    post = row(conn.execute("SELECT * FROM posts WHERE id=?", (job["post_id"],)).fetchone())
    if post is None or post["status"] != "published":
        return {"skipped": "not published"}
    bucket = int(job["payload"]["bucket_hours"])
    account = get_account(conn, post["account_id"])
    s, _ = get_settings(conn, account["id"])
    try:
        if post["is_test"]:
            p = dict(post)
            p["slot_local"] = local_slot(post)
            values = ctx.dry.insights(p, bucket, fail=consume_flag(conn, "metrics_error"))
        else:
            values = ThreadsClient(ctx.cfg, account, transport=ctx.threads_transport).insights(post["external_post_id"])
    except ThreadsError as e:
        final = job["attempts"] >= job["max_attempts"]
        _save_metrics(conn, post, bucket, "failed", {}, str(e))
        if final:
            with tx(conn):
                emit(conn, post["account_id"], "metrics.failed", f"実績取得に失敗（{bucket}時間後）: {e}", severity="error",
                     post_id=post["id"])
        raise
    status = "ok" if any(v is not None for v in values.values()) else "unavailable"
    _save_metrics(conn, post, bucket, status, values, None)
    with tx(conn):
        emit(conn, post["account_id"], "metrics.collected", f"実績を取得（{bucket}時間後）", post_id=post["id"],
             payload={"bucket_hours": bucket, **{k: v for k, v in values.items() if v is not None}})
    return {"bucket_hours": bucket, "status": status}


def _save_metrics(conn, post: dict, bucket: int, status: str, v: dict, error: str | None) -> None:
    with tx(conn):
        existing = conn.execute("SELECT status FROM metrics WHERE post_id=? AND bucket_hours=?",
                                (post["id"], bucket)).fetchone()
        if existing and existing["status"] == "ok" and status != "ok":
            return   # never overwrite good data with a failure
        conn.execute(
            "INSERT INTO metrics(post_id, account_id, bucket_hours, status, views, likes, replies, reposts, quotes, shares,"
            " error, observed_at, is_test) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(post_id, bucket_hours) DO UPDATE SET status=excluded.status, views=excluded.views,"
            " likes=excluded.likes, replies=excluded.replies, reposts=excluded.reposts, quotes=excluded.quotes,"
            " shares=excluded.shares, error=excluded.error, observed_at=excluded.observed_at",
            (post["id"], post["account_id"], bucket, status, v.get("views"), v.get("likes"), v.get("replies"),
             v.get("reposts"), v.get("quotes"), v.get("shares"), error, now_iso(), post["is_test"]))


def check_connection(ctx: Ctx, account_id: str) -> dict:
    account = get_account(ctx.conn, account_id)
    client = ThreadsClient(ctx.cfg, account, transport=ctx.threads_transport)
    if not client.configured:
        status, err = "not_configured", "ThreadsユーザーIDまたはトークン環境変数が未設定"
    else:
        try:
            me = client.me()
            status, err = "connected", None
            if account.get("external_user_id") and str(me.get("id")) != str(account["external_user_id"]):
                status, err = "error", "トークンのユーザーIDが設定と一致しません"
        except ThreadsError as e:
            status, err = ("expired" if e.auth else "error"), str(e)
    with tx(ctx.conn):
        ctx.conn.execute("UPDATE accounts SET connection_status=?, connection_error=?, connection_checked_at=? WHERE id=?",
                         (status, err, now_iso(), account_id))
        emit(ctx.conn, account_id, "connection.checked", f"Threads接続確認: {status}",
             severity="success" if status == "connected" else "warning", payload={"status": status})
    return {"status": status, "error": err, "checked_at": now_iso(), "detail": dumps({})}
