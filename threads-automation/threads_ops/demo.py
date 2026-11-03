"""Demo data and scenarios. Only ever runs against a demo-scope account in the demo database
(APP_ENV=demo forces PUBLISH_MODE=dry_run and the mock LLM). Nothing here touches external services."""

from __future__ import annotations

import random
from datetime import timedelta

from . import ideas as idea_bank
from . import jobs
from .analyzer import analyze
from .context import Ctx
from .db import row, tx
from .reports import generate, period_for
from .settings import AccountSettingsModel, Policy, initial_policy
from .store import Conflict, create_account, emit, list_accounts, set_state
from .threads_api import synthetic_metrics
from .timeutil import JST, iso, now, now_iso

DEMO_ACCOUNT = "demo"

SEED_IDEAS = [
    ("副業の始め方", "何から始めればいいか分からない", "小さな一歩", "最初の1週間でやること"),
    ("副業の始め方", "会社にバレないか不安", "不安の解消", "始める前に確認したいこと"),
    ("時間の使い方", "平日に時間が取れない", "時間効率", "朝15分の使い方"),
    ("時間の使い方", "休日にだらだらしてしまう", "時間効率", "予定を先に決める"),
    ("スキルの選び方", "どのスキルを学べばいいか迷う", "学びの楽しさ", "選ぶ基準を3つに絞る"),
    ("スキルの選び方", "向いていないかもと思う", "不安の解消", "合う・合わないの見極め方"),
    ("続けるコツ", "三日坊主になる", "小さな一歩", "記録を残すだけの習慣"),
    ("続けるコツ", "成果が見えずにやめたくなる", "不安の解消", "途中経過を言葉にする"),
    ("失敗から学ぶこと", "失敗が怖くて動けない", "不安の解消", "小さく試して直す"),
    ("失敗から学ぶこと", "同じミスを繰り返す", "学びの楽しさ", "振り返りの型"),
    ("副業の始め方", "準備ばかりで行動できない", "小さな一歩", "準備を終わらせる期限"),
    ("時間の使い方", "スマホ時間が長い", "時間効率", "通知を減らす工夫"),
]


def demo_settings() -> AccountSettingsModel:
    s = AccountSettingsModel()
    s.autopilot_enabled = True
    s.require_approval = False
    s.business.service_name = "（デモ）副業サロン"
    s.business.target = "（デモ）会社員で副業を始めたい人"
    s.business.offer_summary = "（デモ用の仮説明。実在の商品情報ではありません）"
    s.ideas.refill_when_ready_below = 3
    return s


def seed(ctx: Ctx, *, days: int = 14) -> dict:
    if not ctx.cfg.is_demo and ctx.cfg.app_env != "test":
        raise RuntimeError("seed-demo is only allowed with APP_ENV=demo or test")
    conn = ctx.conn
    if any(a["id"] == DEMO_ACCOUNT for a in list_accounts(conn, None)):
        return {"seeded": False, "reason": "already seeded"}
    s = demo_settings()
    create_account(conn, DEMO_ACCOUNT, "デモアカウント", data_scope="demo", settings=s, actor="system:demo")
    for theme, pain, appeal, angle in SEED_IDEAS:
        idea_bank.create(conn, DEMO_ACCOUNT, idea_bank.IdeaIn(theme=theme, pain=pain, appeal=appeal, angle=angle),
                         actor="system:demo", origin="seed", is_test=True)
    rng = random.Random(7)
    policy: Policy = initial_policy(s)
    idea_ids = [r["id"] for r in conn.execute("SELECT id FROM ideas WHERE account_id=?", (DEMO_ACCOUNT,))]
    t0 = now()
    for d in range(days, 0, -1):
        day = (t0 - timedelta(days=d)).astimezone(JST).date()
        for hhmm in policy.post_times:
            h, m = map(int, hhmm.split(":"))
            from datetime import datetime
            slot = datetime(day.year, day.month, day.day, h, m, tzinfo=JST)
            f = {"theme": rng.choice(s.content.themes), "hook": rng.choice(s.content.hook_styles),
                 "cta": rng.choice([c.key for c in s.business.cta_options]), "appeal": rng.choice(s.content.appeals),
                 "length": rng.choice(["short", "medium", "long"]), "structure": rng.choice(s.content.structures)}
            iid = rng.choice(idea_ids)
            text = f"（デモ投稿）{f['theme']}について、{f['hook']}の書き出しで書いた投稿です。#{d}-{hhmm}"
            with tx(conn):
                cur = conn.execute(
                    "INSERT INTO posts(account_id, slot_at, status, idea_id, policy_version, theme, hook_style, cta_key, appeal,"
                    " length_target, structure, text, check_json, generation_attempts, external_post_id, published_at, origin,"
                    " is_test, created_at, updated_at) VALUES (?,?, 'published', ?, 1, ?,?,?,?,?,?,?, '{\"passed\":true,\"issues\":[]}',"
                    " 1, ?, ?, 'schedule', 1, ?, ?)",
                    (DEMO_ACCOUNT, iso(slot), iid, f["theme"], f["hook"], f["cta"], f["appeal"], f["length"], f["structure"],
                     text, f"dryrun-seed-{d}-{hhmm}", iso(slot), iso(slot), iso(slot)))
                pid = cur.lastrowid
                conn.execute("INSERT INTO post_attempts(post_id, kind, outcome, detail, created_at) VALUES (?, 'publish', 'ok', '{}', ?)",
                             (pid, iso(slot)))
                conn.execute("UPDATE ideas SET status='used', use_count=use_count+1, last_used_at=?, last_post_id=? WHERE id=?",
                             (iso(slot), pid, iid))
                post = {"id": pid, "text": text, "hook_style": f["hook"], "cta_key": f["cta"], "length_target": f["length"],
                        "slot_local": hhmm}
                for b in (24, 72):
                    obs = slot + timedelta(hours=b)
                    if obs > t0:
                        continue
                    v = synthetic_metrics(post, b)
                    conn.execute(
                        "INSERT INTO metrics(post_id, account_id, bucket_hours, status, views, likes, replies, reposts, quotes,"
                        " shares, observed_at, is_test) VALUES (?,?,?, 'ok', ?,?,?,?,?,?,?,1)",
                        (pid, DEMO_ACCOUNT, b, v["views"], v["likes"], v["replies"], v["reposts"], v["quotes"], v["shares"],
                         iso(obs)))
    with tx(conn):
        emit(conn, DEMO_ACCOUNT, "demo.seeded", "デモデータを作成しました（すべて架空・テスト用）", severity="info")
    analyze(ctx, {"id": None, "account_id": DEMO_ACCOUNT, "payload": {}})
    for kind in ("daily", "weekly"):
        ps, pe = period_for(kind, t0)
        generate(ctx, DEMO_ACCOUNT, kind, ps, pe, actor="system:demo")
    return {"seeded": True}


def run_scenario(ctx: Ctx, account_id: str, name: str) -> dict:
    conn = ctx.conn
    if name in ("disconnect", "reconnect"):
        with tx(conn):
            if name == "disconnect":
                set_state(conn, "demo_offline", {"until": iso(now() + timedelta(seconds=45))})
            else:
                conn.execute("DELETE FROM runtime_state WHERE key='demo_offline'")
        return {"ok": True, "message": "45秒間、接続断を再現します" if name == "disconnect" else "接続を復帰しました"}
    if name in ("fail_publish", "unknown_publish", "metrics_fail"):
        flag = {"fail_publish": "publish_error", "unknown_publish": "publish_unknown", "metrics_fail": "metrics_error"}[name]
        with tx(conn):
            set_state(conn, f"flag:{flag}", {"set_at": now_iso()})
        if name == "metrics_fail":
            return run_scenario(ctx, account_id, "advance_metrics")
        return run_scenario(ctx, account_id, "publish_now")
    if name == "generate_now":
        slot = now() + timedelta(minutes=20)
        with tx(conn):
            cur = conn.execute("INSERT INTO posts(account_id, slot_at, status, origin, is_test, created_at, updated_at)"
                               " VALUES (?,?,'planned','manual',1,?,?)", (account_id, iso(slot), now_iso(), now_iso()))
            pid = cur.lastrowid
            emit(conn, account_id, "post.planned", "（デモ）投稿枠を作成", post_id=pid)
        jobs.enqueue(conn, account_id, "generate_post", f"gen:{pid}", now(), post_id=pid, max_attempts=2)
        return {"ok": True, "post_id": pid, "message": "投稿の生成を開始しました"}
    if name == "publish_now":
        p = row(conn.execute("SELECT id FROM posts WHERE account_id=? AND status='scheduled' ORDER BY slot_at LIMIT 1",
                             (account_id,)).fetchone())
        if p is None:
            slot = now() + timedelta(seconds=30)
            with tx(conn):
                cur = conn.execute("INSERT INTO posts(account_id, slot_at, status, origin, is_test, created_at, updated_at)"
                                   " VALUES (?,?,'planned','manual',1,?,?)", (account_id, iso(slot), now_iso(), now_iso()))
                pid = cur.lastrowid
            jobs.enqueue(conn, account_id, "generate_post", f"gen:{pid}", now(), post_id=pid, max_attempts=2)
            return {"ok": True, "post_id": pid, "message": "生成後、約30秒で（テスト）公開します"}
        t = iso(now())
        with tx(conn):
            conn.execute("UPDATE posts SET slot_at=?, updated_at=? WHERE id=?", (t, now_iso(), p["id"]))
            conn.execute("UPDATE jobs SET status='cancelled', updated_at=? WHERE post_id=? AND kind='publish_post' AND status='queued'",
                         (now_iso(), p["id"]))
        jobs.enqueue(conn, account_id, "publish_post", f"publish:{p['id']}:{t}", now(), post_id=p["id"], max_attempts=1)
        return {"ok": True, "post_id": p["id"], "message": "予約済みの投稿を今すぐ（テスト）公開します"}
    if name == "advance_metrics":
        with tx(conn):
            n = conn.execute("UPDATE jobs SET run_at=?, updated_at=? WHERE account_id=? AND kind='collect_metrics' AND status='queued'",
                             (now_iso(), now_iso(), account_id)).rowcount
        return {"ok": True, "message": f"実績取得ジョブ{n}件を前倒ししました"}
    if name == "run_analysis":
        jobs.enqueue(conn, account_id, "analyze", f"analyze:{account_id}:manual:{now_iso()}", now(), max_attempts=1)
        return {"ok": True, "message": "分析を開始しました"}
    if name == "run_reports":
        ps, pe = period_for("daily", now())
        jobs.enqueue(conn, account_id, "daily_report", f"report:daily:{account_id}:{iso(ps)}:regen:{now_iso()}", now(),
                     payload={"kind": "daily", "period_start": iso(ps), "period_end": iso(pe), "regenerate": True,
                              "actor": "demo"}, max_attempts=1)
        return {"ok": True, "message": "日次レポートを再生成します"}
    raise Conflict("unknown scenario")
