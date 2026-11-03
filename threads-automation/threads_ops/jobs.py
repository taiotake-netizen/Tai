"""Durable job queue on SQLite.

- enqueue() is idempotent via a UNIQUE idempotency_key (scheduler ticks, restarts and double clicks are safe).
- claim() takes a lease inside BEGIN IMMEDIATE, so two workers can never run the same job.
- Expired leases are recovered by recover_expired(); publish jobs are NOT blindly re-run (see worker).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from .db import dumps, loads, row, rows, tx
from .store import Conflict, NotFound, audit, emit
from .timeutil import iso, now, now_iso

AI_KINDS = {"generate_post", "analyze", "daily_report", "weekly_report", "assistant", "refill_ideas"}
CANCELLABLE_RUNNING = {"generate_post", "analyze", "daily_report", "weekly_report", "assistant", "refill_ideas",
                       "collect_metrics", "reconcile_post"}
LEASE_SECONDS = 300

JOB_LABELS = {
    "generate_post": "投稿生成・チェック",
    "publish_post": "投稿公開",
    "collect_metrics": "実績取得",
    "reconcile_post": "結果不明の照会",
    "analyze": "分析・自動改善",
    "daily_report": "日次レポート",
    "weekly_report": "週次レポート",
    "refill_ideas": "ネタ補充",
    "assistant": "AI補助",
    "check_connection": "接続確認",
}


def enqueue(conn: sqlite3.Connection, account_id: str, kind: str, key: str, run_at: datetime, *,
            payload: dict | None = None, post_id: int | None = None, max_attempts: int = 3) -> tuple[int, bool]:
    """Returns (job_id, created). Existing job with the same key is returned unchanged."""
    ts = now_iso()
    with tx(conn):
        existing = conn.execute("SELECT id FROM jobs WHERE idempotency_key=?", (key,)).fetchone()
        if existing:   # checked first so repeated scheduler ticks don't burn AUTOINCREMENT ids
            return int(existing["id"]), False
        cur = conn.execute(
            "INSERT OR IGNORE INTO jobs(account_id, kind, idempotency_key, status, run_at, payload_json, post_id,"
            " max_attempts, created_at, updated_at) VALUES (?,?,?,'queued',?,?,?,?,?,?)",
            (account_id, kind, key, iso(run_at), dumps(payload or {}), post_id, max_attempts, ts, ts),
        )
        if cur.rowcount:
            return int(cur.lastrowid), True
        r = conn.execute("SELECT id FROM jobs WHERE idempotency_key=?", (key,)).fetchone()
        return int(r["id"]), False


def claim(conn: sqlite3.Connection, worker_id: str, *, max_ai_concurrency: int = 1) -> dict | None:
    t = now()
    with tx(conn):
        running_ai = conn.execute(
            f"SELECT COUNT(*) c FROM jobs WHERE status IN ('running','cancel_requested') AND kind IN ({_in(AI_KINDS)})",
            tuple(AI_KINDS)).fetchone()["c"]
        exclude = tuple(AI_KINDS) if running_ai >= max_ai_concurrency else ()
        q = "SELECT * FROM jobs WHERE status='queued' AND run_at<=?"
        params: list = [iso(t)]
        if exclude:
            q += f" AND kind NOT IN ({_in(exclude)})"
            params += list(exclude)
        q += " ORDER BY run_at, id LIMIT 1"
        j = row(conn.execute(q, params).fetchone())
        if j is None:
            return None
        conn.execute(
            "UPDATE jobs SET status='running', attempts=attempts+1, lease_owner=?, lease_until=?, started_at=?,"
            " updated_at=? WHERE id=? AND status='queued'",
            (worker_id, iso(t + timedelta(seconds=LEASE_SECONDS)), iso(t), iso(t), j["id"]),
        )
        j["attempts"] += 1
        j["status"] = "running"
        j["payload"] = loads(j["payload_json"], {})
        emit(conn, j["account_id"], "job.started", f"{JOB_LABELS.get(j['kind'], j['kind'])}を開始", job_id=j["id"],
             post_id=j["post_id"], payload={"kind": j["kind"], "attempt": j["attempts"]})
    return j


def _in(xs) -> str:
    return ",".join("?" for _ in xs)


def heartbeat(conn: sqlite3.Connection, job_id: int, worker_id: str) -> None:
    with tx(conn):
        conn.execute("UPDATE jobs SET lease_until=?, updated_at=? WHERE id=? AND lease_owner=?",
                     (iso(now() + timedelta(seconds=LEASE_SECONDS)), now_iso(), job_id, worker_id))


def cancel_requested(conn: sqlite3.Connection, job_id: int) -> bool:
    r = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
    return r is not None and r["status"] == "cancel_requested"


def finish(conn: sqlite3.Connection, job: dict, status: str, *, error: str | None = None, result: dict | None = None,
           retry_in: timedelta | None = None) -> None:
    """status: succeeded | failed | cancelled. retry_in re-queues a failed job if attempts remain."""
    t = now()
    label = JOB_LABELS.get(job["kind"], job["kind"])
    with tx(conn):
        cur = row(conn.execute("SELECT status, attempts, max_attempts FROM jobs WHERE id=?", (job["id"],)).fetchone())
        if cur is None:
            return
        if cur["status"] == "cancel_requested" and status != "succeeded":
            status = "cancelled"
        if status == "failed" and retry_in is not None and cur["attempts"] < cur["max_attempts"]:
            conn.execute(
                "UPDATE jobs SET status='queued', run_at=?, lease_owner=NULL, lease_until=NULL, last_error=?,"
                " updated_at=? WHERE id=?", (iso(t + retry_in), (error or "")[:1000], iso(t), job["id"]))
            emit(conn, job["account_id"], "job.retry_scheduled", f"{label}が失敗、再試行を予約: {error}",
                 severity="warning", job_id=job["id"], post_id=job.get("post_id"),
                 payload={"kind": job["kind"], "attempt": cur["attempts"]})
            return
        conn.execute(
            "UPDATE jobs SET status=?, lease_owner=NULL, lease_until=NULL, last_error=?, result_json=?, finished_at=?,"
            " updated_at=? WHERE id=?",
            (status, (error or "")[:1000] or None, dumps(result) if result is not None else None, iso(t), iso(t),
             job["id"]))
        sev = {"succeeded": "success", "failed": "error", "cancelled": "warning"}[status]
        msg = {"succeeded": "完了", "failed": f"失敗: {error}", "cancelled": "取消完了"}[status]
        emit(conn, job["account_id"], f"job.{status}", f"{label} {msg}", severity=sev, job_id=job["id"],
             post_id=job.get("post_id"), payload={"kind": job["kind"], **({"result": result} if result else {})})


def recover_expired(conn: sqlite3.Connection) -> list[dict]:
    """Return jobs whose lease expired (worker died). Caller decides how to recover each kind."""
    with tx(conn):
        expired = rows(conn.execute(
            "SELECT * FROM jobs WHERE status IN ('running','cancel_requested') AND lease_until < ?",
            (now_iso(),)).fetchall())
        for j in expired:
            if j["kind"] == "publish_post":
                conn.execute("UPDATE jobs SET status='failed', last_error=?, lease_owner=NULL, lease_until=NULL,"
                             " finished_at=?, updated_at=? WHERE id=?",
                             ("ワーカー停止により公開結果が不明", now_iso(), now_iso(), j["id"]))
            elif j["status"] == "cancel_requested":
                conn.execute("UPDATE jobs SET status='cancelled', lease_owner=NULL, lease_until=NULL, finished_at=?,"
                             " updated_at=? WHERE id=?", (now_iso(), now_iso(), j["id"]))
            elif j["attempts"] < j["max_attempts"]:
                conn.execute("UPDATE jobs SET status='queued', lease_owner=NULL, lease_until=NULL, last_error=?,"
                             " updated_at=? WHERE id=?", ("ワーカー停止から復旧（再実行）", now_iso(), j["id"]))
            else:
                conn.execute("UPDATE jobs SET status='failed', last_error=?, lease_owner=NULL, lease_until=NULL,"
                             " finished_at=?, updated_at=? WHERE id=?",
                             ("ワーカー停止、再試行上限", now_iso(), now_iso(), j["id"]))
            emit(conn, j["account_id"], "job.lease_expired", f"{JOB_LABELS.get(j['kind'], j['kind'])}の実行中にワーカーが停止しました",
                 severity="warning", job_id=j["id"], post_id=j["post_id"], payload={"kind": j["kind"]})
    return expired


def get_job(conn: sqlite3.Connection, account_id: str, job_id: int) -> dict:
    j = row(conn.execute("SELECT * FROM jobs WHERE id=? AND account_id=?", (job_id, account_id)).fetchone())
    if j is None:
        raise NotFound(f"job {job_id}")
    return j


def request_cancel(conn: sqlite3.Connection, account_id: str, job_id: int, actor: str) -> dict:
    """Queued → cancelled now. Running → cancel_requested (worker stops at next safe point).
    A publish job that is already talking to Threads cannot be cancelled."""
    with tx(conn):
        j = get_job(conn, account_id, job_id)
        if j["status"] == "queued":
            conn.execute("UPDATE jobs SET status='cancelled', finished_at=?, updated_at=? WHERE id=?",
                         (now_iso(), now_iso(), job_id))
            if j["kind"] == "publish_post" and j["post_id"]:
                conn.execute("UPDATE posts SET status='cancelled', updated_at=? WHERE id=? AND status='scheduled'",
                             (now_iso(), j["post_id"]))
            outcome = {"result": "cancelled", "message": "待機中のジョブを取り消しました"}
        elif j["status"] == "running":
            if j["kind"] not in CANCELLABLE_RUNNING:
                raise Conflict("公開処理はThreadsとの通信中のため取り消せません。結果を確認してください")
            conn.execute("UPDATE jobs SET status='cancel_requested', updated_at=? WHERE id=?", (now_iso(), job_id))
            outcome = {"result": "cancel_requested", "message": "取消要求を受け付けました（処理の区切りで停止します）"}
        elif j["status"] == "cancel_requested":
            outcome = {"result": "cancel_requested", "message": "取消要求は受付済みです"}
        else:
            raise Conflict(f"状態 {j['status']} のジョブは取り消せません")
        audit(conn, account_id, actor, "job.cancel", f"job:{job_id}", outcome)
        emit(conn, account_id, "job.cancel_" + outcome["result"], outcome["message"], severity="warning",
             job_id=job_id, post_id=j["post_id"], payload={"kind": j["kind"]})
    return outcome


def retry(conn: sqlite3.Connection, account_id: str, job_id: int, actor: str) -> dict:
    with tx(conn):
        j = get_job(conn, account_id, job_id)
        if j["status"] not in ("failed", "cancelled"):
            raise Conflict(f"状態 {j['status']} のジョブは再試行できません")
        if j["kind"] == "publish_post":
            raise Conflict("公開ジョブは自動再試行しません。投稿の『結果照会』または『再予約』を使ってください")
        conn.execute(
            "UPDATE jobs SET status='queued', run_at=?, attempts=0, last_error=NULL, finished_at=NULL, updated_at=?"
            " WHERE id=?", (now_iso(), now_iso(), job_id))
        audit(conn, account_id, actor, "job.retry", f"job:{job_id}", {"kind": j["kind"]})
        emit(conn, account_id, "job.requeued", f"{JOB_LABELS.get(j['kind'], j['kind'])}を再試行キューに戻しました",
             job_id=job_id, post_id=j["post_id"], payload={"kind": j["kind"]})
    return {"result": "queued"}
