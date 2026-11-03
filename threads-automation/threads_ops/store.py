"""Repository helpers: accounts, settings, policy versions, events, audit, runtime state."""

from __future__ import annotations

import sqlite3
import uuid
from typing import Any

from . import SOURCE_SYSTEM
from .db import dumps, loads, row, rows, tx
from .settings import AccountSettingsModel, Policy, initial_policy, reconcile_policy
from .timeutil import now_iso


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


# ------------------------------------------------------------------ accounts / settings

def create_account(conn: sqlite3.Connection, account_id: str, display_name: str, *, data_scope: str = "live",
                   external_user_id: str | None = None, token_env: str | None = None,
                   settings: AccountSettingsModel | None = None, actor: str = "system") -> dict:
    s = settings or AccountSettingsModel()
    ts = now_iso()
    with tx(conn):
        conn.execute(
            "INSERT INTO accounts(id, display_name, external_user_id, token_env, data_scope, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (account_id, display_name, external_user_id, token_env, data_scope, ts, ts),
        )
        conn.execute(
            "INSERT INTO account_settings(account_id, settings_json, version, updated_at, updated_by) VALUES (?,?,1,?,?)",
            (account_id, s.model_dump_json(), ts, actor),
        )
        conn.execute(
            "INSERT INTO policy_versions(account_id, version, parent_version, policy_json, source, reason, is_active,"
            " created_at, created_by) VALUES (?,?,?,?,?,?,1,?,?)",
            (account_id, 1, None, initial_policy(s).model_dump_json(), "initial", "初期方針（全候補を均等に試す）", ts, actor),
        )
        audit(conn, account_id, actor, "account.create", account_id, {"display_name": display_name, "data_scope": data_scope})
    return get_account(conn, account_id)


def get_account(conn: sqlite3.Connection, account_id: str) -> dict:
    r = row(conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone())
    if r is None:
        raise NotFound(f"account {account_id}")
    return r


def list_accounts(conn: sqlite3.Connection, scope: set[str] | None) -> list[dict]:
    rs = rows(conn.execute("SELECT * FROM accounts ORDER BY created_at").fetchall())
    return [a for a in rs if scope is None or a["id"] in scope]


def is_test_scope(account: dict) -> bool:
    return account["data_scope"] in ("demo", "test")


def get_settings(conn: sqlite3.Connection, account_id: str) -> tuple[AccountSettingsModel, int]:
    r = conn.execute("SELECT settings_json, version FROM account_settings WHERE account_id=?", (account_id,)).fetchone()
    if r is None:
        raise NotFound(f"settings {account_id}")
    return AccountSettingsModel.model_validate_json(r["settings_json"]), r["version"]


def update_settings(conn: sqlite3.Connection, account_id: str, new: AccountSettingsModel, expected_version: int,
                    actor: str) -> int:
    with tx(conn):
        old, ver = get_settings(conn, account_id)
        if ver != expected_version:
            raise Conflict(f"settings were updated by someone else (current version {ver})")
        conn.execute(
            "UPDATE account_settings SET settings_json=?, version=version+1, updated_at=?, updated_by=? WHERE account_id=?",
            (new.model_dump_json(), now_iso(), actor, account_id),
        )
        diff = _diff(old.model_dump(), new.model_dump())
        audit(conn, account_id, actor, "settings.update", account_id, {"changes": diff})
        # keep active policy aligned with structural settings (themes, CTAs, times)
        pol = active_policy(conn, account_id)
        aligned = reconcile_policy(Policy.model_validate(pol["policy"]), new)
        if aligned.model_dump() != pol["policy"]:
            save_policy(conn, account_id, aligned, source="manual", reason="設定変更に合わせて方針の候補を同期",
                        actor=actor, parent=pol["version"])
        emit(conn, account_id, "settings.updated", "設定を更新しました", payload={"fields": sorted(diff)[:30]})
    return ver + 1


def _diff(a: Any, b: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(a, dict) and isinstance(b, dict):
        for k in set(a) | set(b):
            out.update(_diff(a.get(k), b.get(k), f"{prefix}{k}."))
    elif a != b:
        out[prefix.rstrip(".")] = {"from": a, "to": b}
    return out


# ------------------------------------------------------------------ policy

def active_policy(conn: sqlite3.Connection, account_id: str) -> dict:
    r = row(conn.execute(
        "SELECT * FROM policy_versions WHERE account_id=? AND is_active=1", (account_id,)).fetchone())
    if r is None:
        raise NotFound(f"policy {account_id}")
    r["policy"] = loads(r.pop("policy_json"))
    return r


def get_policy_version(conn: sqlite3.Connection, account_id: str, version: int) -> dict:
    r = row(conn.execute("SELECT * FROM policy_versions WHERE account_id=? AND version=?",
                         (account_id, version)).fetchone())
    if r is None:
        raise NotFound(f"policy version {version}")
    r["policy"] = loads(r.pop("policy_json"))
    return r


def save_policy(conn: sqlite3.Connection, account_id: str, policy: Policy, *, source: str, reason: str,
                actor: str, parent: int | None) -> int:
    with tx(conn):
        nxt = conn.execute("SELECT COALESCE(MAX(version),0)+1 v FROM policy_versions WHERE account_id=?",
                           (account_id,)).fetchone()["v"]
        conn.execute("UPDATE policy_versions SET is_active=0 WHERE account_id=? AND is_active=1", (account_id,))
        conn.execute(
            "INSERT INTO policy_versions(account_id, version, parent_version, policy_json, source, reason, is_active,"
            " created_at, created_by) VALUES (?,?,?,?,?,?,1,?,?)",
            (account_id, nxt, parent, policy.model_dump_json(), source, reason, now_iso(), actor),
        )
        audit(conn, account_id, actor, f"policy.{source}", f"v{nxt}", {"parent": parent, "reason": reason})
        emit(conn, account_id, "policy.updated", f"運用方針 v{nxt} を有効化（{reason}）",
             payload={"version": nxt, "source": source, "parent": parent})
    return nxt


# ------------------------------------------------------------------ events / audit / runtime

def emit(conn: sqlite3.Connection, account_id: str, event_type: str, message: str, *, severity: str = "info",
         job_id: int | None = None, post_id: int | None = None, payload: dict | None = None,
         event_id: str | None = None, occurred_at: str | None = None, source_system: str = SOURCE_SYSTEM) -> str:
    eid = event_id or str(uuid.uuid4())
    ts = now_iso()
    conn.execute(
        "INSERT OR IGNORE INTO events(event_id, account_id, source_system, event_type, severity, occurred_at,"
        " received_at, job_id, post_id, message, payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (eid, account_id, source_system, event_type, severity, occurred_at or ts, ts, job_id, post_id, message,
         dumps(payload or {})),
    )
    return eid


def audit(conn: sqlite3.Connection, account_id: str | None, actor: str, action: str, target: str | None,
          detail: dict | None = None) -> None:
    conn.execute(
        "INSERT INTO audit_log(account_id, actor, action, target, detail_json, created_at) VALUES (?,?,?,?,?,?)",
        (account_id, actor, action, target, dumps(detail or {}), now_iso()),
    )


def set_state(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        "INSERT INTO runtime_state(key, value_json, updated_at) VALUES (?,?,?)"
        " ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
        (key, dumps(value), now_iso()),
    )


def get_state(conn: sqlite3.Connection, key: str) -> dict | None:
    r = conn.execute("SELECT value_json, updated_at FROM runtime_state WHERE key=?", (key,)).fetchone()
    if r is None:
        return None
    return {"value": loads(r["value_json"]), "updated_at": r["updated_at"]}


def consume_flag(conn: sqlite3.Connection, name: str) -> str | None:
    """Demo/test failure injection shared across processes via the DB. Returns name if it was set."""
    with tx(conn):
        cur = conn.execute("DELETE FROM runtime_state WHERE key=?", (f"flag:{name}",))
    return name if cur.rowcount else None
