"""Post generation: choose features from policy/experiment, reserve an idea, generate, check, retry (bounded)."""

from __future__ import annotations

import hashlib
import json
import random
from datetime import timedelta

from . import ideas as idea_bank
from . import jobs
from .context import Ctx
from .db import dumps, row, rows, tx
from .llm import AIUnavailable, parse_json
from .quality import rule_check
from .settings import LENGTHS, AccountSettingsModel, Policy, allowed_values, reconcile_policy
from .store import active_policy, emit, get_account, get_settings, is_test_scope
from .timeutil import JST, iso, now, now_iso, parse


class Cancelled(Exception):
    pass


def _rng(post_id: int, salt: str = "") -> random.Random:
    return random.Random(int(hashlib.sha256(f"{post_id}:{salt}".encode()).hexdigest()[:12], 16))


def _weighted(rng: random.Random, weights: dict[str, float]) -> str:
    keys = list(weights)
    return rng.choices(keys, weights=[max(weights[k], 1e-6) for k in keys], k=1)[0]


def assign_arm(post_id: int, share: float) -> str:
    h = int(hashlib.sha256(f"arm:{post_id}".encode()).hexdigest()[:8], 16) % 1000
    return "treatment" if h < share * 1000 else "control"


def choose_features(post: dict, s: AccountSettingsModel, policy: Policy, experiment: dict | None) -> dict:
    rng = _rng(post["id"], "features")
    f = {
        "theme": _weighted(rng, policy.theme_weights),
        "hook": _weighted(rng, policy.hook_weights),
        "cta": _weighted(rng, policy.cta_weights),
        "appeal": _weighted(rng, policy.appeal_weights),
        "length": _weighted(rng, policy.length_weights),
        "structure": _weighted(rng, policy.structure_weights),
        "experiment_id": None,
        "arm": None,
    }
    if experiment and experiment["variable"] != "post_time":
        var = experiment["variable"]
        arm = assign_arm(post["id"], s.improvement.treatment_share)
        f[var] = experiment["treatment_value"] if arm == "treatment" else experiment["control_value"]
        f["experiment_id"], f["arm"] = experiment["id"], arm
    elif experiment and post.get("experiment_id") == experiment["id"]:
        f["experiment_id"], f["arm"] = experiment["id"], post.get("experiment_arm")
    return f


def recent_context(ctx: Ctx, account_id: str, s: AccountSettingsModel, exclude_post_id: int, include_test: bool) -> dict:
    since = iso(now() - timedelta(days=s.checks.similarity_window_days))
    rs = rows(ctx.conn.execute(
        "SELECT id, text, theme, cta_key FROM posts WHERE account_id=? AND id<>? AND is_test=? AND text IS NOT NULL"
        " AND status IN ('awaiting_approval','scheduled','publishing','published','unknown') AND slot_at>=?"
        " ORDER BY slot_at DESC", (account_id, exclude_post_id, int(include_test), since)).fetchall())
    return {"texts": [r["text"] for r in rs], "themes": [r["theme"] for r in rs if r["theme"]],
            "ctas": [r["cta_key"] for r in rs if r["cta_key"]]}


SYSTEM_PROMPT = """あなたは副業サロンのThreads運用担当のコピーライターです。
必ず次のルールを守り、JSONオブジェクト {"text": "投稿本文"} だけを返してください。
- 日本語。指定された口調・構成・書き出し・訴求・文字数の範囲を守る
- 収入・成果・体験談・実績・数値は、context.approved_facts に書かれた内容だけを使う。無ければ数値を書かない
- 架空の人物・受講生・体験談・実績を作らない。サービス内容は context.business に書かれた範囲だけ
- 「必ず稼げる」「誰でも簡単」など収益を保証・誇張する表現は禁止。context.banned_phrases も使わない
- URLは context.cta.url があればそれだけを使う。それ以外のURLやドメインは書かない
- ハッシュタグ・絵文字の多用はしない。Markdown記法（**, #, ```）は使わない
- 過去の投稿（context.avoid_similar_to）と似た文章にしない"""


def build_prompt(s: AccountSettingsModel, f: dict, idea: dict | None, recent: dict, issues: list[dict]) -> str:
    lo, hi = LENGTHS[f["length"]]
    span = s.content.max_chars - s.content.min_chars
    min_c, max_c = int(s.content.min_chars + span * lo), int(s.content.min_chars + span * hi)
    cta = next((c for c in s.business.cta_options if c.key == f["cta"]), None)
    ctxd = {
        "theme": f["theme"], "hook": f["hook"], "appeal": f["appeal"], "structure": f["structure"],
        "length_chars": [min_c, max_c],
        "cta_key": f["cta"], "cta_text": cta.text if cta else "", "cta": {"text": cta.text if cta else "",
                                                                         "url": cta.url if cta else None},
        "tone": s.business.tone,
        "business": {"service_name": s.business.service_name or None, "target": s.business.target or None,
                     "offer_summary": s.business.offer_summary or None},
        "approved_facts": [fa.statement for fa in s.business.approved_facts],
        "banned_phrases": s.content.banned_phrases,
        "idea": {k: idea[k] for k in ("theme", "pain", "appeal", "angle", "notes")} if idea else None,
        "avoid_similar_to": [t[:120] for t in recent["texts"][:8]],
    }
    msg = ("<context>" + json.dumps(ctxd, ensure_ascii=False) + "</context>\n"
           f"上の条件でThreads投稿を1本作成してください。本文は{min_c}〜{max_c}文字。")
    if f["cta"] == "none" or not cta:
        msg += " CTAは入れないでください。"
    else:
        msg += f" 最後にCTA「{cta.text}」の趣旨を自然に入れてください。"
    if issues:
        msg += "\n前回の案は次の理由で不合格でした。必ず修正してください: " + "; ".join(i["message"] for i in issues)
    return msg


REVIEW_PROMPT = """あなたは投稿の審査担当です。投稿本文が次に該当するか判定し、JSON {"ok": bool, "issues": [文字列]} だけを返してください。
- 架空の体験談・人物・実績の可能性がある
- 承認済み事実（approved_facts）にない具体的な成果・数値を断定している
- 収益の保証や誇大な表現
- 未確認の商品・サービス内容を断定している
問題がなければ ok=true, issues=[]。"""


def _record_attempt(ctx: Ctx, post_id: int, kind: str, outcome: str, detail: dict | str) -> None:
    with tx(ctx.conn):
        ctx.conn.execute("INSERT INTO post_attempts(post_id, kind, outcome, detail, created_at) VALUES (?,?,?,?,?)",
                         (post_id, kind, outcome, detail if isinstance(detail, str) else dumps(detail), now_iso()))


def generate_post(ctx: Ctx, job: dict) -> dict:
    conn = ctx.conn
    post = row(conn.execute("SELECT * FROM posts WHERE id=?", (job["post_id"],)).fetchone())
    if post is None:
        return {"skipped": "post not found"}
    if post["status"] not in ("planned", "generating"):
        return {"skipped": f"post status {post['status']}"}
    account = get_account(conn, post["account_id"])
    s, _ = get_settings(conn, account["id"])
    test_scope = bool(post["is_test"])
    slot = parse(post["slot_at"])
    if post["origin"] == "schedule" and slot + timedelta(minutes=s.schedule.missed_grace_minutes) < now():
        _skip(ctx, post, "投稿予定時刻を過ぎたため生成をスキップ")
        return {"skipped": "missed slot"}
    with tx(conn):
        conn.execute("UPDATE posts SET status='generating', updated_at=? WHERE id=?", (now_iso(), post["id"]))
    pol = active_policy(conn, account["id"])
    policy = reconcile_policy(Policy.model_validate(pol["policy"]), s)
    exp = row(conn.execute("SELECT * FROM experiments WHERE account_id=? AND status='running'",
                           (account["id"],)).fetchone())
    f = choose_features(post, s, policy, exp)
    if job["payload"].get("overrides"):
        for k, v in job["payload"]["overrides"].items():
            if k in ("theme", "hook", "cta", "appeal", "length", "structure") and v in allowed_values(s, k):
                f[k] = v
    recent = recent_context(ctx, account["id"], s, post["id"], test_scope)
    forced_theme = bool(exp and exp["variable"] == "theme" and f["arm"]) or bool(job["payload"].get("overrides", {}).get("theme"))
    idea = None
    if job["payload"].get("idea_id"):
        idea = idea_bank.get(conn, account["id"], int(job["payload"]["idea_id"]))
    else:
        idea = idea_bank.reserve(conn, account["id"], post["id"], s, preferred_theme=f["theme"],
                                 forced_theme=forced_theme, avoid_themes=recent["themes"], include_test=test_scope,
                                 rng=_rng(post["id"], "idea"))
    if idea and not forced_theme:
        f["theme"] = idea["theme"]
    with tx(conn):
        conn.execute(
            "UPDATE posts SET idea_id=?, policy_version=?, experiment_id=?, experiment_arm=?, theme=?, hook_style=?,"
            " cta_key=?, appeal=?, length_target=?, structure=?, updated_at=? WHERE id=?",
            (idea["id"] if idea else None, pol["version"], f["experiment_id"], f["arm"], f["theme"], f["hook"],
             f["cta"], f["appeal"], f["length"], f["structure"], now_iso(), post["id"]))
    issues: list[dict] = []
    attempts = 1 + s.checks.max_regenerations
    for n in range(attempts):
        if jobs.cancel_requested(conn, job["id"]):
            idea_bank.release(conn, post["id"])
            with tx(conn):
                conn.execute("UPDATE posts SET status='cancelled', updated_at=? WHERE id=?", (now_iso(), post["id"]))
            raise Cancelled()
        try:
            res = ctx.llm.complete(account["id"], s, "generate_post", SYSTEM_PROMPT,
                                   build_prompt(s, f, idea, recent, issues), job_id=job["id"])
        except AIUnavailable as e:
            idea_bank.release(conn, post["id"])
            with tx(conn):
                conn.execute("UPDATE posts SET status='planned', generation_attempts=generation_attempts+1,"
                             " last_error=?, updated_at=? WHERE id=?", (str(e), now_iso(), post["id"]))
            _record_attempt(ctx, post["id"], "generate", "error", {"code": e.code, "message": str(e)})
            raise
        try:
            text = str(parse_json(res.text).get("text", "")).strip()
        except (ValueError, json.JSONDecodeError):
            text = ""
        check = rule_check(text, s, recent_texts=recent["texts"], recent_themes=recent["themes"],
                           recent_ctas=recent["ctas"], theme=f["theme"], cta_key=f["cta"])
        if check.passed and s.checks.ai_review_enabled:
            try:
                rv = parse_json(ctx.llm.complete(
                    account["id"], s, "review_post", REVIEW_PROMPT,
                    "<context>" + json.dumps({"text": text, "approved_facts": [fa.statement for fa in s.business.approved_facts],
                                              "business": s.business.model_dump(include={"service_name", "offer_summary"})},
                                             ensure_ascii=False) + "</context>", job_id=job["id"]).text)
                if rv.get("ok") is False:
                    for msg in (rv.get("issues") or ["AI審査で不合格"])[:5]:
                        check.add("ai_review", f"AI審査: {str(msg)[:200]}")
            except AIUnavailable as e:
                check.add("ai_review_unavailable", f"AI審査を実行できませんでした（{e}）", severity="warning")
            except (ValueError, json.JSONDecodeError):
                check.add("ai_review_unavailable", "AI審査の応答を解釈できませんでした", severity="warning")
        _record_attempt(ctx, post["id"], "generate", "ok" if check.passed else "rejected",
                        {"attempt": n + 1, "check": check.as_dict(), "chars": len(text)})
        with tx(conn):
            conn.execute("UPDATE posts SET text=?, check_json=?, generation_attempts=generation_attempts+1, updated_at=?"
                         " WHERE id=?", (text or None, dumps(check.as_dict()), now_iso(), post["id"]))
        if check.passed:
            return _accept(ctx, post, s)
        issues = [i for i in check.issues if i["severity"] == "error"]
    _skip(ctx, post, "品質チェックに合格しなかったため投稿をスキップ（要確認）",
          detail={"issues": issues})
    return {"skipped": "quality", "issues": issues}


def _accept(ctx: Ctx, post: dict, s: AccountSettingsModel) -> dict:
    conn = ctx.conn
    approval = s.require_approval and post["origin"] == "schedule"
    if post["origin"] == "assistant":
        approval = True   # assistant drafts are always saved as drafts for human approval
    status = "awaiting_approval" if approval else "scheduled"
    with tx(conn):
        conn.execute("UPDATE posts SET status=?, last_error=NULL, updated_at=? WHERE id=?", (status, now_iso(), post["id"]))
        emit(conn, post["account_id"], "post.ready",
             "投稿案が承認待ちです" if approval else "投稿を予約しました", severity="success" if not approval else "info",
             post_id=post["id"], payload={"status": status, "slot_at": post["slot_at"]})
    if status == "scheduled":
        jobs.enqueue(conn, post["account_id"], "publish_post", f"publish:{post['id']}:{post['slot_at']}", parse(post["slot_at"]),
                     post_id=post["id"], max_attempts=1)
    return {"status": status}


def _skip(ctx: Ctx, post: dict, reason: str, detail: dict | None = None) -> None:
    idea_bank.release(ctx.conn, post["id"])
    with tx(ctx.conn):
        ctx.conn.execute("UPDATE posts SET status='skipped', last_error=?, updated_at=? WHERE id=?",
                         (reason, now_iso(), post["id"]))
        emit(ctx.conn, post["account_id"], "post.skipped", reason, severity="warning", post_id=post["id"],
             payload=detail or {})


# ------------------------------------------------------------------ idea refill / derive

REFILL_PROMPT = """あなたは副業サロンのSNS企画担当です。与えられたテーマ・ターゲット・承認済み情報の範囲だけで投稿ネタを考え、
JSON {"ideas": [{"theme": テーマ, "pain": 読者の悩み, "appeal": 訴求, "angle": 切り口}]} だけを返してください。
theme は context.themes のいずれか、appeal は context.appeals のいずれか。架空の実績・数値・体験談は書かないこと。"""


def refill_ideas(ctx: Ctx, job: dict) -> dict:
    conn = ctx.conn
    account = get_account(conn, job["account_id"])
    s, _ = get_settings(conn, account["id"])
    test = is_test_scope(account)
    remaining = s.ideas.refill_max_per_day - idea_bank.created_today(conn, account["id"], ("ai_refill", "derived"))
    count = min(s.ideas.refill_batch, remaining)
    if count <= 0:
        return {"created": 0, "reason": "本日の補充上限に到達"}
    existing = [r["angle"] for r in conn.execute(
        "SELECT angle FROM ideas WHERE account_id=? ORDER BY id DESC LIMIT 30", (account["id"],))]
    ctxd = {"themes": s.content.themes, "appeals": s.content.appeals, "count": count,
            "target": s.business.target or None, "offer_summary": s.business.offer_summary or None,
            "approved_facts": [f.statement for f in s.business.approved_facts], "existing_angles": existing}
    res = ctx.llm.complete(account["id"], s, "refill_ideas", REFILL_PROMPT,
                           "<context>" + json.dumps(ctxd, ensure_ascii=False) + "</context>", job_id=job["id"])
    created = _store_ideas(ctx, account["id"], s, parse_json(res.text).get("ideas", []), count, origin="ai_refill",
                           is_test=test)
    return {"created": created}


def _store_ideas(ctx: Ctx, account_id: str, s: AccountSettingsModel, raw: list, limit: int, *, origin: str,
                 is_test: bool, parent_idea_id: int | None = None, source_post_id: int | None = None) -> int:
    n = 0
    for it in raw[:limit]:
        if not isinstance(it, dict):
            continue
        theme = str(it.get("theme", ""))
        if theme not in s.content.themes:
            continue
        appeal = str(it.get("appeal", ""))
        data = idea_bank.IdeaIn(theme=theme, pain=str(it.get("pain", ""))[:200],
                                appeal=appeal if appeal in s.content.appeals else "",
                                angle=str(it.get("angle", ""))[:200], status="ready")
        idea_bank.create(ctx.conn, account_id, data, actor="system:ai", origin=origin, parent_idea_id=parent_idea_id,
                         source_post_id=source_post_id, is_test=is_test)
        n += 1
    return n


DERIVE_PROMPT = """反応が良かった投稿のネタを、別の切り口に展開してください。テーマは context.themes のいずれか。
JSON {"ideas": [{"theme","pain","appeal","angle"}]} だけを返すこと。架空の実績・数値・体験談は書かないこと。"""


def derive_ideas(ctx: Ctx, account_id: str, s: AccountSettingsModel, post: dict, is_test: bool, job_id: int) -> int:
    if not post.get("idea_id"):
        return 0
    base = idea_bank.get(ctx.conn, account_id, post["idea_id"])
    remaining = s.ideas.refill_max_per_day - idea_bank.created_today(ctx.conn, account_id, ("ai_refill", "derived"))
    if remaining <= 0:
        return 0
    ctxd = {"themes": s.content.themes, "appeals": s.content.appeals,
            "base": {k: base[k] for k in ("theme", "pain", "appeal", "angle")}, "post_text": (post.get("text") or "")[:300]}
    res = ctx.llm.complete(account_id, s, "derive_ideas", DERIVE_PROMPT,
                           "<context>" + json.dumps(ctxd, ensure_ascii=False) + "</context>", job_id=job_id)
    return _store_ideas(ctx, account_id, s, parse_json(res.text).get("ideas", []), min(2, remaining),
                        origin="derived", is_test=is_test, parent_idea_id=base["id"], source_post_id=post["id"])


def local_slot(post: dict, zone=JST) -> str:
    return parse(post["slot_at"]).astimezone(zone).strftime("%H:%M")
