import "server-only";
import { NextResponse, type NextRequest } from "next/server";

/** CSRF defence for state-changing requests: same-origin Origin header + custom header (cannot be sent cross-site without CORS). */
export function checkSameOrigin(req: NextRequest): NextResponse | null {
  const origin = req.headers.get("origin");
  const host = req.headers.get("x-forwarded-host") ?? req.headers.get("host");
  if (!origin || !host) return jsonError(403, "forbidden", "不正なリクエストです");
  try {
    if (new URL(origin).host !== host) return jsonError(403, "forbidden", "不正なリクエストです");
  } catch {
    return jsonError(403, "forbidden", "不正なリクエストです");
  }
  if (req.headers.get("x-cc-request") !== "1") return jsonError(403, "forbidden", "不正なリクエストです");
  return null;
}

export function jsonError(status: number, code: string, message: string): NextResponse {
  return NextResponse.json({ error: { code, message } }, { status, headers: { "cache-control": "no-store" } });
}

// very small in-memory login throttle (per IP+user). Resets on restart; adequate for a single-admin console.
const attempts = new Map<string, { n: number; until: number }>();
export function throttle(key: string): boolean {
  const now = Date.now();
  const a = attempts.get(key);
  if (a && a.until > now && a.n >= 5) return false;
  return true;
}
export function recordFailure(key: string): void {
  const now = Date.now();
  const a = attempts.get(key);
  if (!a || a.until < now) attempts.set(key, { n: 1, until: now + 15 * 60 * 1000 });
  else a.n += 1;
}
export function clearFailures(key: string): void {
  attempts.delete(key);
}
