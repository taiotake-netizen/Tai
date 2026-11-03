"""Threads Graph API client + dry-run simulator.

Endpoints used (Threads API, https://graph.threads.net/v1.0). Verify against the official docs before go-live:
  POST /{user_id}/threads            media_type=TEXT, text        -> {id: creation_id}
  POST /{user_id}/threads_publish    creation_id                  -> {id: media_id}
  GET  /{media_id}?fields=id,permalink,timestamp
  GET  /{media_id}/insights?metric=views,likes,replies,reposts,quotes,shares
  GET  /{user_id}/threads?fields=id,text,timestamp,permalink&limit=25   (reconciliation of unknown results)
  GET  /{user_id}/threads_publishing_limit?fields=quota_usage,config
  GET  /me?fields=id,username                                       (connection check)

Access token comes from the env var named in accounts.token_env. It is sent only to graph.threads.net.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from .config import Config

METRICS = ("views", "likes", "replies", "reposts", "quotes", "shares")


class ThreadsError(Exception):
    def __init__(self, message: str, *, outcome_unknown: bool = False, auth: bool = False, rate_limited: bool = False):
        super().__init__(message)
        self.outcome_unknown = outcome_unknown
        self.auth = auth
        self.rate_limited = rate_limited


@dataclass
class PublishResult:
    container_id: str
    post_id: str
    permalink: str | None


class ThreadsClient:
    def __init__(self, cfg: Config, account: dict, transport: httpx.BaseTransport | None = None):
        self.cfg = cfg
        self.account = account
        self.transport = transport
        host = urlparse(cfg.threads_api_base).hostname or ""
        if host not in cfg.allowed_hosts:
            raise ThreadsError(f"許可されていない接続先です: {host}")

    @property
    def configured(self) -> bool:
        return bool(self.account.get("external_user_id") and self.account.get("token_env")
                    and os.environ.get(self.account["token_env"]))

    def _token(self) -> str:
        if not self.configured:
            raise ThreadsError("ThreadsのユーザーIDまたはアクセストークンが未設定です", auth=True)
        return os.environ[self.account["token_env"]]

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=self.cfg.threads_api_base, timeout=30, transport=self.transport)

    def _check(self, resp: httpx.Response, *, write: bool) -> dict:
        if resp.status_code >= 400:
            try:
                err = resp.json().get("error", {})
            except ValueError:
                err = {}
            code = err.get("code")
            msg = f"Threads API HTTP {resp.status_code} code={code} {err.get('type', '')}".strip()
            raise ThreadsError(msg, auth=code in (190, 102) or resp.status_code == 401,
                               rate_limited=resp.status_code == 429 or code in (4, 17, 32, 613),
                               outcome_unknown=write and resp.status_code >= 500)
        return resp.json()

    # ---- read
    def me(self) -> dict:
        with self._client() as c:
            return self._check(c.get("/me", params={"fields": "id,username", "access_token": self._token()}), write=False)

    def publishing_quota(self) -> dict:
        with self._client() as c:
            return self._check(c.get(f"/{self.account['external_user_id']}/threads_publishing_limit",
                                     params={"fields": "quota_usage,config", "access_token": self._token()}),
                               write=False)

    def recent_posts(self, limit: int = 25) -> list[dict]:
        with self._client() as c:
            data = self._check(c.get(f"/{self.account['external_user_id']}/threads",
                                     params={"fields": "id,text,timestamp,permalink", "limit": limit,
                                             "access_token": self._token()}), write=False)
        return data.get("data", [])

    def insights(self, media_id: str) -> dict[str, int | None]:
        with self._client() as c:
            data = self._check(c.get(f"/{media_id}/insights",
                                     params={"metric": ",".join(METRICS), "access_token": self._token()}),
                               write=False)
        out: dict[str, int | None] = {m: None for m in METRICS}
        for item in data.get("data", []):
            name = item.get("name")
            if name not in out:
                continue
            val = None
            if item.get("values"):
                val = item["values"][0].get("value")
            elif isinstance(item.get("total_value"), dict):
                val = item["total_value"].get("value")
            out[name] = int(val) if isinstance(val, int | float) else None
        return out

    # ---- write (never auto-retried)
    def create_container(self, text: str) -> str:
        try:
            with self._client() as c:
                data = self._check(c.post(f"/{self.account['external_user_id']}/threads",
                                          data={"media_type": "TEXT", "text": text, "access_token": self._token()}),
                                   write=True)
        except httpx.HTTPError as e:
            # container creation has no public side effect; safe to treat as failure
            raise ThreadsError(f"コンテナ作成で通信エラー: {type(e).__name__}") from e
        return str(data["id"])

    def publish_container(self, container_id: str) -> str:
        try:
            with self._client() as c:
                data = self._check(c.post(f"/{self.account['external_user_id']}/threads_publish",
                                          data={"creation_id": container_id, "access_token": self._token()}),
                                   write=True)
        except httpx.TimeoutException as e:
            raise ThreadsError("公開リクエストがタイムアウト（公開された可能性あり）", outcome_unknown=True) from e
        except httpx.HTTPError as e:
            raise ThreadsError(f"公開リクエストで通信エラー: {type(e).__name__}", outcome_unknown=True) from e
        return str(data["id"])

    def permalink(self, media_id: str) -> str | None:
        try:
            with self._client() as c:
                data = self._check(c.get(f"/{media_id}", params={"fields": "id,permalink",
                                                                 "access_token": self._token()}), write=False)
            return data.get("permalink")
        except (ThreadsError, httpx.HTTPError):
            return None


class DryRunPublisher:
    """Simulates publishing without any network call. Used for demo/test and PUBLISH_MODE=dry_run."""

    def publish(self, text: str, fail: str | None = None) -> PublishResult:
        """fail: injected failure for demo/test scenarios ("publish_error" | "publish_unknown")."""
        if fail == "publish_error":
            raise ThreadsError("（テスト）公開APIがエラーを返しました")
        if fail == "publish_unknown":
            raise ThreadsError("（テスト）公開結果が不明です", outcome_unknown=True)
        pid = f"dryrun-{uuid.uuid4().hex[:12]}"
        return PublishResult(container_id=f"dryrun-c-{uuid.uuid4().hex[:8]}", post_id=pid, permalink=None)

    def insights(self, post: dict, bucket_hours: int, fail: str | None = None) -> dict[str, int | None]:
        if fail == "metrics_error":
            raise ThreadsError("（テスト）実績取得に失敗しました")
        return synthetic_metrics(post, bucket_hours)


# Synthetic metrics exist ONLY for dry-run/test posts so the full loop can be exercised.
# They are deterministic and favour a few options so the improvement loop has something to find.
_BIAS = {"結論先出し": 1.35, "問いかけ": 1.15, "手順": 1.1, "save": 1.2, "short": 1.1, "21:00": 1.15}


def synthetic_metrics(post: dict, bucket_hours: int) -> dict[str, int | None]:
    seed = int(hashlib.sha256(f"{post['id']}:{post.get('text', '')}".encode()).hexdigest()[:8], 16)
    noise = 0.75 + (seed % 1000) / 2000
    mult = 1.0
    for k in (post.get("hook_style"), post.get("cta_key"), post.get("length_target"), (post.get("slot_local") or "")):
        mult *= _BIAS.get(k or "", 1.0)
    views = int(400 * (1 + bucket_hours / 48) * noise)
    rate = 0.035 * mult * (0.85 + (seed % 300) / 1000)
    likes = int(views * rate)
    return {"views": views, "likes": likes, "replies": int(likes * 0.12), "reposts": int(likes * 0.06),
            "quotes": int(likes * 0.02), "shares": None}
