"""LLM access with budget guard.

Providers:
  openai : OpenAI Responses API via httpx (key from OPENAI_API_KEY, never logged)
  mock   : deterministic local generator for demo/tests (no network, cost 0)
  none   : AI unavailable

Every call reserves budget first inside an IMMEDIATE transaction, so concurrent workers cannot
overshoot the daily/monthly limit; the reservation is replaced by the measured cost afterwards.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import re
import sqlite3
from dataclasses import dataclass
from datetime import timedelta

import httpx

from .config import Config
from .db import tx
from .settings import AccountSettingsModel
from .timeutil import JST, now, now_iso

log = logging.getLogger(__name__)


class AIUnavailable(Exception):
    """AI cannot be used (not configured / budget not set / budget exhausted / provider down)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class LLMResult:
    text: str
    input_tokens: int | None
    output_tokens: int | None
    model: str
    usage_id: int | None


# ------------------------------------------------------------------ budget

def spent(conn: sqlite3.Connection, account_id: str) -> dict:
    t = now().astimezone(JST)
    day_start = t.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = day_start.replace(day=1)

    def total(since) -> float:
        r = conn.execute(
            "SELECT COALESCE(SUM(CASE WHEN status='reserved' THEN reserved_usd ELSE COALESCE(cost_usd, reserved_usd) END),0) s"
            " FROM ai_usage WHERE account_id=? AND created_at>=? AND status IN ('reserved','committed','failed')",
            (account_id, since.astimezone(now().tzinfo).strftime("%Y-%m-%dT%H:%M:%S.%fZ")),
        ).fetchone()
        return float(r["s"])

    return {"today_usd": round(total(day_start), 6), "month_usd": round(total(month_start), 6)}


def _estimate_cost(s: AccountSettingsModel, input_chars: int, max_output: int) -> float | None:
    b = s.budget
    if b.price_input_per_mtok_usd is None or b.price_output_per_mtok_usd is None:
        return None
    est_in_tokens = int(input_chars * 1.2) + 50   # Japanese ≈ ≤1.2 tokens/char; conservative
    # reasoning tokens are billed as output: budget the whole max_output allowance
    return (est_in_tokens * b.price_input_per_mtok_usd + max_output * b.price_output_per_mtok_usd) / 1_000_000


def _reserve(conn: sqlite3.Connection, account_id: str, s: AccountSettingsModel, cfg: Config, purpose: str,
             input_chars: int, job_id: int | None, provider: str, model: str) -> tuple[int, float]:
    if provider == "mock":
        with tx(conn):
            cur = conn.execute(
                "INSERT INTO ai_usage(account_id, purpose, provider, model, status, reserved_usd, cost_kind, job_id,"
                " created_at, updated_at) VALUES (?,?,?,?, 'reserved', 0, 'none', ?, ?, ?)",
                (account_id, purpose, provider, model, job_id, now_iso(), now_iso()))
        return int(cur.lastrowid), 0.0
    b = s.budget
    if b.daily_usd is None or b.monthly_usd is None:
        raise AIUnavailable("budget_not_set", "AI予算（日次・月次）が未設定のため、AI処理を停止しています")
    est = _estimate_cost(s, input_chars, b.max_output_tokens)
    if est is None:
        raise AIUnavailable("price_not_set", "モデル単価が未設定のため費用を見積もれず、AI処理を停止しています")
    with tx(conn):
        sp = spent(conn, account_id)
        if sp["today_usd"] + est > b.daily_usd:
            raise AIUnavailable("budget_daily", f"日次予算に到達（使用 {sp['today_usd']:.4f} / 上限 {b.daily_usd} USD）")
        if sp["month_usd"] + est > b.monthly_usd:
            raise AIUnavailable("budget_monthly", f"月次予算に到達（使用 {sp['month_usd']:.4f} / 上限 {b.monthly_usd} USD）")
        cur = conn.execute(
            "INSERT INTO ai_usage(account_id, purpose, provider, model, status, reserved_usd, cost_kind, job_id,"
            " created_at, updated_at) VALUES (?,?,?,?, 'reserved', ?, 'estimated', ?, ?, ?)",
            (account_id, purpose, provider, model, est, job_id, now_iso(), now_iso()))
    return int(cur.lastrowid), est


def _settle(conn: sqlite3.Connection, usage_id: int, s: AccountSettingsModel, *, ok: bool, in_tok: int | None,
            out_tok: int | None, error: str | None, maybe_billed: bool) -> None:
    b = s.budget
    cost: float | None
    kind: str
    if in_tok is not None and out_tok is not None and b.price_input_per_mtok_usd is not None \
            and b.price_output_per_mtok_usd is not None:
        cost = (in_tok * b.price_input_per_mtok_usd + out_tok * b.price_output_per_mtok_usd) / 1_000_000
        kind = "measured_tokens_estimated_price"
    elif maybe_billed:
        cost, kind = None, "estimated"     # keep reserved amount as conservative estimate
    else:
        cost, kind = 0.0, "none"
    with tx(conn):
        r = conn.execute("SELECT provider FROM ai_usage WHERE id=?", (usage_id,)).fetchone()
        if r and r["provider"] == "mock":
            cost, kind = 0.0, "none"
        status = "committed" if ok else ("failed" if maybe_billed else "released")
        conn.execute(
            "UPDATE ai_usage SET status=?, cost_usd=?, cost_kind=?, input_tokens=?, output_tokens=?, error=?, updated_at=?"
            " WHERE id=?", (status, cost, kind, in_tok, out_tok, (error or "")[:500] or None, now_iso(), usage_id))


# ------------------------------------------------------------------ providers

class LLM:
    def __init__(self, cfg: Config, conn: sqlite3.Connection, transport: httpx.BaseTransport | None = None):
        self.cfg = cfg
        self.conn = conn
        self.transport = transport
        self._dropped_params: set[str] = set()

    @property
    def provider(self) -> str:
        return self.cfg.llm_provider

    def availability(self) -> dict:
        if self.provider == "mock":
            return {"available": True, "provider": "mock", "model": "mock-local", "reason": None}
        if self.provider == "openai":
            if not self.cfg.openai_key_present():
                return {"available": False, "provider": "openai", "model": self.cfg.openai_model,
                        "reason": "OPENAI_API_KEY が未設定です"}
            return {"available": True, "provider": "openai", "model": self.cfg.openai_model, "reason": None}
        return {"available": False, "provider": self.provider, "model": None, "reason": "LLM_PROVIDER が none です"}

    def complete(self, account_id: str, s: AccountSettingsModel, purpose: str, system: str, user: str,
                 *, job_id: int | None = None, json_mode: bool = True) -> LLMResult:
        av = self.availability()
        if not av["available"]:
            raise AIUnavailable("not_configured", av["reason"])
        model = av["model"]
        usage_id, _ = _reserve(self.conn, account_id, s, self.cfg, purpose, len(system) + len(user), job_id,
                               self.provider, model)
        try:
            if self.provider == "mock":
                text = mock_response(purpose, system, user)
                in_tok, out_tok = len(system + user) // 2, len(text) // 2
            else:
                text, in_tok, out_tok = self._openai(system, user, s.budget.max_output_tokens, json_mode)
        except _ProviderError as e:
            _settle(self.conn, usage_id, s, ok=False, in_tok=None, out_tok=None, error=str(e),
                    maybe_billed=e.maybe_billed)
            raise AIUnavailable("provider_error", str(e)) from e
        _settle(self.conn, usage_id, s, ok=True, in_tok=in_tok, out_tok=out_tok, error=None, maybe_billed=True)
        return LLMResult(text=text, input_tokens=in_tok, output_tokens=out_tok, model=model, usage_id=usage_id)

    # OpenAI Responses API -------------------------------------------------------
    def _openai(self, system: str, user: str, max_output: int, json_mode: bool) -> tuple[str, int | None, int | None]:
        key = os.environ.get("OPENAI_API_KEY", "")
        body: dict = {
            "model": self.cfg.openai_model,
            "instructions": system,
            "input": user,
            "max_output_tokens": max_output,
            "store": False,
        }
        if self.cfg.openai_reasoning_effort and "reasoning" not in self._dropped_params:
            body["reasoning"] = {"effort": self.cfg.openai_reasoning_effort}
        if json_mode and "text" not in self._dropped_params:
            body["text"] = {"format": {"type": "json_object"}}
        client = httpx.Client(timeout=self.cfg.openai_timeout_s, transport=self.transport)
        try:
            for _ in range(3):  # only to drop unsupported optional params; never for transport errors
                try:
                    resp = client.post(f"{self.cfg.openai_base_url}/responses", json=body,
                                       headers={"Authorization": f"Bearer {key}"})
                except httpx.TimeoutException as e:
                    raise _ProviderError("OpenAI応答タイムアウト（課金された可能性あり）", maybe_billed=True) from e
                except httpx.HTTPError as e:
                    raise _ProviderError(f"OpenAI接続エラー: {type(e).__name__}", maybe_billed=False) from e
                if resp.status_code == 400:
                    param = _unsupported_param(resp)
                    if param in ("reasoning", "text") and param in body:
                        self._dropped_params.add(param)
                        body.pop(param)
                        log.warning("OpenAI rejected optional param %s; retrying without it", param)
                        continue
                if resp.status_code >= 400:
                    raise _ProviderError(_openai_error(resp), maybe_billed=False)
                data = resp.json()
                return _extract_output(data), _usage(data, "input_tokens"), _usage(data, "output_tokens")
            raise _ProviderError("OpenAIパラメーター互換性エラー", maybe_billed=False)
        finally:
            client.close()


class _ProviderError(Exception):
    def __init__(self, msg: str, maybe_billed: bool):
        super().__init__(msg)
        self.maybe_billed = maybe_billed


def _unsupported_param(resp: httpx.Response) -> str | None:
    try:
        err = resp.json().get("error", {})
    except ValueError:
        return None
    param = (err.get("param") or "").split(".")[0]
    msg = (err.get("message") or "").lower()
    if param:
        return param
    for p in ("reasoning", "text"):
        if p in msg and ("unsupported" in msg or "not supported" in msg):
            return p
    return None


def _openai_error(resp: httpx.Response) -> str:
    code = resp.status_code
    try:
        err = resp.json().get("error", {})
        kind = err.get("code") or err.get("type") or ""
    except ValueError:
        kind = ""
    hint = {401: "APIキーが無効です", 403: "権限がありません", 404: "モデルが見つかりません", 429: "利用上限またはクレジット不足"}
    return f"OpenAI HTTP {code} {kind} {hint.get(code, '')}".strip()


def _extract_output(data: dict) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    parts = []
    for item in data.get("output", []) or []:
        for c in item.get("content", []) or []:
            if c.get("type") in ("output_text", "text") and isinstance(c.get("text"), str):
                parts.append(c["text"])
    return "".join(parts)


def _usage(data: dict, key: str) -> int | None:
    u = data.get("usage") or {}
    v = u.get(key)
    return int(v) if isinstance(v, int | float) else None


def parse_json(text: str) -> dict:
    t = text.strip()
    m = re.search(r"\{.*\}", t, re.DOTALL)
    if not m:
        raise ValueError("no JSON object in model output")
    v = json.loads(m.group(0))
    if not isinstance(v, dict):
        raise ValueError("model output is not an object")
    return v


# ------------------------------------------------------------------ mock (demo/test only)

_MOCK_OPENERS = {
    "問いかけ": "{theme}、何から手をつければいいか迷っていませんか？",
    "共感": "{theme}って、最初は本当に不安ですよね。",
    "結論先出し": "結論：{theme}は「小さく試す」が一番の近道です。",
    "意外な事実": "{theme}で大事なのは、才能より段取りだったりします。",
    "手順": "{theme}を進めるための手順を3つにまとめました。",
}


def mock_response(purpose: str, system: str, user: str) -> str:
    seed = int(hashlib.sha256((purpose + user).encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    ctx = _ctx(user)
    if purpose == "generate_post":
        theme = ctx.get("theme", "副業")
        opener = _MOCK_OPENERS.get(ctx.get("hook", ""), "{theme}について。").format(theme=theme)
        idea = ctx.get("idea") or {}
        pool = [
            "まずは1日15分だけ時間を確保する", "完璧を目指さず、試して直す", "記録をつけて振り返る",
            "できたことを小さく言葉にする", "一人で抱え込まず相談する", "やらないことを先に決める",
            "週に一度、予定を見直す", "気になったことはメモに残す", "比べる相手は昨日の自分にする",
            "疲れた日は休むと決めておく", "目標は数字より行動で決める", "迷ったら小さいほうを選ぶ",
            "朝のうちに一つだけ進める", "終わったらチェックを付ける", "学んだことを一行で書き出す",
        ]
        bullets = rng.sample(pool, 3)
        body = "\n".join(f"・{b}" for b in bullets)
        closing = rng.choice(["焦らず、自分のペースで続けるのが大切です。", "小さな積み重ねが、あとで効いてきます。",
                              "うまくいかない日があっても大丈夫。", "今日できる一つから始めてみてください。",
                              "続けた分だけ、選べることが増えていきます。"])
        about = f"「{idea.get('pain')}」という声をよく聞きます。" if idea.get("pain") else ""
        cta = ctx.get("cta_text", "")
        tail = f"\n\n{cta}" if cta and cta != "（CTAなし）" else ""
        text = f"{opener}\n{about}\n\n{body}\n\n{closing}{tail}"
        return json.dumps({"text": text}, ensure_ascii=False)
    if purpose == "review_post":
        return json.dumps({"ok": True, "issues": []}, ensure_ascii=False)
    if purpose == "refill_ideas":
        themes = ctx.get("themes") or ["副業の始め方"]
        n = int(ctx.get("count", 3))
        ideas = [{"theme": themes[i % len(themes)], "pain": rng.choice(["時間がない", "何を選べばいいか分からない", "続かない"]),
                  "appeal": rng.choice(["小さな一歩", "不安の解消"]), "angle": f"切り口{rng.randint(1, 99)}"} for i in range(n)]
        return json.dumps({"ideas": ideas}, ensure_ascii=False)
    if purpose == "derive_ideas":
        base = ctx.get("base", {})
        return json.dumps({"ideas": [{**base, "angle": f"{base.get('angle', '')}の別視点{rng.randint(1, 9)}"}]},
                          ensure_ascii=False)
    if purpose in ("summarize_report", "assistant_summary"):
        return json.dumps({"summary": "集計結果をもとにした要約（デモ用のローカル生成）です。数値は上の集計表を参照してください。"},
                          ensure_ascii=False)
    if purpose in ("propose_hypothesis", "assistant_improvement"):
        return json.dumps({"variable": ctx.get("suggest_variable", "hook"), "value": ctx.get("suggest_value", ""),
                           "hypothesis": "サンプルの少ない候補を試して比較する（デモ）",
                           "suggestions": ["書き出しの型をひとつ固定して比較する"]}, ensure_ascii=False)
    return json.dumps({"text": "ok"}, ensure_ascii=False)


def _ctx(user: str) -> dict:
    m = re.search(r"<context>(.*?)</context>", user, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except ValueError:
        return {}


def usage_summary(conn: sqlite3.Connection, account_id: str, s: AccountSettingsModel) -> dict:
    sp = spent(conn, account_id)
    by_purpose = [dict(r) for r in conn.execute(
        "SELECT purpose, COUNT(*) calls, SUM(COALESCE(cost_usd, reserved_usd)) usd,"
        " SUM(COALESCE(input_tokens,0)) input_tokens, SUM(COALESCE(output_tokens,0)) output_tokens,"
        " SUM(CASE WHEN cost_kind='estimated' THEN 1 ELSE 0 END) estimated_calls"
        " FROM ai_usage WHERE account_id=? AND created_at>=? GROUP BY purpose ORDER BY usd DESC",
        (account_id, (now() - timedelta(days=31)).strftime("%Y-%m-%dT%H:%M:%S.%fZ"))).fetchall()]
    return {
        **sp,
        "daily_limit_usd": s.budget.daily_usd,
        "monthly_limit_usd": s.budget.monthly_usd,
        "budget_configured": s.budget.daily_usd is not None and s.budget.monthly_usd is not None,
        "price_configured": s.budget.price_input_per_mtok_usd is not None and s.budget.price_output_per_mtok_usd is not None,
        "cost_basis": "トークン数は実測、単価は設定値による推定。課金の確定値はOpenAIの請求画面で確認してください。",
        "by_purpose_31d": by_purpose,
    }
