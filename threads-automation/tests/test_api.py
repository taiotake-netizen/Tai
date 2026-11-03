from __future__ import annotations

from dataclasses import replace

import pytest
from conftest import advance, make_settings
from fastapi.testclient import TestClient

from threads_ops import timeutil
from threads_ops.api import create_app
from threads_ops.context import Ctx
from threads_ops.llm import LLM
from threads_ops.store import create_account
from threads_ops.timeutil import iso

TOKEN = "test-token-0123456789"


@pytest.fixture
def client(ctx):
    cfg = replace(ctx.cfg, api_token=TOKEN)
    c2 = Ctx(cfg=cfg, conn=ctx.conn, llm=LLM(cfg, ctx.conn))
    create_account(ctx.conn, "a1", "A1", data_scope="test", settings=make_settings())
    create_account(ctx.conn, "b1", "B1", data_scope="test", settings=make_settings())
    return TestClient(create_app(c2))


def H(scope="a1", actor="alice"):
    return {"Authorization": f"Bearer {TOKEN}", "X-Account-Scope": scope, "X-Actor": actor}


def test_auth_required(client):
    assert client.get("/v1/accounts").status_code == 401
    assert client.get("/v1/accounts", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/v1/health").status_code == 200          # health is public, contains no data


def test_account_scope_isolation(client):
    r = client.get("/v1/accounts", headers=H("a1"))
    assert [a["id"] for a in r.json()["items"]] == ["a1"]
    assert client.get("/v1/accounts/b1/overview", headers=H("a1")).status_code == 404
    assert client.get("/v1/accounts/b1/ideas", headers=H("a1")).status_code == 404
    assert client.post("/v1/accounts/b1/control/autopilot", json={"enabled": False}, headers=H("a1")).status_code == 404
    assert client.get("/v1/accounts/a1/overview", headers=H("")).status_code == 404     # empty scope sees nothing


def test_overview_and_capabilities(client):
    o = client.get("/v1/accounts/a1/overview", headers=H()).json()
    assert o["mode"]["data"] == "test" and o["mode"]["live_publishing"] is False
    assert {a["id"] for a in o["agents"]} == {"orchestrator", "threads_ops", "content", "analytics"}
    assert all(a["state"] == "unavailable" for a in o["agents"])       # no worker heartbeat → never "running"
    assert o["kpi"]["success_rate_today"] is None
    assert len(o["activity_24h"]) == 24 and sum(o["activity_24h"]) == 0
    assert o["job_stats_24h"] == {}
    caps = client.get("/v1/accounts/a1/capabilities", headers=H()).json()["actions"]
    assert caps["publish.live"]["enabled"] is False and caps["publish.live"]["reason"]
    assert caps["post.delete_published"]["enabled"] is False


def test_settings_patch_conflict_and_validation(client):
    s = client.get("/v1/accounts/a1/settings", headers=H()).json()
    v = s["version"]
    r = client.patch("/v1/accounts/a1/settings", json={"expected_version": v, "patch": {"schedule": {"posts_per_day": 2}}}, headers=H())
    assert r.status_code == 200
    r2 = client.patch("/v1/accounts/a1/settings", json={"expected_version": v, "patch": {"schedule": {"posts_per_day": 1}}}, headers=H())
    assert r2.status_code == 409
    bad = client.patch("/v1/accounts/a1/settings", json={"expected_version": v + 1, "patch": {"schedule": {"post_times": ["25:00"]}}},
                       headers=H())
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "validation_error"
    audit = client.get("/v1/accounts/a1/audit", headers=H()).json()["items"]
    assert any(a["action"] == "settings.update" and a["actor"] == "alice" for a in audit)


def test_events_cursor_and_ingest_idempotent(client):
    body = {"event_id": "evt-000001", "source_system": "ext", "event_type": "ext.note", "occurred_at": iso(timeutil.now()),
            "message": "hello"}
    r1 = client.post("/v1/accounts/a1/events/ingest", json=body, headers=H()).json()
    r2 = client.post("/v1/accounts/a1/events/ingest", json=body, headers=H()).json()
    assert r1["accepted"] and r2["duplicate"]
    first = client.get("/v1/accounts/a1/events", headers=H()).json()
    assert first["items"] and first["cursor"] == first["latest_seq"]
    client.post("/v1/accounts/a1/control/autopilot", json={"enabled": False}, headers=H())
    nxt = client.get(f"/v1/accounts/a1/events?after_seq={first['cursor']}", headers=H()).json()
    assert nxt["items"] and all(e["seq"] > first["cursor"] for e in nxt["items"])
    assert all(e["account_id"] == "a1" for e in nxt["items"])


def test_post_cancel_rules(client, ctx):
    ts = iso(timeutil.now())
    ctx.conn.execute("INSERT INTO posts(account_id, slot_at, status, origin, is_test, created_at, updated_at, text)"
                     " VALUES ('a1', ?, 'published', 'manual', 1, ?, ?, 'x')", (ts, ts, ts))
    pid = ctx.conn.execute("SELECT id FROM posts").fetchone()[0]
    r = client.post(f"/v1/accounts/a1/posts/{pid}/cancel", headers=H())
    assert r.status_code == 409 and "公開済み" in r.json()["error"]["message"]


def test_stop_modes(client):
    r = client.post("/v1/accounts/a1/control/stop", json={"mode": "cancel_queued"}, headers=H()).json()
    assert r["autopilot"]["enabled"] is False and "jobs_cancelled" in r
    assert client.post("/v1/accounts/a1/control/stop", json={"mode": "delete_everything"}, headers=H()).status_code == 422


def test_ideas_crud(client):
    r = client.post("/v1/accounts/a1/ideas", json={"theme": "副業の始め方", "pain": "p", "angle": "a"}, headers=H()).json()
    iid = r["id"]
    advance(seconds=1)
    upd = client.put(f"/v1/accounts/a1/ideas/{iid}", json={"theme": "副業の始め方", "angle": "b", "expected_updated_at": r["updated_at"]},
                     headers=H())
    assert upd.status_code == 200 and upd.json()["angle"] == "b"
    stale = client.put(f"/v1/accounts/a1/ideas/{iid}", json={"theme": "副業の始め方", "angle": "c", "expected_updated_at": r["updated_at"]},
                       headers=H())
    assert stale.status_code == 409
    assert client.post(f"/v1/accounts/a1/ideas/{iid}/status", json={"status": "held"}, headers=H()).json()["status"] == "held"
    assert client.post("/v1/accounts/a1/ideas", json={"theme": "勝手なテーマ"}, headers=H()).status_code == 409
    d = client.get(f"/v1/accounts/a1/ideas/{iid}", headers=H()).json()
    assert len(d["history"]) >= 2


def test_demo_scenarios_only_in_demo(client):
    assert client.post("/v1/demo/scenario", json={"name": "generate_now"}, headers=H()).status_code == 404


def test_assistant_unavailable_when_no_ai(ctx):
    cfg = replace(ctx.cfg, api_token=TOKEN, llm_provider="none")
    c2 = Ctx(cfg=cfg, conn=ctx.conn, llm=LLM(cfg, ctx.conn))
    create_account(ctx.conn, "a1", "A1", data_scope="test", settings=make_settings())
    cl = TestClient(create_app(c2))
    r = cl.post("/v1/accounts/a1/assistant/runs", json={"kind": "summary"}, headers=H()).json()
    assert r["status"] == "unavailable" and r["error"]
    assert cl.get("/v1/accounts/a1/capabilities", headers=H()).json()["actions"]["assistant.draft"]["enabled"] is False


def test_production_requires_token(ctx):
    cfg = replace(ctx.cfg, app_env="production", api_token=None)
    with pytest.raises(RuntimeError):
        create_app(Ctx(cfg=cfg, conn=ctx.conn, llm=LLM(cfg, ctx.conn)))
