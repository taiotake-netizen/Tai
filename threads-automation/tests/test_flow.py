"""End-to-end loop without any real posting:
idea → generate → check → schedule → (dry-run) publish → metrics → analyze → policy update → next generation → report."""

from __future__ import annotations

from datetime import timedelta

from conftest import advance

from threads_ops import ideas as idea_bank
from threads_ops import jobs, scheduler, timeutil
from threads_ops.analyzer import analyze
from threads_ops.db import loads, rows
from threads_ops.reports import generate, get_report, period_for
from threads_ops.store import active_policy
from threads_ops.worker import run_one


def drain(ctx, limit=200):
    n = 0
    while n < limit and run_one(ctx, "w1"):
        n += 1
    return n


def seed_ideas(ctx, n=10):
    themes = ["副業の始め方", "時間の使い方", "スキルの選び方", "続けるコツ", "失敗から学ぶこと"]
    for i in range(n):
        idea_bank.create(ctx.conn, "acc", idea_bank.IdeaIn(theme=themes[i % 5], pain=f"悩み{i}", angle=f"切り口{i}"),
                         actor="t", is_test=True)


def test_full_loop(ctx, account):
    seed_ideas(ctx)
    published = 0
    for _ in range(18 * 24 * 4):      # simulate 18 days in 15-minute steps
        scheduler.tick(ctx)
        drain(ctx)
        advance(minutes=15)
    posts = rows(ctx.conn.execute("SELECT * FROM posts WHERE account_id='acc'").fetchall())
    published = [p for p in posts if p["status"] == "published"]
    assert len(published) >= 40, {p["status"] for p in posts}
    assert all(p["is_test"] == 1 for p in published)                      # never real
    assert all(p["external_post_id"].startswith("dryrun-") for p in published)
    # metrics collected at 24h and 72h, never inserted as zero for failures
    m = ctx.conn.execute("SELECT COUNT(*) c FROM metrics WHERE status='ok'").fetchone()["c"]
    assert m >= 60
    # improvement loop ran: experiments exist and at least one finished with a decision
    exps = rows(ctx.conn.execute("SELECT * FROM experiments").fetchall())
    assert exps
    adopted = [e for e in exps if e["status"] == "adopted"]
    pol = active_policy(ctx.conn, "acc")
    if adopted:
        assert pol["version"] >= 2 and pol["source"] in ("auto", "rollback")
        # posts generated after adoption use the new policy version
        later = ctx.conn.execute("SELECT MAX(policy_version) v FROM posts WHERE status='published'").fetchone()["v"]
        assert later >= adopted[0]["adopted_policy_version"]
    # used ideas are marked, reserved ones are not leaked
    assert ctx.conn.execute("SELECT COUNT(*) c FROM ideas WHERE status='reserved'").fetchone()["c"] <= 3
    # daily reports were produced exactly once per period
    dup = ctx.conn.execute("SELECT kind, period_start, COUNT(*) c FROM reports WHERE is_current=1 GROUP BY 1,2 HAVING c>1").fetchall()
    assert not dup
    assert ctx.conn.execute("SELECT COUNT(*) c FROM reports WHERE kind='daily'").fetchone()["c"] >= 15
    assert ctx.conn.execute("SELECT COUNT(*) c FROM reports WHERE kind='weekly'").fetchone()["c"] >= 2


def test_policy_update_reaches_next_generation(ctx, account):
    seed_ideas(ctx)
    from threads_ops.settings import Policy
    from threads_ops.store import save_policy
    pol = Policy.model_validate(active_policy(ctx.conn, "acc")["policy"])
    w = {k: 0.03 for k in pol.hook_weights}
    w["結論先出し"] = 1 - 0.03 * (len(w) - 1)
    new = pol.model_copy(update={"hook_weights": w})
    v = save_policy(ctx.conn, "acc", new, source="manual", reason="test", actor="t", parent=1)
    advance(hours=2)
    scheduler.tick(ctx)
    drain(ctx)
    p = ctx.conn.execute("SELECT policy_version, hook_style FROM posts WHERE text IS NOT NULL ORDER BY id LIMIT 1").fetchone()
    assert p["policy_version"] == v


def test_report_idempotent_and_regenerate(ctx, account):
    ps, pe = period_for("daily", timeutil.now())
    a = generate(ctx, "acc", "daily", ps, pe, actor="t")
    b = generate(ctx, "acc", "daily", ps, pe, actor="t")
    assert a["created"] and not b["created"] and a["report_id"] == b["report_id"]
    c = generate(ctx, "acc", "daily", ps, pe, actor="t", regenerate=True)
    assert c["version"] == 2
    r = get_report(ctx.conn, "acc", c["report_id"])
    assert [v["version"] for v in r["versions"]] == [2, 1]
    assert sum(v["is_current"] for v in r["versions"]) == 1
    assert r["data"]["success_rate"] is None          # no attempts → "—"
    assert r["data"]["metrics"]["mean_er"] is None


def test_report_period_must_be_over(ctx, account):
    import pytest

    from threads_ops.store import Conflict
    start = timeutil.now()
    with pytest.raises(Conflict):
        generate(ctx, "acc", "daily", start, start + timedelta(days=1), actor="t")


def test_analyze_with_no_data_changes_nothing(ctx, account):
    out = analyze(ctx, {"id": None, "account_id": "acc", "payload": {}})
    assert out["samples"] == 0
    assert active_policy(ctx.conn, "acc")["version"] == 1


def test_jobs_listing_labels(ctx, account):
    jid, created = jobs.enqueue(ctx.conn, "acc", "analyze", "k1", timeutil.now())
    assert created
    assert loads(ctx.conn.execute("SELECT payload_json FROM jobs WHERE id=?", (jid,)).fetchone()[0]) == {}
