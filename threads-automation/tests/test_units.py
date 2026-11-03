from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from conftest import advance, live_ctx, make_settings

from threads_ops import analyzer, jobs, publishing, scheduler, timeutil
from threads_ops import ideas as idea_bank
from threads_ops.db import row
from threads_ops.generator import generate_post
from threads_ops.llm import AIUnavailable
from threads_ops.quality import rule_check
from threads_ops.settings import (
    AccountSettingsModel,
    ApprovedFact,
    Policy,
    PolicyViolation,
    validate_policy_change,
)
from threads_ops.store import (
    Conflict,
    active_policy,
    create_account,
    get_settings,
    save_policy,
    update_settings,
)
from threads_ops.timeutil import JST, daily_period, iso, weekly_period
from threads_ops.worker import run_one

# ------------------------------------------------------------------ time boundaries


def test_daily_and_weekly_periods_in_jst():
    ref = datetime(2026, 11, 2, 0, 30, tzinfo=UTC)          # Mon 09:30 JST
    s, e = daily_period(ref, JST)
    assert (iso(s), iso(e)) == ("2026-10-31T15:00:00.000000Z", "2026-11-01T15:00:00.000000Z")
    s, e = weekly_period(ref, JST)
    assert (iso(s), iso(e)) == ("2026-10-25T15:00:00.000000Z", "2026-11-01T15:00:00.000000Z")
    # 23:59 JST Sunday belongs to the previous week relative to Monday 00:00
    ref2 = datetime(2026, 11, 1, 14, 59, tzinfo=UTC)        # Sun 23:59 JST
    s2, e2 = weekly_period(ref2, JST)
    assert iso(e2) == "2026-10-25T15:00:00.000000Z"


# ------------------------------------------------------------------ quality


def _chk(text, s=None, **kw):
    s = s or AccountSettingsModel()
    base = dict(recent_texts=[], recent_themes=[], recent_ctas=[], theme="副業の始め方", cta_key="none")
    base.update(kw)
    return rule_check(text, s, **base)


def codes(r):
    return {i["code"] for i in r.issues if i["severity"] == "error"}


GOOD = "副業を始めるとき、まず大事なのは小さく試すことです。\n・1日15分の時間を作る\n・やらないことを決める\n・記録を残す\n焦らず続けていきましょう。"


def test_quality_rules():
    assert _chk(GOOD).passed
    assert "empty" in codes(_chk("  "))
    assert "too_short" in codes(_chk("短い"))
    assert "too_long_api" in codes(_chk("あ" * 501))
    assert "banned_phrase" in codes(_chk(GOOD + "誰でも簡単に始められます"))
    assert "guarantee" in codes(_chk(GOOD + "必ず稼げます"))
    assert "unverified_claim" in codes(_chk(GOOD + "受講生のAさんは月収30万円になりました"))
    assert "unverified_number" in codes(_chk(GOOD + "収益は20%アップ"))
    assert "url_not_allowed" in codes(_chk(GOOD + " https://evil.example.com/x"))
    assert "url_not_allowed" in codes(_chk(GOOD + " bit.ly/abc"))
    assert "broken_output" in codes(_chk(GOOD + "```"))
    assert "duplicate" in codes(_chk(GOOD, recent_texts=[GOOD]))
    assert "too_similar" in codes(_chk(GOOD + "！", recent_texts=[GOOD]))
    assert "theme_streak" in codes(_chk(GOOD, recent_themes=["副業の始め方", "副業の始め方"]))
    assert "cta_streak" in codes(_chk(GOOD, cta_key="save", recent_ctas=["save", "save"]))


def test_approved_fact_allows_number_and_domain():
    s = AccountSettingsModel()
    s.business.approved_facts = [ApprovedFact(id="f1", statement="参加費は月3,000円", source="料金表")]
    s.business.allowed_domains = ["example.jp"]
    assert _chk(GOOD + "参加費は月3,000円です https://www.example.jp/join", s).passed


def test_cta_url_must_be_in_allowed_domains():
    with pytest.raises(ValueError):
        AccountSettingsModel.model_validate({"business": {"cta_options": [{"key": "lp", "text": "詳しくは", "url": "https://x.com"}]}})


# ------------------------------------------------------------------ jobs


def test_enqueue_idempotent_and_single_claim(ctx, account):
    a = jobs.enqueue(ctx.conn, "acc", "analyze", "same", timeutil.now())
    b = jobs.enqueue(ctx.conn, "acc", "analyze", "same", timeutil.now())
    assert a[0] == b[0] and a[1] and not b[1]
    j1 = jobs.claim(ctx.conn, "w1")
    j2 = jobs.claim(ctx.conn, "w2")
    assert j1 and j1["id"] == a[0] and j2 is None


def test_ai_concurrency_limit(ctx, account):
    jobs.enqueue(ctx.conn, "acc", "analyze", "a1", timeutil.now())
    jobs.enqueue(ctx.conn, "acc", "daily_report", "a2", timeutil.now())
    jobs.enqueue(ctx.conn, "acc", "collect_metrics", "m1", timeutil.now())
    first = jobs.claim(ctx.conn, "w1", max_ai_concurrency=1)
    second = jobs.claim(ctx.conn, "w2", max_ai_concurrency=1)
    assert first["kind"] == "analyze" and second["kind"] == "collect_metrics"


def test_cancel_semantics(ctx, account):
    jid, _ = jobs.enqueue(ctx.conn, "acc", "analyze", "c1", timeutil.now())
    assert jobs.request_cancel(ctx.conn, "acc", jid, "u")["result"] == "cancelled"
    jid2, _ = jobs.enqueue(ctx.conn, "acc", "publish_post", "c2", timeutil.now())
    jobs.claim(ctx.conn, "w")
    with pytest.raises(Conflict):
        jobs.request_cancel(ctx.conn, "acc", jid2, "u")       # publishing cannot be cancelled
    jid3, _ = jobs.enqueue(ctx.conn, "acc", "analyze", "c3", timeutil.now())
    j = jobs.claim(ctx.conn, "w")
    assert j["id"] == jid3
    assert jobs.request_cancel(ctx.conn, "acc", jid3, "u")["result"] == "cancel_requested"
    jobs.finish(ctx.conn, j, "failed", error="x")
    assert row(ctx.conn.execute("SELECT status FROM jobs WHERE id=?", (jid3,)).fetchone())["status"] == "cancelled"
    with pytest.raises(Conflict):
        jobs.retry(ctx.conn, "acc", jid2, "u")                 # publish never retried


def test_dead_worker_during_publish_becomes_unknown_then_reconciled(ctx, account):
    advance(hours=2)
    scheduler.tick(ctx)
    while run_one(ctx, "w"):
        pass
    post = row(ctx.conn.execute("SELECT * FROM posts WHERE status='scheduled' ORDER BY slot_at LIMIT 1").fetchone())
    timeutil.set_clock(datetime.fromisoformat(post["slot_at"].replace("Z", "+00:00")))
    j = jobs.claim(ctx.conn, "dying")
    assert j["kind"] == "publish_post"
    ctx.conn.execute("UPDATE posts SET status='publishing' WHERE id=?", (post["id"],))
    advance(minutes=6)                          # lease expires
    scheduler.tick(ctx)
    assert row(ctx.conn.execute("SELECT status FROM posts WHERE id=?", (post["id"],)).fetchone())["status"] == "unknown"
    while run_one(ctx, "w"):
        pass
    # dry-run: the simulator never posted, so reconciliation marks it failed — and it was NOT re-posted
    p = row(ctx.conn.execute("SELECT status FROM posts WHERE id=?", (post["id"],)).fetchone())
    assert p["status"] == "failed"
    assert ctx.conn.execute("SELECT COUNT(*) c FROM post_attempts WHERE post_id=? AND kind='publish' AND outcome='ok'",
                            (post["id"],)).fetchone()["c"] == 0


# ------------------------------------------------------------------ ideas


def test_idea_reservation_is_exclusive_and_released_on_failure(ctx, account):
    s, _ = get_settings(ctx.conn, "acc")
    idea_bank.create(ctx.conn, "acc", idea_bank.IdeaIn(theme="副業の始め方"), actor="t", is_test=True)
    a = idea_bank.reserve(ctx.conn, "acc", 101, s, preferred_theme=None, forced_theme=False, avoid_themes=[],
                          include_test=True, rng=random.Random(1))
    b = idea_bank.reserve(ctx.conn, "acc", 102, s, preferred_theme=None, forced_theme=False, avoid_themes=[],
                          include_test=True, rng=random.Random(1))
    assert a is not None and b is None
    again = idea_bank.reserve(ctx.conn, "acc", 101, s, preferred_theme=None, forced_theme=False, avoid_themes=[],
                              include_test=True, rng=random.Random(1))
    assert again["id"] == a["id"]                               # same post → same idea (retry-safe)
    idea_bank.release(ctx.conn, 101)
    i = idea_bank.get(ctx.conn, "acc", a["id"])
    assert i["status"] == "ready" and i["use_count"] == 0       # failure does not consume


def test_idea_reuse_interval(ctx, account):
    s, _ = get_settings(ctx.conn, "acc")
    idea = idea_bank.create(ctx.conn, "acc", idea_bank.IdeaIn(theme="副業の始め方"), actor="t", is_test=True)
    idea_bank.reserve(ctx.conn, "acc", 1, s, preferred_theme=None, forced_theme=False, avoid_themes=[], include_test=True,
                      rng=random.Random(1))
    idea_bank.mark_used(ctx.conn, 1)
    kw = dict(preferred_theme=None, forced_theme=False, avoid_themes=[], include_test=True, rng=random.Random(1))
    assert idea_bank.reserve(ctx.conn, "acc", 2, s, **kw) is None
    advance(days=s.ideas.reuse_interval_days + 1)
    assert idea_bank.reserve(ctx.conn, "acc", 2, s, **kw)["id"] == idea["id"]


def test_live_ideas_never_mix_with_test_ideas(ctx, account):
    s, _ = get_settings(ctx.conn, "acc")
    idea_bank.create(ctx.conn, "acc", idea_bank.IdeaIn(theme="副業の始め方"), actor="t", is_test=True)
    assert idea_bank.reserve(ctx.conn, "acc", 1, s, preferred_theme=None, forced_theme=False, avoid_themes=[],
                             include_test=False, rng=random.Random(1)) is None


# ------------------------------------------------------------------ policy / improvement


def test_policy_envelope(ctx, account):
    s, _ = get_settings(ctx.conn, "acc")
    p = Policy.model_validate(active_policy(ctx.conn, "acc")["policy"])
    big = dict(p.hook_weights)
    k = next(iter(big))
    big[k] += 0.3
    others = [x for x in big if x != k]
    for o in others:
        big[o] -= 0.3 / len(others)
    with pytest.raises(PolicyViolation):
        validate_policy_change(p, p.model_copy(update={"hook_weights": big}), s, max_step=0.15)
    s_locked = s.model_copy(update={"locked": ["hook"]})
    small = dict(p.hook_weights)
    small[k] += 0.05
    small[others[0]] -= 0.05
    with pytest.raises(PolicyViolation):
        validate_policy_change(p, p.model_copy(update={"hook_weights": small}), s_locked, max_step=0.15)
    validate_policy_change(p, p.model_copy(update={"hook_weights": small}), s, max_step=0.15)
    with pytest.raises(PolicyViolation):
        validate_policy_change(p, p.model_copy(update={"post_times": ["03:00", "12:15", "18:00"]}), s, max_step=0.15)
    bad_keys = dict(p.theme_weights)
    bad_keys["勝手なテーマ"] = 0.0
    with pytest.raises(PolicyViolation):
        validate_policy_change(p, p.model_copy(update={"theme_weights": bad_keys}), s, max_step=None)


def _fake_published(ctx, n, *, hook, er, arm=None, exp_id=None, version=1, start_days=10):
    t = timeutil.now()
    for i in range(n):
        ts = iso(t - timedelta(days=start_days) + timedelta(hours=i * 7 + (1 if arm == "treatment" else 0)))
        cur = ctx.conn.execute(
            "INSERT INTO posts(account_id, slot_at, status, policy_version, experiment_id, experiment_arm, hook_style, theme,"
            " text, published_at, origin, is_test, created_at, updated_at) VALUES ('acc', ?, 'published', ?, ?, ?, ?, '副業の始め方',"
            " ?, ?, 'manual', 1, ?, ?)", (ts, version, exp_id, arm, hook, f"t{i}{hook}{arm}", ts, ts, ts))
        views = 1000
        likes = int(views * (er + (i % 3 - 1) * 0.002))
        ctx.conn.execute("INSERT INTO metrics(post_id, account_id, bucket_hours, status, views, likes, replies, reposts, quotes,"
                         " observed_at, is_test) VALUES (?, 'acc', 24, 'ok', ?, ?, 0, 0, 0, ?, 1)",
                         (cur.lastrowid, views, likes, ts))


def test_experiment_adoption_updates_policy_within_step(ctx, account):
    ctx.conn.execute("INSERT INTO experiments(account_id, variable, hypothesis, control_value, treatment_value,"
                     " base_policy_version, status, started_at) VALUES ('acc','hook','h','問いかけ','結論先出し',1,'running',?)",
                     (iso(timeutil.now() - timedelta(days=5)),))
    exp_id = ctx.conn.execute("SELECT id FROM experiments").fetchone()["id"]
    _fake_published(ctx, 6, hook="問いかけ", er=0.03, arm="control", exp_id=exp_id)
    _fake_published(ctx, 6, hook="結論先出し", er=0.05, arm="treatment", exp_id=exp_id)
    before = Policy.model_validate(active_policy(ctx.conn, "acc")["policy"])
    out = analyzer.analyze(ctx, {"id": None, "account_id": "acc", "payload": {}})
    assert out["experiment"]["decision"] == "adopt", out
    pol = active_policy(ctx.conn, "acc")
    assert pol["version"] == 2, (out, ctx.conn.execute("SELECT result_json FROM experiments").fetchone()[0])
    assert pol["version"] == 2 and pol["source"] == "auto"
    after = Policy.model_validate(pol["policy"])
    assert after.hook_weights["結論先出し"] > before.hook_weights["結論先出し"]
    assert max(abs(after.hook_weights[k] - before.hook_weights[k]) for k in before.hook_weights) <= 0.15 + 1e-6
    assert ctx.conn.execute("SELECT status FROM experiments WHERE id=?", (exp_id,)).fetchone()["status"] == "adopted"


def test_insufficient_data_does_not_decide(ctx, account):
    ctx.conn.execute("INSERT INTO experiments(account_id, variable, hypothesis, control_value, treatment_value,"
                     " base_policy_version, status, started_at) VALUES ('acc','hook','h','問いかけ','結論先出し',1,'running',?)",
                     (iso(timeutil.now()),))
    exp_id = ctx.conn.execute("SELECT id FROM experiments").fetchone()["id"]
    _fake_published(ctx, 2, hook="結論先出し", er=0.2, arm="treatment", exp_id=exp_id)   # one lucky post is not a pattern
    out = analyzer.analyze(ctx, {"id": None, "account_id": "acc", "payload": {}})
    assert out["experiment"]["decision"] == "collecting"
    assert active_policy(ctx.conn, "acc")["version"] == 1


def test_failed_metrics_are_excluded_not_zero(ctx, account):
    _fake_published(ctx, 3, hook="問いかけ", er=0.05)
    ctx.conn.execute("UPDATE metrics SET status='failed', views=NULL, likes=NULL WHERE id=1")
    s, _ = get_settings(ctx.conn, "acc")
    data = analyzer.dataset(ctx, "acc", s, include_test=True)
    assert len(data) == 2 and all(d["er"] > 0 for d in data)


def test_auto_rollback_on_drop_and_manual_rollback(ctx, account):
    s, _ = get_settings(ctx.conn, "acc")
    p1 = Policy.model_validate(active_policy(ctx.conn, "acc")["policy"])
    v2 = save_policy(ctx.conn, "acc", p1, source="auto", reason="t", actor="t", parent=1)
    _fake_published(ctx, 6, hook="問いかけ", er=0.06, version=1, start_days=12)
    _fake_published(ctx, 6, hook="問いかけ", er=0.02, version=v2, start_days=5)
    out = analyzer.analyze(ctx, {"id": None, "account_id": "acc", "payload": {}})
    assert out["rollback"]["from"] == v2
    assert active_policy(ctx.conn, "acc")["source"] == "rollback"
    v4 = analyzer.manual_rollback(ctx, "acc", 2, "user")
    assert active_policy(ctx.conn, "acc")["version"] == v4


def test_settings_optimistic_concurrency(ctx, account):
    s, v = get_settings(ctx.conn, "acc")
    update_settings(ctx.conn, "acc", s, v, "a")
    with pytest.raises(Conflict):
        update_settings(ctx.conn, "acc", s, v, "b")


# ------------------------------------------------------------------ AI availability / budget


def _scheduled_post(ctx):
    advance(hours=2)
    scheduler.tick(ctx)
    return row(ctx.conn.execute("SELECT * FROM posts WHERE status='planned' ORDER BY slot_at LIMIT 1").fetchone())


def test_ai_not_configured_keeps_post_unpublished(ctx, account):
    lc = live_ctx(ctx, provider="none")
    post = _scheduled_post(ctx)
    jid, _ = jobs.enqueue(ctx.conn, "acc", "generate_post", "g-x", timeutil.now(), post_id=post["id"])
    j = jobs.claim(ctx.conn, "w")
    while j and j["id"] != jid:
        jobs.finish(ctx.conn, j, "cancelled")
        j = jobs.claim(ctx.conn, "w")
    with pytest.raises(AIUnavailable):
        generate_post(lc, j)
    p = row(ctx.conn.execute("SELECT status FROM posts WHERE id=?", (post["id"],)).fetchone())
    assert p["status"] == "planned"
    assert ctx.conn.execute("SELECT COUNT(*) c FROM ideas WHERE status='reserved'").fetchone()["c"] == 0


def _openai_transport(calls, *, fail_param=None, usage=(100, 50)):
    def handler(req: httpx.Request):
        body = json.loads(req.content)
        calls.append(body)
        if fail_param and fail_param in body:
            return httpx.Response(400, json={"error": {"message": f"Unsupported parameter: '{fail_param}'", "param": fail_param}})
        return httpx.Response(200, json={"output": [{"type": "message", "content": [{"type": "output_text",
                                         "text": '{"ok": true}'}]}], "usage": {"input_tokens": usage[0], "output_tokens": usage[1]}})
    return httpx.MockTransport(handler)


def test_openai_budget_required_and_enforced(ctx, account, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real-000000")
    calls: list = []
    lc = live_ctx(ctx, provider="openai", llm_transport=_openai_transport(calls))
    s = make_settings()
    with pytest.raises(AIUnavailable) as e:
        lc.llm.complete("acc", s, "x", "sys", "user")
    assert e.value.code == "budget_not_set" and not calls
    s.budget.daily_usd, s.budget.monthly_usd = 0.001, 1.0
    s.budget.price_input_per_mtok_usd, s.budget.price_output_per_mtok_usd = 1.0, 4.0
    s.budget.max_output_tokens = 200
    lc.llm.complete("acc", s, "x", "sys", "user")              # ~0.0008 reserved → fits
    with pytest.raises(AIUnavailable) as e2:
        lc.llm.complete("acc", s, "x", "sys", "user")
    assert e2.value.code == "budget_daily" and len(calls) == 1
    u = row(ctx.conn.execute("SELECT * FROM ai_usage WHERE status='committed'").fetchone())
    assert u["input_tokens"] == 100 and u["cost_kind"] == "measured_tokens_estimated_price"


def test_openai_drops_unsupported_param(ctx, account, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real-000000")
    calls: list = []
    lc = live_ctx(ctx, provider="openai", llm_transport=_openai_transport(calls, fail_param="reasoning"))
    s = make_settings()
    s.budget.daily_usd = s.budget.monthly_usd = 1.0
    s.budget.price_input_per_mtok_usd = s.budget.price_output_per_mtok_usd = 1.0
    res = lc.llm.complete("acc", s, "x", "sys", "user")
    assert res.text == '{"ok": true}'
    assert "reasoning" in calls[0] and "reasoning" not in calls[1]
    assert "temperature" not in calls[0]


# ------------------------------------------------------------------ live publishing (mocked Threads API)


def _threads_transport(log, *, publish_mode="ok", recent_text=None):
    def handler(req: httpx.Request):
        log.append((req.method, req.url.path))
        p = req.url.path
        if p.endswith("/threads_publishing_limit"):
            return httpx.Response(200, json={"data": [{"quota_usage": 1, "config": {"quota_total": 250}}]})
        if req.method == "POST" and p.endswith("/threads"):
            return httpx.Response(200, json={"id": "C1"})
        if p.endswith("/threads_publish"):
            if publish_mode == "timeout":
                raise httpx.ReadTimeout("timeout", request=req)
            return httpx.Response(200, json={"id": "M1"})
        if req.method == "GET" and p.endswith("/threads"):
            return httpx.Response(200, json={"data": [{"id": "M9", "text": recent_text or "zzz", "permalink": "https://www.threads.net/x"}]})
        if p.endswith("/M1") or p.endswith("/M9"):
            return httpx.Response(200, json={"id": "M1", "permalink": "https://www.threads.net/@a/post/1"})
        if p.endswith("/insights"):
            return httpx.Response(200, json={"data": [{"name": "views", "values": [{"value": 120}]},
                                                      {"name": "likes", "values": [{"value": 7}]}]})
        return httpx.Response(404, json={"error": {"message": "nf"}})
    return httpx.MockTransport(handler)


def _live_account(ctx, monkeypatch):
    monkeypatch.setenv("THREADS_ACCESS_TOKEN", "tok-not-real-000000000")
    s = make_settings()
    s.live_publish_enabled = True
    s.checks.ai_review_enabled = False
    create_account(ctx.conn, "live1", "本番", data_scope="live", external_user_id="123",
                   token_env="THREADS_ACCESS_TOKEN", settings=s)
    ctx.conn.execute("INSERT INTO posts(account_id, slot_at, status, text, check_json, origin, is_test, created_at, updated_at)"
                     " VALUES ('live1', ?, 'scheduled', 'こんにちは、本番テスト本文です', '{\"passed\":true}', 'schedule', 0, ?, ?)",
                     (iso(timeutil.now()), iso(timeutil.now()), iso(timeutil.now())))
    return ctx.conn.execute("SELECT id FROM posts WHERE account_id='live1'").fetchone()["id"]


def test_live_publish_flow_with_mocked_api(ctx, monkeypatch):
    pid = _live_account(ctx, monkeypatch)
    log: list = []
    lc = live_ctx(ctx, threads_transport=_threads_transport(log))
    out = publishing.publish_post(lc, {"id": 0, "post_id": pid, "payload": {}})
    assert out["status"] == "published" and out["live"]
    p = row(ctx.conn.execute("SELECT * FROM posts WHERE id=?", (pid,)).fetchone())
    assert p["external_post_id"] == "M1" and p["external_container_id"] == "C1" and p["is_test"] == 0
    j = row(ctx.conn.execute("SELECT * FROM jobs WHERE post_id=? AND kind='collect_metrics' ORDER BY run_at LIMIT 1", (pid,)).fetchone())
    j["payload"] = json.loads(j["payload_json"])
    j["attempts"] = 1
    publishing.collect_metrics(lc, j)
    m = row(ctx.conn.execute("SELECT * FROM metrics WHERE post_id=?", (pid,)).fetchone())
    assert m["views"] == 120 and m["likes"] == 7 and m["replies"] is None    # missing metric stays NULL


def test_live_publish_timeout_becomes_unknown_and_reconciles(ctx, monkeypatch):
    pid = _live_account(ctx, monkeypatch)
    log: list = []
    lc = live_ctx(ctx, threads_transport=_threads_transport(log, publish_mode="timeout",
                                                            recent_text="こんにちは、本番テスト本文です"))
    out = publishing.publish_post(lc, {"id": 0, "post_id": pid, "payload": {}})
    assert out["status"] == "unknown"
    assert sum(1 for m, p in log if p.endswith("/threads_publish")) == 1     # exactly one publish call
    rj = row(ctx.conn.execute("SELECT * FROM jobs WHERE kind='reconcile_post'").fetchone())
    rj["payload"] = json.loads(rj["payload_json"])
    res = publishing.reconcile_post(lc, rj)
    assert res["resolved"] == "published"
    assert row(ctx.conn.execute("SELECT status, external_post_id FROM posts WHERE id=?", (pid,)).fetchone())["external_post_id"] == "M9"


def test_dry_run_never_publishes_non_test_post(ctx, monkeypatch):
    pid = _live_account(ctx, monkeypatch)
    out = publishing.publish_post(ctx, {"id": 0, "post_id": pid, "payload": {}})   # ctx = dry-run config
    assert "skipped" in out
    assert row(ctx.conn.execute("SELECT status FROM posts WHERE id=?", (pid,)).fetchone())["status"] == "skipped"


def test_repeated_ticks_are_idempotent_and_do_not_burn_ids(ctx, account):
    scheduler.tick(ctx)
    before = (ctx.conn.execute("SELECT COUNT(*), MAX(id) FROM jobs").fetchone(),
              ctx.conn.execute("SELECT COUNT(*), MAX(id) FROM posts").fetchone())
    for _ in range(20):
        scheduler.tick(ctx)
    after = (ctx.conn.execute("SELECT COUNT(*), MAX(id) FROM jobs").fetchone(),
             ctx.conn.execute("SELECT COUNT(*), MAX(id) FROM posts").fetchone())
    assert [tuple(r) for r in before] == [tuple(r) for r in after]


def test_repeated_ticks_emit_no_duplicate_planned_events(ctx, account):
    scheduler.tick(ctx)
    n1 = ctx.conn.execute("SELECT COUNT(*) FROM events WHERE event_type='post.planned'").fetchone()[0]
    for _ in range(5):
        scheduler.tick(ctx)
    n2 = ctx.conn.execute("SELECT COUNT(*) FROM events WHERE event_type='post.planned'").fetchone()[0]
    assert n1 > 0 and n1 == n2


def test_manual_posts_survive_schedule_cleanup(ctx, account):
    from threads_ops.timeutil import iso as _iso
    t = _iso(timeutil.now() + timedelta(minutes=7))
    ctx.conn.execute("INSERT INTO posts(account_id, slot_at, status, origin, is_test, created_at, updated_at)"
                     " VALUES ('acc', ?, 'planned', 'manual', 1, ?, ?)", (t, t, t))
    scheduler.tick(ctx)
    assert ctx.conn.execute("SELECT status FROM posts WHERE origin='manual'").fetchone()[0] == "planned"
