"""Idea bank: store, select (with reservation), release, mark used, refill, derive."""

from __future__ import annotations

import random
import sqlite3
from datetime import timedelta

from pydantic import BaseModel, Field

from .db import row, rows, tx
from .settings import AccountSettingsModel
from .store import Conflict, NotFound, audit, emit
from .timeutil import iso, now, now_iso

EDITABLE_STATUSES = {"draft", "ready", "held", "retired"}


class IdeaIn(BaseModel):
    theme: str = Field(min_length=1, max_length=60)
    pain: str = Field("", max_length=200)
    appeal: str = Field("", max_length=60)
    angle: str = Field("", max_length=200)
    notes: str = Field("", max_length=1000)
    status: str = Field("ready", pattern="^(draft|ready|held|retired)$")


def create(conn: sqlite3.Connection, account_id: str, data: IdeaIn, *, actor: str, origin: str = "manual",
           parent_idea_id: int | None = None, source_post_id: int | None = None, is_test: bool = False) -> dict:
    ts = now_iso()
    with tx(conn):
        cur = conn.execute(
            "INSERT INTO ideas(account_id, theme, pain, appeal, angle, notes, parent_idea_id, source_post_id, origin,"
            " status, is_test, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (account_id, data.theme, data.pain, data.appeal, data.angle, data.notes, parent_idea_id, source_post_id,
             origin, data.status, int(is_test), ts, ts))
        iid = int(cur.lastrowid)
        audit(conn, account_id, actor, "idea.create", f"idea:{iid}", {"origin": origin, "theme": data.theme})
        emit(conn, account_id, "idea.created", f"ネタを追加: {data.theme}／{data.angle or data.pain}",
             payload={"idea_id": iid, "origin": origin})
    return get(conn, account_id, iid)


def get(conn: sqlite3.Connection, account_id: str, idea_id: int) -> dict:
    r = row(conn.execute("SELECT * FROM ideas WHERE id=? AND account_id=?", (idea_id, account_id)).fetchone())
    if r is None:
        raise NotFound(f"idea {idea_id}")
    return r


def detail(conn: sqlite3.Connection, account_id: str, idea_id: int) -> dict:
    d = get(conn, account_id, idea_id)
    d["posts"] = rows(conn.execute(
        "SELECT p.id, p.status, p.slot_at, p.published_at, p.external_post_id, p.text, m.views, m.likes, m.replies,"
        " m.reposts, m.quotes, m.status metrics_status, m.observed_at FROM posts p"
        " LEFT JOIN metrics m ON m.post_id=p.id AND m.bucket_hours=(SELECT MAX(bucket_hours) FROM metrics WHERE post_id=p.id)"
        " WHERE p.idea_id=? AND p.account_id=? ORDER BY p.slot_at DESC LIMIT 50", (idea_id, account_id)).fetchall())
    d["children"] = rows(conn.execute(
        "SELECT id, theme, angle, status, origin, created_at FROM ideas WHERE parent_idea_id=? AND account_id=?",
        (idea_id, account_id)).fetchall())
    d["history"] = rows(conn.execute(
        "SELECT actor, action, detail_json, created_at FROM audit_log WHERE account_id=? AND target=? ORDER BY id DESC LIMIT 50",
        (account_id, f"idea:{idea_id}")).fetchall())
    return d


def list_ideas(conn: sqlite3.Connection, account_id: str, *, status: str | None = None, theme: str | None = None,
               q: str | None = None, limit: int = 50, offset: int = 0) -> dict:
    where, params = ["account_id=?"], [account_id]
    if status:
        where.append("status=?")
        params.append(status)
    if theme:
        where.append("theme=?")
        params.append(theme)
    if q:
        where.append("(theme LIKE ? OR pain LIKE ? OR angle LIKE ? OR notes LIKE ?)")
        params += [f"%{q}%"] * 4
    w = " AND ".join(where)
    total = conn.execute(f"SELECT COUNT(*) c FROM ideas WHERE {w}", params).fetchone()["c"]
    items = rows(conn.execute(f"SELECT * FROM ideas WHERE {w} ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?",
                              [*params, limit, offset]).fetchall())
    counts = {r["status"]: r["c"] for r in conn.execute(
        "SELECT status, COUNT(*) c FROM ideas WHERE account_id=? GROUP BY status", (account_id,))}
    return {"items": items, "total": total, "counts": counts, "limit": limit, "offset": offset}


def update(conn: sqlite3.Connection, account_id: str, idea_id: int, data: IdeaIn, *, actor: str,
           expected_updated_at: str | None = None) -> dict:
    with tx(conn):
        cur = get(conn, account_id, idea_id)
        if expected_updated_at and cur["updated_at"] != expected_updated_at:
            raise Conflict("このネタは他の操作で更新されています。再読み込みしてください")
        if cur["status"] == "reserved":
            raise Conflict("投稿生成で使用中のネタは編集できません")
        status = data.status
        if cur["status"] == "used" and status == "ready":
            status = "used"   # keep usage state; reuse interval governs reuse
        conn.execute(
            "UPDATE ideas SET theme=?, pain=?, appeal=?, angle=?, notes=?, status=?, updated_at=? WHERE id=?",
            (data.theme, data.pain, data.appeal, data.angle, data.notes, status, now_iso(), idea_id))
        audit(conn, account_id, actor, "idea.update", f"idea:{idea_id}",
              {"before": {k: cur[k] for k in ("theme", "pain", "appeal", "angle", "status")},
               "after": data.model_dump()})
    return get(conn, account_id, idea_id)


def set_status(conn: sqlite3.Connection, account_id: str, idea_id: int, status: str, *, actor: str) -> dict:
    if status not in ("ready", "held", "retired"):
        raise Conflict("変更できない状態です")
    with tx(conn):
        cur = get(conn, account_id, idea_id)
        if cur["status"] == "reserved":
            raise Conflict("投稿生成で使用中のネタです。生成完了後に操作してください")
        new = "used" if status == "ready" and cur["use_count"] > 0 else status
        conn.execute("UPDATE ideas SET status=?, updated_at=? WHERE id=?", (new, now_iso(), idea_id))
        audit(conn, account_id, actor, f"idea.{status}", f"idea:{idea_id}", {"from": cur["status"], "to": new})
    return get(conn, account_id, idea_id)


# ------------------------------------------------------------------ selection

def reserve(conn: sqlite3.Connection, account_id: str, post_id: int, s: AccountSettingsModel, *,
            preferred_theme: str | None, forced_theme: bool, avoid_themes: list[str], include_test: bool,
            rng: random.Random) -> dict | None:
    """Atomically pick and reserve one idea for a post. Returns None if nothing suitable."""
    cutoff = iso(now() - timedelta(days=s.ideas.reuse_interval_days))
    with tx(conn):
        existing = row(conn.execute("SELECT * FROM ideas WHERE reserved_by_post_id=? AND status='reserved'",
                                    (post_id,)).fetchone())
        if existing:
            return existing
        cands = rows(conn.execute(
            "SELECT * FROM ideas WHERE account_id=? AND is_test=? AND ("
            " status='ready' OR (status='used' AND (last_used_at IS NULL OR last_used_at < ?)))",
            (account_id, int(include_test), cutoff)).fetchall())
        cands = [c for c in cands if c["theme"] in s.content.themes]
        if forced_theme and preferred_theme:
            cands = [c for c in cands if c["theme"] == preferred_theme]
        streak_n = s.checks.theme_max_consecutive
        if len(avoid_themes) >= streak_n and len(set(avoid_themes[:streak_n])) == 1 and not forced_theme:
            cands = [c for c in cands if c["theme"] != avoid_themes[0]] or cands
        if not cands:
            return None
        fresh = [c for c in cands if c["use_count"] == 0]
        if fresh and rng.random() < max(s.ideas.new_theme_share, 0.5 if len(fresh) == len(cands) else 0):
            pool = fresh
        else:
            pool = cands
        if preferred_theme:
            pref = [c for c in pool if c["theme"] == preferred_theme]
            pool = pref or pool
        pool.sort(key=lambda c: (c["use_count"], c["last_used_at"] or "", c["id"]))
        pick = pool[0]
        cur = conn.execute(
            "UPDATE ideas SET status='reserved', reserved_by_post_id=?, reserved_at=?, updated_at=?"
            " WHERE id=? AND status IN ('ready','used')", (post_id, now_iso(), now_iso(), pick["id"]))
        if cur.rowcount != 1:
            return None
        pick["prev_status"] = pick["status"]
        pick["status"] = "reserved"
        return pick


def release(conn: sqlite3.Connection, post_id: int) -> None:
    """Generation/publish failed or was cancelled: idea is NOT consumed."""
    with tx(conn):
        conn.execute(
            "UPDATE ideas SET status=CASE WHEN use_count>0 THEN 'used' ELSE 'ready' END, reserved_by_post_id=NULL,"
            " reserved_at=NULL, updated_at=? WHERE reserved_by_post_id=? AND status='reserved'", (now_iso(), post_id))


def mark_used(conn: sqlite3.Connection, post_id: int) -> None:
    with tx(conn):
        conn.execute(
            "UPDATE ideas SET status='used', use_count=use_count+1, last_used_at=?, last_post_id=?,"
            " reserved_by_post_id=NULL, reserved_at=NULL, updated_at=? WHERE reserved_by_post_id=?",
            (now_iso(), post_id, now_iso(), post_id))


def ready_count(conn: sqlite3.Connection, account_id: str, include_test: bool) -> int:
    return conn.execute("SELECT COUNT(*) c FROM ideas WHERE account_id=? AND status='ready' AND is_test=?",
                        (account_id, int(include_test))).fetchone()["c"]


def created_today(conn: sqlite3.Connection, account_id: str, origins: tuple[str, ...]) -> int:
    since = iso(now() - timedelta(hours=24))
    q = f"SELECT COUNT(*) c FROM ideas WHERE account_id=? AND created_at>=? AND origin IN ({','.join('?' * len(origins))})"
    return conn.execute(q, (account_id, since, *origins)).fetchone()["c"]
