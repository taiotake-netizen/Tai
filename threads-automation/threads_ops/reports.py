"""Daily / weekly reports. Numbers are computed here; AI only summarizes the computed numbers.

Definitions (also shown in the report):
- 投稿数: posts with status=published whose published_at is in the period
- 公開試行数: publish attempts (post_attempts kind=publish, outcome != started) in the period
- 成功率: 成功 / (成功 + 失敗). 結果不明は分母に含めず別掲。対象0件なら null（画面では「—」）
- 反応率: (likes+replies+reposts+quotes) / views、主観測時点の取得済みデータのみ
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime

from .context import Ctx
from .db import dumps, loads, row, rows, tx
from .llm import AIUnavailable, parse_json
from .store import Conflict, NotFound, audit, emit, get_account, get_settings, is_test_scope
from .timeutil import JST, daily_period, iso, now, now_iso, parse, weekly_period


def period_for(kind: str, ref: datetime, zone=JST) -> tuple[datetime, datetime]:
    return daily_period(ref, zone) if kind == "daily" else weekly_period(ref, zone)


def compute(ctx: Ctx, account_id: str, start: str, end: str) -> dict:
    conn = ctx.conn
    account = get_account(conn, account_id)
    s, _ = get_settings(conn, account_id)
    test = int(is_test_scope(account))
    bucket = s.improvement.primary_bucket_hours
    planned = conn.execute("SELECT COUNT(*) c FROM posts WHERE account_id=? AND is_test=? AND slot_at>=? AND slot_at<?",
                           (account_id, test, start, end)).fetchone()["c"]
    status_counts = {r["status"]: r["c"] for r in conn.execute(
        "SELECT status, COUNT(*) c FROM posts WHERE account_id=? AND is_test=? AND slot_at>=? AND slot_at<? GROUP BY status",
        (account_id, test, start, end))}
    attempts = {r["outcome"]: r["c"] for r in conn.execute(
        "SELECT a.outcome, COUNT(*) c FROM post_attempts a JOIN posts p ON p.id=a.post_id WHERE p.account_id=? AND p.is_test=?"
        " AND a.kind='publish' AND a.outcome<>'started' AND a.created_at>=? AND a.created_at<? GROUP BY a.outcome",
        (account_id, test, start, end))}
    published = rows(conn.execute(
        "SELECT p.id, p.theme, p.hook_style, p.cta_key, p.text, p.published_at, p.permalink, p.experiment_arm,"
        " m.status mstatus, m.views, m.likes, m.replies, m.reposts, m.quotes, m.observed_at FROM posts p"
        " LEFT JOIN metrics m ON m.post_id=p.id AND m.bucket_hours=?"
        " WHERE p.account_id=? AND p.is_test=? AND p.status='published' AND p.published_at>=? AND p.published_at<?"
        " ORDER BY p.published_at", (bucket, account_id, test, start, end)).fetchall())
    ok = [p for p in published if p["mstatus"] == "ok"]
    totals = {k: (sum(p[k] for p in ok if p[k] is not None) if any(p[k] is not None for p in ok) else None)
              for k in ("views", "likes", "replies", "reposts", "quotes")}
    rated = [p for p in ok if p["views"]]
    for p in rated:
        p["er"] = sum((p[k] or 0) for k in ("likes", "replies", "reposts", "quotes")) / p["views"]

    def group(col: str) -> list[dict]:
        g: dict[str, list[float]] = {}
        for p in rated:
            g.setdefault(p[col] or "（なし）", []).append(p["er"])
        return sorted([{"value": k, "n": len(v), "mean_er": statistics.mean(v)} for k, v in g.items()],
                      key=lambda x: -x["mean_er"])

    succ, fail, unk = attempts.get("ok", 0), attempts.get("error", 0), attempts.get("unknown", 0)
    experiments = rows(conn.execute(
        "SELECT id, variable, hypothesis, control_value, treatment_value, status, result_json, started_at, ended_at"
        " FROM experiments WHERE account_id=? AND started_at<? AND (ended_at IS NULL OR ended_at>=?)",
        (account_id, end, start)).fetchall())
    for e in experiments:
        e["result"] = loads(e.pop("result_json"), None)
    policy_changes = rows(conn.execute(
        "SELECT version, parent_version, source, reason, created_at FROM policy_versions WHERE account_id=?"
        " AND created_at>=? AND created_at<? AND source<>'initial' ORDER BY version", (account_id, start, end)).fetchall())
    errors = rows(conn.execute(
        "SELECT event_type, message, occurred_at, post_id FROM events WHERE account_id=? AND severity='error'"
        " AND occurred_at>=? AND occurred_at<? ORDER BY seq DESC LIMIT 30", (account_id, start, end)).fetchall())
    metric_failures = conn.execute(
        "SELECT COUNT(*) c FROM metrics WHERE account_id=? AND is_test=? AND status<>'ok' AND observed_at>=? AND observed_at<?",
        (account_id, test, start, end)).fetchone()["c"]
    last_obs = conn.execute("SELECT MAX(observed_at) t FROM metrics WHERE account_id=? AND is_test=? AND status='ok'",
                            (account_id, test)).fetchone()["t"]
    running = row(conn.execute("SELECT variable, control_value, treatment_value, hypothesis FROM experiments"
                               " WHERE account_id=? AND status='running'", (account_id,)).fetchone())
    notes = []
    if len(published) and len(ok) < len(published):
        notes.append(f"公開{len(published)}件のうち{len(published) - len(ok)}件は{bucket}時間後の実績が未取得または取得失敗です（0扱いしていません）")
    if not published:
        notes.append("期間内に公開された投稿はありません")
    if len(rated) < 5:
        notes.append("反応率の比較は5件未満のため参考値です")
    return {
        "definitions": {"success_rate": "成功/(成功+失敗)。結果不明は別掲", "er": "(いいね+返信+再投稿+引用)/閲覧",
                        "primary_bucket_hours": bucket},
        "data_scope": account["data_scope"],
        "planned_slots": planned,
        "post_status_counts": status_counts,
        "published_count": len(published),
        "publish_attempts": {"success": succ, "failed": fail, "unknown": unk, "total": succ + fail + unk},
        "success_rate": (succ / (succ + fail)) if (succ + fail) else None,
        "metrics": {"posts_with_metrics": len(ok), "posts_without_metrics": len(published) - len(ok),
                    "totals": totals, "mean_er": statistics.mean([p["er"] for p in rated]) if rated else None,
                    "metric_failures": metric_failures},
        "by_theme": group("theme"),
        "by_hook": group("hook_style"),
        "top_posts": [{"id": p["id"], "text": (p["text"] or "")[:80], "er": p["er"], "views": p["views"],
                       "permalink": p["permalink"]} for p in sorted(rated, key=lambda p: -p["er"])[:3]],
        "experiments": experiments,
        "policy_changes": policy_changes,
        "next": {"running_experiment": running},
        "errors": errors,
        "notes": notes,
        "last_metrics_observed_at": last_obs,
    }


SUMMARY_PROMPT = """あなたはSNS運用のレポート担当です。context.data は集計済みの数値です。
数値を変えたり推測で補ったりせず、日本語で5行以内に要約し、次に試すことを1〜2点挙げてください。
効果が確定していないものは「傾向」「暫定」と書くこと。サロンへの流入や入会には触れないこと。
JSON {"summary": "..."} だけを返すこと。"""


def generate(ctx: Ctx, account_id: str, kind: str, start: datetime, end: datetime, *, actor: str,
             regenerate: bool = False, job_id: int | None = None) -> dict:
    conn = ctx.conn
    s_iso, e_iso = iso(start), iso(end)
    cur = row(conn.execute("SELECT * FROM reports WHERE account_id=? AND kind=? AND period_start=? AND is_current=1",
                           (account_id, kind, s_iso)).fetchone())
    if cur and not regenerate:
        return {"report_id": cur["id"], "version": cur["version"], "created": False}
    if end > now():
        raise Conflict("期間が終了していないためレポートを作成できません")
    data = compute(ctx, account_id, s_iso, e_iso)
    s, _ = get_settings(conn, account_id)
    summary, sstatus = None, "skipped_no_ai"
    if s.reports.ai_summary:
        try:
            res = ctx.llm.complete(account_id, s, "summarize_report", SUMMARY_PROMPT,
                                   "<context>" + json.dumps({"kind": kind, "data": data}, ensure_ascii=False, default=str)
                                   + "</context>", job_id=job_id)
            summary, sstatus = str(parse_json(res.text).get("summary", ""))[:2000] or None, "ok"
        except AIUnavailable as e:
            sstatus = "skipped_budget" if e.code.startswith("budget") or e.code == "price_not_set" else (
                "skipped_no_ai" if e.code == "not_configured" else "failed")
            summary = None
        except (ValueError, json.JSONDecodeError):
            sstatus = "failed"
    with tx(conn):
        latest = row(conn.execute("SELECT * FROM reports WHERE account_id=? AND kind=? AND period_start=? AND is_current=1",
                                  (account_id, kind, s_iso)).fetchone())
        if latest and not regenerate:
            return {"report_id": latest["id"], "version": latest["version"], "created": False}
        ver = conn.execute("SELECT COALESCE(MAX(version),0)+1 v FROM reports WHERE account_id=? AND kind=? AND period_start=?",
                           (account_id, kind, s_iso)).fetchone()["v"]
        conn.execute("UPDATE reports SET is_current=0 WHERE account_id=? AND kind=? AND period_start=?",
                     (account_id, kind, s_iso))
        c = conn.execute(
            "INSERT INTO reports(account_id, kind, period_start, period_end, version, is_current, data_json, summary_text,"
            " summary_status, data_as_of, generated_at, generated_by) VALUES (?,?,?,?,?,1,?,?,?,?,?,?)",
            (account_id, kind, s_iso, e_iso, ver, dumps(data), summary, sstatus,
             data["last_metrics_observed_at"] or now_iso(), now_iso(), actor))
        rid = int(c.lastrowid)
        audit(conn, account_id, actor, f"report.{'regenerate' if regenerate else 'generate'}", f"report:{rid}",
              {"kind": kind, "period_start": s_iso, "version": ver})
        label = "日次" if kind == "daily" else "週次"
        emit(conn, account_id, "report.generated", f"{label}レポートを作成（v{ver}）", severity="success",
             payload={"report_id": rid, "kind": kind, "period_start": s_iso, "version": ver})
    return {"report_id": rid, "version": ver, "created": True}


def get_report(conn, account_id: str, report_id: int) -> dict:
    r = row(conn.execute("SELECT * FROM reports WHERE id=? AND account_id=?", (report_id, account_id)).fetchone())
    if r is None:
        raise NotFound(f"report {report_id}")
    r["data"] = loads(r.pop("data_json"))
    r["versions"] = rows(conn.execute(
        "SELECT id, version, is_current, generated_at, generated_by, summary_status FROM reports WHERE account_id=? AND kind=?"
        " AND period_start=? ORDER BY version DESC", (account_id, r["kind"], r["period_start"])).fetchall())
    return r


def list_reports(conn, account_id: str, kind: str | None, limit: int = 30) -> list[dict]:
    q = ("SELECT id, kind, period_start, period_end, version, summary_status, generated_at, data_as_of FROM reports"
         " WHERE account_id=? AND is_current=1")
    params: list = [account_id]
    if kind:
        q += " AND kind=?"
        params.append(kind)
    q += " ORDER BY period_start DESC, kind LIMIT ?"
    params.append(limit)
    return rows(conn.execute(q, params).fetchall())


def run_report_job(ctx: Ctx, job: dict) -> dict:
    p = job["payload"]
    return generate(ctx, job["account_id"], p["kind"], parse(p["period_start"]), parse(p["period_end"]),
                    actor=p.get("actor", "system:scheduler"), regenerate=bool(p.get("regenerate")), job_id=job["id"])
