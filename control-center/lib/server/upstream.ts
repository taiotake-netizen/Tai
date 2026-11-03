import "server-only";
import { allowedUpstreamHosts, demoUpstream, liveUpstream, type Upstream } from "./config";
import type { Session } from "./session";

export type UpstreamResult = { status: number; body: unknown };

const READ_TIMEOUT_MS = 8000;
const WRITE_TIMEOUT_MS = 20000;

export function upstreamFor(session: Session): Upstream | null {
  return session.m === "demo" ? demoUpstream() : liveUpstream();
}

function hostAllowed(u: Upstream): boolean {
  try {
    return allowedUpstreamHosts().includes(new URL(u.url).hostname);
  } catch {
    return false;
  }
}

/**
 * Calls the Threads engine. Reads are retried with backoff; writes are NOT retried automatically
 * (the engine is the source of truth — the UI re-reads state instead).
 */
export async function callUpstream(
  session: Session,
  method: string,
  path: string,
  body?: string,
): Promise<UpstreamResult> {
  const up = upstreamFor(session);
  if (!up) {
    return { status: 503, body: { error: { code: "not_configured", message: session.m === "demo"
      ? "デモ用エンジンの接続先（DEMO_THREADS_OPS_URL）が未設定です"
      : "Threads運用エンジンの接続先（THREADS_OPS_URL）が未設定です" } } };
  }
  if (!hostAllowed(up)) {
    return { status: 503, body: { error: { code: "host_not_allowed", message: "許可されていない接続先です" } } };
  }
  const write = method !== "GET";
  const attempts = write ? 1 : 3;
  let lastErr = "";
  for (let i = 0; i < attempts; i++) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), write ? WRITE_TIMEOUT_MS : READ_TIMEOUT_MS);
    try {
      const res = await fetch(`${up.url}${path}`, {
        method,
        body,
        cache: "no-store",
        signal: ctrl.signal,
        headers: {
          "content-type": "application/json",
          ...(up.token ? { authorization: `Bearer ${up.token}` } : {}),
          "x-account-scope": session.a.join(","),
          "x-actor": `${session.m}:${session.u}`,
        },
      });
      const text = await res.text();
      let parsed: unknown = null;
      try {
        parsed = text ? JSON.parse(text) : null;
      } catch {
        parsed = { error: { code: "bad_upstream_response", message: "エンジンの応答を解釈できません" } };
      }
      if (!write && res.status >= 500 && i < attempts - 1) {
        lastErr = `HTTP ${res.status}`;
        await new Promise((r) => setTimeout(r, 300 * 2 ** i));
        continue;
      }
      return { status: res.status, body: parsed };
    } catch (e) {
      lastErr = e instanceof Error ? e.name : "error";
      if (write) {
        return { status: 504, body: { error: { code: "write_outcome_unknown",
          message: "エンジンからの応答がありません。操作が反映されたか、画面を更新して確認してください" } } };
      }
      if (i < attempts - 1) await new Promise((r) => setTimeout(r, 300 * 2 ** i));
    } finally {
      clearTimeout(timer);
    }
  }
  return { status: 503, body: { error: { code: "upstream_unreachable", message: `Threads運用エンジンに接続できません（${lastErr}）` } } };
}
