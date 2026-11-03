"""HTTP API (v1) consumed by the AI CONTROL CENTER server-side adapter.

Auth: `Authorization: Bearer <THREADS_OPS_API_TOKEN>` (server-to-server only; never sent to browsers),
`X-Account-Scope: acc1,acc2` limits which accounts the calling user may see (enforced on every route),
`X-Actor: <user>` is recorded in the audit log. Errors: {"error": {"code", "message", "details"}}.
The machine-readable spec is served at /openapi.json and exported to docs/openapi.json.
"""

from __future__ import annotations

import hmac
import json
from datetime import timedelta
from typing import Any

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from . import API_VERSION, analyzer, assistant, jobs, publishing
from . import ideas as idea_bank
from . import reports as report_mod
from .api_views import overview, runtime
from .context import Ctx
from .db import dumps, loads, row, rows, tx
from .generator import _record_attempt
from .llm import AIUnavailable
from .quality import rule_check
from .settings import AccountSettingsModel, PolicyViolation
from .store import (
    Conflict,
    NotFound,
    active_policy,
    audit,
    emit,
    get_account,
    get_settings,
    get_state,
    is_test_scope,
    list_accounts,
    update_settings,
)
from .timeutil import iso, now, now_iso, parse


class Principal(BaseModel):
    actor: str
    scope: set[str] | None   # None = all accounts


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: Any = None):
        self.status, self.code, self.message, self.details = status, code, message, details


def _err(status: int, code: str, message: str, details: Any = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "details": details}})


# ------------------------------------------------------------------ request bodies

class ToggleIn(BaseModel):
    enabled: bool


class StopIn(BaseModel):
    mode: str = Field(pattern="^(pause_schedule|cancel_queued)$")


class SettingsPatchIn(BaseModel):
    expected_version: int
    patch: dict


class ApproveIn(BaseModel):
    publish_at: str | None = None


class EditTextIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    expected_updated_at: str


class ResolveIn(BaseModel):
    outcome: str = Field(pattern="^(published|not_published)$")
    external_post_id: str | None = Field(None, max_length=64)


class IdeaPatchIn(idea_bank.IdeaIn):
    expected_updated_at: str | None = None


class IdeaStatusIn(BaseModel):
    status: str = Field(pattern="^(ready|held|retired)$")


class RollbackIn(BaseModel):
    version: int = Field(ge=1)


class RegenerateIn(BaseModel):
    kind: str = Field(pattern="^(daily|weekly)$")
    period_start: str


class IngestEventIn(BaseModel):
    event_id: str = Field(min_length=8, max_length=64)
    source_system: str = Field(min_length=1, max_length=40)
    event_type: str = Field(pattern=r"^[a-z_]+(\.[a-z_]+)*$", max_length=60)
    occurred_at: str
    severity: str = Field("info", pattern="^(info|success|warning|error)$")
    message: str = Field(max_length=500)
    post_id: int | None = None
    payload: dict = Field(default_factory=dict)


class ScenarioIn(BaseModel):
    name: str = Field(pattern="^(generate_now|publish_now|fail_publish|unknown_publish|metrics_fail|advance_metrics|run_analysis|run_reports|disconnect|reconnect)$")


def _deep_merge(base: dict, patch: dict) -> dict:
    out = dict(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


# ------------------------------------------------------------------ app

def create_app(ctx: Ctx) -> FastAPI:
    cfg = ctx.cfg
    if cfg.is_production and not cfg.api_token:
        raise RuntimeError("THREADS_OPS_API_TOKEN is required in production")
    app = FastAPI(title="threads-ops API", version=API_VERSION,
                  description="Threads automation engine API for AI CONTROL CENTER. All times are UTC ISO-8601.")
    conn = ctx.conn
    # NOTE: all route handlers are `async def` on purpose: they run on the single event-loop thread, so the shared
    # SQLite connection is never used by two threads at once (transactions stay isolated).

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, e: ApiError):
        return _err(e.status, e.code, e.message, e.details)

    @app.exception_handler(NotFound)
    async def _nf(_: Request, e: NotFound):
        return _err(404, "not_found", "対象が見つかりません", str(e))

    @app.exception_handler(Conflict)
    async def _cf(_: Request, e: Conflict):
        return _err(409, "conflict", str(e))

    @app.exception_handler(PolicyViolation)
    async def _pv(_: Request, e: PolicyViolation):
        return _err(422, "policy_violation", str(e))

    @app.exception_handler(ValidationError)
    async def _ve(_: Request, e: ValidationError):
        return _err(422, "validation_error", "入力内容が不正です", json.loads(e.json(include_url=False, include_context=False)))

    @app.exception_handler(AIUnavailable)
    async def _ai(_: Request, e: AIUnavailable):
        return _err(503, f"ai_{e.code}", str(e))

    @app.middleware("http")
    async def _demo_offline(request: Request, call_next):
        if cfg.is_demo and request.url.path.startswith("/v1/") and request.url.path != "/v1/demo/scenario":
            st = get_state(conn, "demo_offline")
            if st and parse(st["value"]["until"]) > now():
                return _err(503, "demo_disconnected", "（デモ）接続断を再現中です")
        return await call_next(request)

    def principal(authorization: str | None = Header(None), x_account_scope: str | None = Header(None),
                  x_actor: str | None = Header(None)) -> Principal:
        if cfg.api_token:
            supplied = (authorization or "").removeprefix("Bearer ").strip()
            if not supplied or not hmac.compare_digest(supplied, cfg.api_token):
                raise ApiError(401, "unauthorized", "認証が必要です")
        elif cfg.is_production:
            raise ApiError(401, "unauthorized", "認証が必要です")
        scope: set[str] | None
        raw = (x_account_scope or "").strip()
        if raw == "*":
            scope = None
        else:
            scope = {s.strip() for s in raw.split(",") if s.strip()}
        actor = (x_actor or "api").strip()[:80] or "api"
        return Principal(actor=actor, scope=scope)

    def account_for(account_id: str, p: Principal) -> dict:
        if p.scope is not None and account_id not in p.scope:
            raise NotFound(f"account {account_id}")   # do not reveal existence
        return get_account(conn, account_id)

    # ---------------------------------------------------------- meta
    @app.get("/v1/health", tags=["meta"])
    async def health():
        try:
            conn.execute("SELECT 1").fetchone()
            db_ok = True
        except Exception:  # noqa: BLE001
            db_ok = False
        rt = runtime(ctx)
        return {"status": "ok" if db_ok else "degraded", "api_version": API_VERSION, "app_env": cfg.app_env,
                "publish_mode": cfg.publish_mode, "llm": ctx.llm.availability(), "db": db_ok, **rt, "time": now_iso()}

    @app.get("/v1/accounts", tags=["accounts"])
    async def accounts(p: Principal = Depends(principal)):
        return {"items": [{k: a[k] for k in ("id", "display_name", "platform", "data_scope", "connection_status")}
                          for a in list_accounts(conn, p.scope)]}

    @app.get("/v1/accounts/{account_id}/capabilities", tags=["meta"])
    async def capabilities(account_id: str, p: Principal = Depends(principal)):
        account = account_for(account_id, p)
        s, _ = get_settings(conn, account_id)
        llm = ctx.llm.availability()
        live = publishing.live_enabled(ctx, account, s)

        def cap(ok: bool, reason: str | None = None):
            return {"enabled": ok, "reason": None if ok else reason}
        return {
            "api_version": API_VERSION,
            "actions": {
                "autopilot.toggle": cap(True),
                "improvement.toggle": cap(True),
                "stop.pause_schedule": cap(True),
                "stop.cancel_queued": cap(True),
                "job.cancel": cap(True), "job.retry": cap(True),
                "post.approve": cap(True), "post.cancel": cap(True), "post.edit_text": cap(True),
                "post.resolve_unknown": cap(True),
                "post.delete_published": cap(False, "公開済み投稿の削除には対応していません（Threadsアプリで行ってください）"),
                "policy.rollback": cap(True), "experiment.stop": cap(True),
                "ideas.edit": cap(True),
                "reports.regenerate": cap(True),
                "settings.update": cap(True),
                "assistant.summary": cap(llm["available"], llm["reason"]),
                "assistant.draft": cap(llm["available"], llm["reason"]),
                "assistant.improvement": cap(llm["available"], llm["reason"]),
                "connection.check": cap(account["data_scope"] == "live", "デモ/テストアカウントはThreadsに接続しません"),
                "publish.live": cap(live, "本番投稿は無効です（PUBLISH_MODE=live と設定の両方が必要）"),
                "demo.scenarios": cap(cfg.is_demo, "デモ環境のみ"),
            },
        }

    @app.get("/v1/accounts/{account_id}/overview", tags=["status"])
    async def get_overview(account_id: str, p: Principal = Depends(principal)):
        account_for(account_id, p)
        return overview(ctx, account_id)

    # ---------------------------------------------------------- jobs
    @app.get("/v1/accounts/{account_id}/jobs", tags=["jobs"])
    async def list_jobs(account_id: str, status: str | None = None, limit: int = Query(50, ge=1, le=200),
                  before_id: int | None = None, p: Principal = Depends(principal)):
        account_for(account_id, p)
        q, params = "SELECT * FROM jobs WHERE account_id=?", [account_id]
        if status:
            q += " AND status=?"
            params.append(status)
        if before_id:
            q += " AND id<?"
            params.append(before_id)
        q += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        items = rows(conn.execute(q, params).fetchall())
        for j in items:
            j["payload"] = loads(j.pop("payload_json"), {})
            j["result"] = loads(j.pop("result_json"), None)
            j["label"] = jobs.JOB_LABELS.get(j["kind"], j["kind"])
        return {"items": items, "next_before_id": items[-1]["id"] if len(items) == limit else None}

    @app.post("/v1/accounts/{account_id}/jobs/{job_id}/cancel", tags=["jobs"])
    async def cancel_job(account_id: str, job_id: int, p: Principal = Depends(principal)):
        account_for(account_id, p)
        return jobs.request_cancel(conn, account_id, job_id, p.actor)

    @app.post("/v1/accounts/{account_id}/jobs/{job_id}/retry", tags=["jobs"])
    async def retry_job(account_id: str, job_id: int, p: Principal = Depends(principal)):
        account_for(account_id, p)
        return jobs.retry(conn, account_id, job_id, p.actor)

    # ---------------------------------------------------------- posts
    @app.get("/v1/accounts/{account_id}/posts", tags=["posts"])
    async def list_posts(account_id: str, view: str = Query("upcoming", pattern="^(upcoming|history|attention|all)$"),
                   limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), p: Principal = Depends(principal)):
        account_for(account_id, p)
        where = {
            "upcoming": "status IN ('planned','generating','awaiting_approval','scheduled','publishing')",
            "history": "status IN ('published','failed','skipped','cancelled','unknown')",
            "attention": "status IN ('unknown','awaiting_approval','failed')",
            "all": "1=1",
        }[view]
        order = "slot_at ASC" if view == "upcoming" else "COALESCE(published_at, slot_at) DESC"
        items = rows(conn.execute(
            f"SELECT p.*, (SELECT json_object('views',views,'likes',likes,'replies',replies,'reposts',reposts,'quotes',quotes,"
            f"'status',status,'bucket_hours',bucket_hours,'observed_at',observed_at) FROM metrics m WHERE m.post_id=p.id"
            f" ORDER BY bucket_hours DESC LIMIT 1) latest_metrics FROM posts p WHERE account_id=? AND {where}"
            f" ORDER BY {order} LIMIT ? OFFSET ?", (account_id, limit, offset)).fetchall())
        for it in items:
            it["check"] = loads(it.pop("check_json"), None)
            it["latest_metrics"] = loads(it["latest_metrics"], None)
        total = conn.execute(f"SELECT COUNT(*) c FROM posts WHERE account_id=? AND {where}", (account_id,)).fetchone()["c"]
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    @app.get("/v1/accounts/{account_id}/posts/{post_id}", tags=["posts"])
    async def get_post(account_id: str, post_id: int, p: Principal = Depends(principal)):
        account_for(account_id, p)
        post = row(conn.execute("SELECT * FROM posts WHERE id=? AND account_id=?", (post_id, account_id)).fetchone())
        if not post:
            raise NotFound(f"post {post_id}")
        post["check"] = loads(post.pop("check_json"), None)
        post["attempts"] = rows(conn.execute("SELECT * FROM post_attempts WHERE post_id=? ORDER BY id", (post_id,)).fetchall())
        post["metrics"] = rows(conn.execute("SELECT * FROM metrics WHERE post_id=? ORDER BY bucket_hours", (post_id,)).fetchall())
        post["jobs"] = rows(conn.execute("SELECT id, kind, status, run_at, attempts, last_error FROM jobs WHERE post_id=? ORDER BY id",
                                         (post_id,)).fetchall())
        return post

    def _post(account_id: str, post_id: int) -> dict:
        post = row(conn.execute("SELECT * FROM posts WHERE id=? AND account_id=?", (post_id, account_id)).fetchone())
        if not post:
            raise NotFound(f"post {post_id}")
        return post

    @app.post("/v1/accounts/{account_id}/posts/{post_id}/approve", tags=["posts"])
    async def approve(account_id: str, post_id: int, body: ApproveIn, p: Principal = Depends(principal)):
        account_for(account_id, p)
        s, _ = get_settings(conn, account_id)
        with tx(conn):
            post = _post(account_id, post_id)
            if post["status"] != "awaiting_approval":
                raise Conflict(f"承認待ちではありません（{post['status']}）")
            slot = parse(post["slot_at"])
            if body.publish_at:
                if post["origin"] == "schedule":
                    raise Conflict("定期枠の投稿は公開時刻を変更できません")
                slot = parse(body.publish_at)
            if slot < now() + timedelta(minutes=1):
                if post["origin"] == "schedule" and slot + timedelta(minutes=s.schedule.missed_grace_minutes) >= now():
                    slot = now()
                else:
                    raise Conflict("公開時刻が過去です。新しい公開時刻を指定してください")
            chk = loads(post["check_json"], {}) or {}
            if not chk.get("passed"):
                raise Conflict("品質チェックに合格していない投稿は承認できません")
            conn.execute("UPDATE posts SET status='scheduled', slot_at=?, updated_at=? WHERE id=?",
                         (iso(slot), now_iso(), post_id))
            audit(conn, account_id, p.actor, "post.approve", f"post:{post_id}", {"publish_at": iso(slot)})
            emit(conn, account_id, "post.approved", f"投稿を承認し予約しました（{iso(slot)}）", severity="success", post_id=post_id)
        jobs.enqueue(conn, account_id, "publish_post", f"publish:{post_id}:{iso(slot)}", slot, post_id=post_id, max_attempts=1)
        return {"status": "scheduled", "slot_at": iso(slot)}

    @app.patch("/v1/accounts/{account_id}/posts/{post_id}/text", tags=["posts"])
    async def edit_text(account_id: str, post_id: int, body: EditTextIn, p: Principal = Depends(principal)):
        account_for(account_id, p)
        s, _ = get_settings(conn, account_id)
        post = _post(account_id, post_id)
        if post["status"] != "awaiting_approval":
            raise Conflict("承認待ちの投稿だけ編集できます")
        if post["updated_at"] != body.expected_updated_at:
            raise Conflict("この投稿は他の操作で更新されています。再読み込みしてください")
        from .generator import recent_context
        recent = recent_context(ctx, account_id, s, post_id, bool(post["is_test"]))
        chk = rule_check(body.text, s, recent_texts=recent["texts"], recent_themes=[], recent_ctas=[],
                         theme=post["theme"], cta_key=post["cta_key"])
        with tx(conn):
            conn.execute("UPDATE posts SET text=?, check_json=?, updated_at=? WHERE id=?",
                         (body.text.strip(), dumps(chk.as_dict()), now_iso(), post_id))
            audit(conn, account_id, p.actor, "post.edit_text", f"post:{post_id}", {"passed": chk.passed})
        _record_attempt(ctx, post_id, "check", "ok" if chk.passed else "rejected", {"manual_edit": True, **chk.as_dict()})
        return {"check": chk.as_dict()}

    @app.post("/v1/accounts/{account_id}/posts/{post_id}/cancel", tags=["posts"])
    async def cancel_post(account_id: str, post_id: int, p: Principal = Depends(principal)):
        account_for(account_id, p)
        with tx(conn):
            post = _post(account_id, post_id)
            st = post["status"]
            if st == "published":
                raise Conflict("公開済みの投稿は取り消せません（削除はThreadsアプリで行ってください）")
            if st == "publishing":
                raise Conflict("Threadsへ公開処理中のため取り消せません。結果を確認してください")
            if st in ("failed", "skipped", "cancelled", "unknown"):
                raise Conflict(f"状態 {st} の投稿は取り消し対象ではありません")
            if st == "generating":
                j = conn.execute("SELECT id FROM jobs WHERE post_id=? AND kind='generate_post' AND status='running'",
                                 (post_id,)).fetchone()
                if j:
                    conn.execute("UPDATE jobs SET status='cancel_requested', updated_at=? WHERE id=?", (now_iso(), j["id"]))
                    audit(conn, account_id, p.actor, "post.cancel_requested", f"post:{post_id}", {})
                    emit(conn, account_id, "post.cancel_requested", "生成中の投稿に取消要求を出しました", severity="warning",
                         post_id=post_id)
                    return {"result": "cancel_requested", "message": "生成処理の区切りで停止します"}
            conn.execute("UPDATE posts SET status='cancelled', last_error=?, updated_at=? WHERE id=?",
                         ("ユーザーが取り消し", now_iso(), post_id))
            conn.execute("UPDATE jobs SET status='cancelled', finished_at=?, updated_at=? WHERE post_id=? AND status='queued'",
                         (now_iso(), now_iso(), post_id))
            audit(conn, account_id, p.actor, "post.cancel", f"post:{post_id}", {"from": st})
            emit(conn, account_id, "post.cancelled", "投稿予定を取り消しました", severity="warning", post_id=post_id)
        idea_bank.release(conn, post_id)
        return {"result": "cancelled", "message": "投稿予定を取り消しました"}

    @app.post("/v1/accounts/{account_id}/posts/{post_id}/resolve", tags=["posts"])
    async def resolve(account_id: str, post_id: int, body: ResolveIn, p: Principal = Depends(principal)):
        account_for(account_id, p)
        return publishing.resolve_unknown_manually(ctx, account_id, post_id, body.outcome, p.actor, body.external_post_id)

    # ---------------------------------------------------------- events
    @app.get("/v1/accounts/{account_id}/events", tags=["events"])
    async def events(account_id: str, after_seq: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
               p: Principal = Depends(principal)):
        account_for(account_id, p)
        if after_seq == 0:
            items = rows(conn.execute("SELECT * FROM events WHERE account_id=? ORDER BY seq DESC LIMIT ?",
                                      (account_id, limit)).fetchall())[::-1]
        else:
            items = rows(conn.execute("SELECT * FROM events WHERE account_id=? AND seq>? ORDER BY seq LIMIT ?",
                                      (account_id, after_seq, limit)).fetchall())
        for e in items:
            e["payload"] = loads(e.pop("payload_json"), {})
        latest = conn.execute("SELECT COALESCE(MAX(seq),0) s FROM events WHERE account_id=?", (account_id,)).fetchone()["s"]
        cursor = items[-1]["seq"] if items else after_seq
        return {"items": items, "cursor": cursor, "latest_seq": latest, "has_more": cursor < latest}

    @app.post("/v1/accounts/{account_id}/events/ingest", tags=["events"])
    async def ingest(account_id: str, body: IngestEventIn, p: Principal = Depends(principal)):
        """Idempotent ingestion for future source systems. Duplicate event_id is ignored."""
        account_for(account_id, p)
        if len(dumps(body.payload)) > 8000:
            raise ApiError(413, "payload_too_large", "payloadが大きすぎます")
        parse(body.occurred_at)
        with tx(conn):
            before = conn.execute("SELECT 1 FROM events WHERE event_id=?", (body.event_id,)).fetchone()
            emit(conn, account_id, body.event_type, body.message, severity=body.severity, post_id=body.post_id,
                 payload=body.payload, event_id=body.event_id, occurred_at=body.occurred_at, source_system=body.source_system)
        return {"accepted": before is None, "duplicate": before is not None}

    # ---------------------------------------------------------- ideas
    @app.get("/v1/accounts/{account_id}/ideas", tags=["ideas"])
    async def list_ideas(account_id: str, status: str | None = None, theme: str | None = None, q: str | None = Query(None, max_length=100),
                   limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), p: Principal = Depends(principal)):
        account_for(account_id, p)
        return idea_bank.list_ideas(conn, account_id, status=status, theme=theme, q=q, limit=limit, offset=offset)

    @app.post("/v1/accounts/{account_id}/ideas", tags=["ideas"])
    async def create_idea(account_id: str, body: idea_bank.IdeaIn, p: Principal = Depends(principal)):
        account = account_for(account_id, p)
        s, _ = get_settings(conn, account_id)
        if body.theme not in s.content.themes:
            raise Conflict("テーマは設定済みのテーマから選んでください")
        return idea_bank.create(conn, account_id, body, actor=p.actor, is_test=is_test_scope(account))

    @app.get("/v1/accounts/{account_id}/ideas/{idea_id}", tags=["ideas"])
    async def idea_detail(account_id: str, idea_id: int, p: Principal = Depends(principal)):
        account_for(account_id, p)
        return idea_bank.detail(conn, account_id, idea_id)

    @app.put("/v1/accounts/{account_id}/ideas/{idea_id}", tags=["ideas"])
    async def update_idea(account_id: str, idea_id: int, body: IdeaPatchIn, p: Principal = Depends(principal)):
        account_for(account_id, p)
        s, _ = get_settings(conn, account_id)
        if body.theme not in s.content.themes:
            raise Conflict("テーマは設定済みのテーマから選んでください")
        data = idea_bank.IdeaIn.model_validate(body.model_dump(exclude={"expected_updated_at"}))
        return idea_bank.update(conn, account_id, idea_id, data, actor=p.actor, expected_updated_at=body.expected_updated_at)

    @app.post("/v1/accounts/{account_id}/ideas/{idea_id}/status", tags=["ideas"])
    async def idea_status(account_id: str, idea_id: int, body: IdeaStatusIn, p: Principal = Depends(principal)):
        account_for(account_id, p)
        return idea_bank.set_status(conn, account_id, idea_id, body.status, actor=p.actor)

    # ---------------------------------------------------------- policy / experiments
    @app.get("/v1/accounts/{account_id}/policy", tags=["improvement"])
    async def policy(account_id: str, p: Principal = Depends(principal)):
        account_for(account_id, p)
        versions = rows(conn.execute(
            "SELECT version, parent_version, source, reason, is_active, created_at, created_by, policy_json FROM policy_versions"
            " WHERE account_id=? ORDER BY version DESC LIMIT 50", (account_id,)).fetchall())
        for v in versions:
            v["policy"] = loads(v.pop("policy_json"))
        s, _ = get_settings(conn, account_id)
        return {"active": active_policy(conn, account_id), "versions": versions, "locked": s.locked,
                "improvement": s.improvement.model_dump()}

    @app.post("/v1/accounts/{account_id}/policy/rollback", tags=["improvement"])
    async def rollback(account_id: str, body: RollbackIn, p: Principal = Depends(principal)):
        account_for(account_id, p)
        return {"new_version": analyzer.manual_rollback(ctx, account_id, body.version, p.actor)}

    @app.get("/v1/accounts/{account_id}/experiments", tags=["improvement"])
    async def experiments(account_id: str, limit: int = Query(30, ge=1, le=100), p: Principal = Depends(principal)):
        account_for(account_id, p)
        items = rows(conn.execute("SELECT * FROM experiments WHERE account_id=? ORDER BY id DESC LIMIT ?",
                                  (account_id, limit)).fetchall())
        for e in items:
            e["result"] = loads(e.pop("result_json"), None)
        return {"items": items}

    @app.post("/v1/accounts/{account_id}/experiments/stop", tags=["improvement"])
    async def stop_experiment(account_id: str, p: Principal = Depends(principal)):
        account_for(account_id, p)
        return analyzer.stop_experiment(ctx, account_id, p.actor)

    # ---------------------------------------------------------- reports
    @app.get("/v1/accounts/{account_id}/reports", tags=["reports"])
    async def reports(account_id: str, kind: str | None = Query(None, pattern="^(daily|weekly)$"), p: Principal = Depends(principal)):
        account_for(account_id, p)
        return {"items": report_mod.list_reports(conn, account_id, kind)}

    @app.get("/v1/accounts/{account_id}/reports/{report_id}", tags=["reports"])
    async def report(account_id: str, report_id: int, p: Principal = Depends(principal)):
        account_for(account_id, p)
        return report_mod.get_report(conn, account_id, report_id)

    @app.post("/v1/accounts/{account_id}/reports/regenerate", tags=["reports"])
    async def regenerate(account_id: str, body: RegenerateIn, p: Principal = Depends(principal)):
        account_for(account_id, p)
        start = parse(body.period_start)
        existing = row(conn.execute("SELECT period_end FROM reports WHERE account_id=? AND kind=? AND period_start=? LIMIT 1",
                                    (account_id, body.kind, iso(start))).fetchone())
        end = parse(existing["period_end"]) if existing else (start + (timedelta(days=1) if body.kind == "daily" else timedelta(days=7)))
        key = f"report:{body.kind}:{account_id}:{iso(start)}:regen:{now_iso()}"
        jid, _ = jobs.enqueue(conn, account_id, f"{body.kind}_report", key, now(),
                              payload={"kind": body.kind, "period_start": iso(start), "period_end": iso(end),
                                       "regenerate": True, "actor": p.actor}, max_attempts=2)
        with tx(conn):
            audit(conn, account_id, p.actor, "report.regenerate_requested", f"job:{jid}", {"kind": body.kind})
        return {"job_id": jid, "status": "queued"}

    # ---------------------------------------------------------- settings / control
    @app.get("/v1/accounts/{account_id}/settings", tags=["settings"])
    async def settings(account_id: str, p: Principal = Depends(principal)):
        account_for(account_id, p)
        s, v = get_settings(conn, account_id)
        return {"settings": s.model_dump(), "version": v, "schema": AccountSettingsModel.model_json_schema()}

    @app.patch("/v1/accounts/{account_id}/settings", tags=["settings"])
    async def patch_settings(account_id: str, body: SettingsPatchIn, p: Principal = Depends(principal)):
        account_for(account_id, p)
        s, _ = get_settings(conn, account_id)
        merged = AccountSettingsModel.model_validate(_deep_merge(s.model_dump(), body.patch))
        v = update_settings(conn, account_id, merged, body.expected_version, p.actor)
        return {"version": v, "settings": merged.model_dump()}

    def _toggle(account_id: str, path: list[str], enabled: bool, actor: str, label: str) -> dict:
        s, v = get_settings(conn, account_id)
        patch: dict = {}
        cur = patch
        for k in path[:-1]:
            cur = cur.setdefault(k, {})
        cur[path[-1]] = enabled
        merged = AccountSettingsModel.model_validate(_deep_merge(s.model_dump(), patch))
        nv = update_settings(conn, account_id, merged, v, actor)
        with tx(conn):
            emit(conn, account_id, "control.toggled", f"{label}を{'ON' if enabled else 'OFF'}にしました",
                 severity="info", payload={"what": ".".join(path), "enabled": enabled})
        return {"enabled": enabled, "settings_version": nv}

    @app.post("/v1/accounts/{account_id}/control/autopilot", tags=["control"])
    async def autopilot(account_id: str, body: ToggleIn, p: Principal = Depends(principal)):
        account_for(account_id, p)
        return _toggle(account_id, ["autopilot_enabled"], body.enabled, p.actor, "自動運用")

    @app.post("/v1/accounts/{account_id}/control/improvement", tags=["control"])
    async def improvement(account_id: str, body: ToggleIn, p: Principal = Depends(principal)):
        account_for(account_id, p)
        return _toggle(account_id, ["improvement", "enabled"], body.enabled, p.actor, "自動改善")

    @app.post("/v1/accounts/{account_id}/control/stop", tags=["control"])
    async def stop(account_id: str, body: StopIn, p: Principal = Depends(principal)):
        """pause_schedule: 予約停止（新規の枠作成と公開を止める。公開済みには影響しない）
        cancel_queued: 予約停止＋待機中ジョブ・未公開の予定を取消。実行中ジョブには取消要求を出す。"""
        account_for(account_id, p)
        res: dict = {"mode": body.mode}
        res["autopilot"] = _toggle(account_id, ["autopilot_enabled"], False, p.actor, "自動運用")
        if body.mode == "cancel_queued":
            queued = rows(conn.execute("SELECT id FROM jobs WHERE account_id=? AND status='queued'", (account_id,)).fetchall())
            running = rows(conn.execute("SELECT id, kind FROM jobs WHERE account_id=? AND status='running'", (account_id,)).fetchall())
            cancelled, requested, refused = 0, 0, []
            for j in queued:
                jobs.request_cancel(conn, account_id, j["id"], p.actor)
                cancelled += 1
            for j in running:
                try:
                    jobs.request_cancel(conn, account_id, j["id"], p.actor)
                    requested += 1
                except Conflict as e:
                    refused.append({"job_id": j["id"], "kind": j["kind"], "reason": str(e)})
            with tx(conn):
                n = conn.execute("UPDATE posts SET status='cancelled', last_error='一括停止で取消', updated_at=? WHERE account_id=?"
                                 " AND status IN ('planned','awaiting_approval','scheduled')", (now_iso(), account_id)).rowcount
            for r_ in rows(conn.execute("SELECT id FROM posts WHERE account_id=? AND status='cancelled'", (account_id,)).fetchall()):
                idea_bank.release(conn, r_["id"])
            res.update({"jobs_cancelled": cancelled, "cancel_requested": requested, "not_cancellable": refused,
                        "posts_cancelled": n})
        with tx(conn):
            audit(conn, account_id, p.actor, f"control.stop.{body.mode}", account_id, res)
        return res

    @app.post("/v1/accounts/{account_id}/connection/check", tags=["control"])
    async def connection_check(account_id: str, p: Principal = Depends(principal)):
        account = account_for(account_id, p)
        if account["data_scope"] != "live":
            raise Conflict("デモ/テストアカウントはThreadsに接続しません")
        return publishing.check_connection(ctx, account_id)

    # ---------------------------------------------------------- usage / audit
    @app.get("/v1/accounts/{account_id}/usage", tags=["status"])
    async def usage(account_id: str, p: Principal = Depends(principal)):
        account_for(account_id, p)
        from .llm import usage_summary
        s, _ = get_settings(conn, account_id)
        return usage_summary(conn, account_id, s)

    @app.get("/v1/accounts/{account_id}/audit", tags=["status"])
    async def audit_log(account_id: str, limit: int = Query(50, ge=1, le=200), p: Principal = Depends(principal)):
        account_for(account_id, p)
        items = rows(conn.execute("SELECT * FROM audit_log WHERE account_id=? ORDER BY id DESC LIMIT ?",
                                  (account_id, limit)).fetchall())
        for a in items:
            a["detail"] = loads(a.pop("detail_json"), {})
        return {"items": items}

    # ---------------------------------------------------------- assistant
    @app.post("/v1/accounts/{account_id}/assistant/runs", tags=["assistant"])
    async def assistant_create(account_id: str, body: assistant.AssistantIn, p: Principal = Depends(principal)):
        account_for(account_id, p)
        return assistant.create_run(ctx, account_id, body, p.actor)

    @app.get("/v1/accounts/{account_id}/assistant/runs", tags=["assistant"])
    async def assistant_list(account_id: str, p: Principal = Depends(principal)):
        account_for(account_id, p)
        return {"items": assistant.list_runs(conn, account_id)}

    # ---------------------------------------------------------- demo
    @app.post("/v1/demo/scenario", tags=["demo"])
    async def scenario(body: ScenarioIn, p: Principal = Depends(principal)):
        if not cfg.is_demo:
            raise ApiError(404, "not_found", "デモ環境のみ")
        from .demo import run_scenario
        accts = list_accounts(conn, p.scope)
        if not accts:
            raise NotFound("demo account")
        return run_scenario(ctx, accts[0]["id"], body.name)

    return app

