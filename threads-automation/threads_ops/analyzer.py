"""Automatic improvement loop.

Metric: engagement rate (ER) = (likes + replies + reposts + quotes) / views at the primary observation bucket.
Only posts with an 'ok' metric row and views > 0 are used. Failed/unavailable metrics are excluded (never zero).

One experiment at a time, one variable at a time. Treatment posts get the candidate value, control posts the
current best value. Decisions use a Welch t statistic and a minimum lift; otherwise the result is
'inconclusive'. Adoption shifts policy weights by at most max_weight_step and is validated against settings.
A newly adopted version is watched; if ER drops beyond the threshold, it is rolled back automatically.
"""

from __future__ import annotations

import json
import math
import statistics
from datetime import timedelta

from .context import Ctx
from .db import dumps, row, rows, tx
from .generator import derive_ideas, local_slot
from .llm import AIUnavailable, parse_json
from .settings import (
    VARIABLES,
    AccountSettingsModel,
    Policy,
    PolicyViolation,
    allowed_values,
    normalize,
    reconcile_policy,
    validate_policy_change,
    weights_key,
)
from .store import (
    active_policy,
    emit,
    get_account,
    get_policy_version,
    get_settings,
    is_test_scope,
    save_policy,
)
from .timeutil import iso, now, now_iso, parse

FEATURE_COL = {"hook": "hook_style", "theme": "theme", "cta": "cta_key", "appeal": "appeal", "length": "length_target",
               "structure": "structure"}


def dataset(ctx: Ctx, account_id: str, s: AccountSettingsModel, *, days: int = 60, include_test: bool) -> list[dict]:
    since = iso(now() - timedelta(days=days))
    rs = rows(ctx.conn.execute(
        "SELECT p.*, m.views, m.likes, m.replies, m.reposts, m.quotes FROM posts p JOIN metrics m"
        " ON m.post_id=p.id AND m.bucket_hours=? AND m.status='ok'"
        " WHERE p.account_id=? AND p.status='published' AND p.is_test=? AND p.published_at>=?"
        " ORDER BY p.published_at", (s.improvement.primary_bucket_hours, account_id, int(include_test), since)).fetchall())
    out = []
    for r in rs:
        if not r["views"]:
            continue
        inter = sum((r[k] or 0) for k in ("likes", "replies", "reposts", "quotes"))
        r["er"] = inter / r["views"]
        r["post_time"] = local_slot(r)
        out.append(r)
    return out


def welch(a: list[float], b: list[float]) -> float | None:
    if len(a) < 2 or len(b) < 2:
        return None
    va, vb = statistics.variance(a), statistics.variance(b)
    se = math.sqrt(va / len(a) + vb / len(b))
    if se == 0:
        return None
    return (statistics.mean(a) - statistics.mean(b)) / se


def feature_value(r: dict, variable: str) -> str | None:
    if variable == "post_time":
        return r["post_time"]
    return r.get(FEATURE_COL.get(variable, ""))


def evaluate_experiment(ctx: Ctx, exp: dict, data: list[dict], s: AccountSettingsModel) -> dict:
    arm_rows = [r for r in data if r["experiment_id"] == exp["id"]]
    t = [r["er"] for r in arm_rows if r["experiment_arm"] == "treatment"]
    c = [r["er"] for r in arm_rows if r["experiment_arm"] == "control"]
    res = {"n_treatment": len(t), "n_control": len(c),
           "mean_treatment": statistics.mean(t) if t else None, "mean_control": statistics.mean(c) if c else None,
           "t_stat": None, "lift": None, "decision": "collecting",
           "note": "データ収集中（暫定値。効果は確定していません）"}
    n_min = s.improvement.min_samples_per_arm
    age_days = (now() - parse(exp["started_at"])).total_seconds() / 86400
    if len(t) >= n_min and len(c) >= n_min:
        ts = welch(t, c)
        lift = (res["mean_treatment"] - res["mean_control"]) / res["mean_control"] if res["mean_control"] else None
        res["t_stat"], res["lift"] = ts, lift
        if ts is not None and lift is not None and ts >= 2.0 and lift >= s.improvement.min_lift:
            res["decision"], res["note"] = "adopt", "改善の傾向あり（t≥2・上昇率が基準以上）。小さく反映し、引き続き監視します"
        elif ts is not None and ts <= -2.0:
            res["decision"], res["note"] = "reject", "悪化の傾向あり。採用しません"
    if res["decision"] == "collecting" and age_days >= s.improvement.experiment_max_days:
        res["decision"] = "inconclusive"
        res["note"] = "期間内に明確な差が出ませんでした（判定保留）"
    return res


def _shift(policy: Policy, variable: str, value: str, control: str, step: float, s: AccountSettingsModel) -> Policy:
    data = policy.model_dump()
    if variable == "post_time":
        times = [value if x == control else x for x in data["post_times"]]
        data["post_times"] = sorted(times)
        return Policy.model_validate(data)
    key = weights_key(variable)
    w = dict(data[key])
    room = min(step, 1 - w[value])
    others = [k for k in w if k != value]
    take_total = 0.0
    others_sum = max(sum(w[o] for o in others), 1e-9)
    shares = {k: w[k] / others_sum for k in others}
    for k in others:   # take proportionally, keep each option ≥ 3% (exploration floor)
        take = min(room * shares[k], max(0.0, w[k] - 0.03))
        w[k] -= take
        take_total += take
    w[value] += take_total
    data[key] = normalize(w)
    return Policy.model_validate(data)


def _candidate(data: list[dict], s: AccountSettingsModel, policy: Policy) -> list[dict]:
    """Deterministic candidate list: per variable, the best-performing non-leader (exploit) or least-sampled (explore)."""
    out = []
    for var in VARIABLES:
        if var in s.locked:
            continue
        values = allowed_values(s, var)
        if var == "post_time":
            current = policy.post_times
            spare = [v for v in values if v not in current]
            if not spare or not current:
                continue
            by_time = {v: [r["er"] for r in data if r["post_time"] == v] for v in current}
            worst = min(current, key=lambda v: statistics.mean(by_time[v]) if by_time[v] else 1e9)
            out.append({"variable": var, "control": worst, "treatment": spare[0], "reason": "空き時間帯を最弱の枠と比較"})
            continue
        weights = getattr(policy, weights_key(var))
        leader = max(weights, key=lambda k: weights[k])
        stats = {v: [r["er"] for r in data if feature_value(r, var) == v] for v in values}
        others = [v for v in values if v != leader]
        if not others:
            continue
        sampled = [v for v in others if len(stats[v]) >= 3]
        if sampled:
            best = max(sampled, key=lambda v: statistics.mean(stats[v]))
            lead_mean = statistics.mean(stats[leader]) if stats[leader] else 0
            if statistics.mean(stats[best]) > lead_mean:
                out.append({"variable": var, "control": leader, "treatment": best,
                            "reason": f"観測上 {best} が {leader} を上回る（n={len(stats[best])}）ため検証"})
                continue
        least = min(others, key=lambda v: len(stats[v]))
        out.append({"variable": var, "control": leader, "treatment": least,
                    "reason": f"サンプルの少ない {least}（n={len(stats[least])}）を検証"})
    return out


HYPOTHESIS_PROMPT = """あなたはSNS運用のアナリストです。context.candidates から次に検証する1件を選び、
JSON {"index": 候補番号, "hypothesis": "仮説（60字以内）"} だけを返してください。候補以外は選べません。"""


def analyze(ctx: Ctx, job: dict) -> dict:
    conn = ctx.conn
    account = get_account(conn, job["account_id"])
    s, _ = get_settings(conn, account["id"])
    test = is_test_scope(account)
    if not s.improvement.enabled:
        return {"skipped": "自動改善は停止中"}
    data = dataset(ctx, account["id"], s, include_test=test)
    pol = active_policy(conn, account["id"])
    policy = reconcile_policy(Policy.model_validate(pol["policy"]), s)
    out: dict = {"samples": len(data), "policy_version": pol["version"]}

    # 1) rollback watch on the latest auto-adopted version
    rb = _rollback_check(ctx, account["id"], s, pol, data)
    if rb:
        out["rollback"] = rb
        return out

    # 2) running experiment
    exp = row(conn.execute("SELECT * FROM experiments WHERE account_id=? AND status='running'", (account["id"],)).fetchone())
    if exp:
        ev = evaluate_experiment(ctx, exp, data, s)
        out["experiment"] = {"id": exp["id"], **ev}
        if ev["decision"] == "adopt":
            try:
                new = _shift(policy, exp["variable"], exp["treatment_value"], exp["control_value"],
                             s.improvement.max_weight_step, s)
                validate_policy_change(policy, new, s, max_step=s.improvement.max_weight_step)
                ver = save_policy(conn, account["id"], new, source="auto",
                                  reason=f"実験#{exp['id']} {exp['variable']}={exp['treatment_value']} を小さく反映",
                                  actor="system:analyzer", parent=pol["version"])
                _end(ctx, exp, "adopted", ev, ver)
            except PolicyViolation as e:
                ev["note"] = f"許可範囲外の変更のため反映しません: {e}"
                _end(ctx, exp, "rejected", ev, None)
        elif ev["decision"] in ("reject", "inconclusive"):
            _end(ctx, exp, "rejected" if ev["decision"] == "reject" else "inconclusive", ev, None)
        else:
            with tx(conn):
                conn.execute("UPDATE experiments SET result_json=? WHERE id=?", (dumps(ev), exp["id"]))
        if ev["decision"] == "collecting":
            _derive(ctx, account["id"], s, data, test, job, out)
            return out

    # 3) start a new experiment (allocation change only — policy itself unchanged)
    cands = _candidate(data, s, policy)
    if cands:
        pick, hyp = 0, cands[0]["reason"]
        try:
            res = ctx.llm.complete(account["id"], s, "propose_hypothesis", HYPOTHESIS_PROMPT,
                                   "<context>" + json.dumps({"candidates": [dict(c, index=i) for i, c in enumerate(cands)],
                                                             "samples": len(data)}, ensure_ascii=False) + "</context>",
                                   job_id=job["id"])
            v = parse_json(res.text)
            idx = v.get("index")
            if isinstance(idx, int) and 0 <= idx < len(cands):   # AI may only choose from validated candidates
                pick = idx
                hyp = str(v.get("hypothesis") or cands[idx]["reason"])[:120]
        except (AIUnavailable, ValueError, json.JSONDecodeError):
            hyp = cands[0]["reason"]
        c = cands[pick]
        if c["control"] != c["treatment"]:
            with tx(conn):
                cur = conn.execute(
                    "INSERT INTO experiments(account_id, variable, hypothesis, control_value, treatment_value,"
                    " base_policy_version, status, started_at) VALUES (?,?,?,?,?,?, 'running', ?)",
                    (account["id"], c["variable"], hyp, c["control"], c["treatment"], pol["version"], now_iso()))
                emit(conn, account["id"], "experiment.started",
                     f"改善実験を開始: {c['variable']} {c['control']} → {c['treatment']}（{hyp}）",
                     payload={"experiment_id": cur.lastrowid, **c})
            out["started_experiment"] = c
    _derive(ctx, account["id"], s, data, test, job, out)
    return out


def _end(ctx: Ctx, exp: dict, status: str, ev: dict, ver: int | None) -> None:
    with tx(ctx.conn):
        ctx.conn.execute("UPDATE experiments SET status=?, result_json=?, ended_at=?, adopted_policy_version=? WHERE id=?",
                         (status, dumps(ev), now_iso(), ver, exp["id"]))
        label = {"adopted": "採用", "rejected": "不採用", "inconclusive": "判定保留", "stopped": "停止"}[status]
        emit(ctx.conn, exp["account_id"], "experiment.ended", f"改善実験#{exp['id']}を終了（{label}）: {ev.get('note', '')}",
             severity="success" if status == "adopted" else "info", payload={"experiment_id": exp["id"], "status": status})


def _rollback_check(ctx: Ctx, account_id: str, s: AccountSettingsModel, pol: dict, data: list[dict]) -> dict | None:
    if pol["source"] != "auto" or pol["parent_version"] is None:
        return None
    n = s.improvement.rollback_window_posts
    after = [r["er"] for r in data if r["policy_version"] == pol["version"] and r["experiment_arm"] is None][-n:]
    before = [r["er"] for r in data if r["policy_version"] == pol["parent_version"] and r["experiment_arm"] is None][-n:]
    if len(after) < n or len(before) < n:
        return None
    ma, mb = statistics.mean(after), statistics.mean(before)
    if mb > 0 and (mb - ma) / mb >= s.improvement.rollback_drop_threshold:
        parent = get_policy_version(ctx.conn, account_id, pol["parent_version"])
        restored = reconcile_policy(Policy.model_validate(parent["policy"]), s)
        ver = save_policy(ctx.conn, account_id, restored, source="rollback",
                          reason=f"v{pol['version']}適用後に反応率が{(mb - ma) / mb:.0%}低下したため自動差し戻し",
                          actor="system:analyzer", parent=pol["version"])
        return {"from": pol["version"], "to_parent": pol["parent_version"], "new_version": ver,
                "mean_before": mb, "mean_after": ma}
    return None


def _derive(ctx: Ctx, account_id: str, s: AccountSettingsModel, data: list[dict], test: bool, job: dict, out: dict) -> None:
    if not s.ideas.derive_top_performers or len(data) < 5:
        return
    recent = [r for r in data if parse(r["published_at"]) >= now() - timedelta(days=14)]
    if len(recent) < 5:
        return
    med = statistics.median(r["er"] for r in recent)
    top = max(recent, key=lambda r: r["er"])
    if top["er"] <= med or not top.get("idea_id"):
        return
    already = ctx.conn.execute("SELECT 1 FROM ideas WHERE source_post_id=? LIMIT 1", (top["id"],)).fetchone()
    if already:
        return
    try:
        out["derived_ideas"] = derive_ideas(ctx, account_id, s, top, test, job["id"])
    except (AIUnavailable, ValueError, json.JSONDecodeError) as e:
        out["derived_ideas_error"] = str(e)


def manual_rollback(ctx: Ctx, account_id: str, version: int, actor: str) -> int:
    s, _ = get_settings(ctx.conn, account_id)
    target = get_policy_version(ctx.conn, account_id, version)
    cur = active_policy(ctx.conn, account_id)
    if target["version"] == cur["version"]:
        from .store import Conflict
        raise Conflict("すでに有効な版です")
    restored = reconcile_policy(Policy.model_validate(target["policy"]), s)
    validate_policy_change(Policy.model_validate(cur["policy"]), restored, s.model_copy(update={"locked": []}),
                           max_step=None)
    return save_policy(ctx.conn, account_id, restored, source="rollback", reason=f"手動でv{version}へ差し戻し",
                       actor=actor, parent=cur["version"])


def stop_experiment(ctx: Ctx, account_id: str, actor: str) -> dict:
    from .store import Conflict, audit
    exp = row(ctx.conn.execute("SELECT * FROM experiments WHERE account_id=? AND status='running'", (account_id,)).fetchone())
    if not exp:
        raise Conflict("実行中の実験はありません")
    _end(ctx, exp, "stopped", {"note": "ユーザー操作で停止"}, None)
    with tx(ctx.conn):
        audit(ctx.conn, account_id, actor, "experiment.stop", f"experiment:{exp['id']}", {})
    return {"stopped": exp["id"]}
