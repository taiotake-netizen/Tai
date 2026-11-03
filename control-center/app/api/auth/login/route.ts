import { NextResponse, type NextRequest } from "next/server";
import { demoEnabled } from "@/lib/server/config";
import { checkSameOrigin, clearFailures, jsonError, recordFailure, throttle } from "@/lib/server/guard";
import { SESSION_COOKIE, cookieOptions, encodeSession } from "@/lib/server/session";
import { authenticate } from "@/lib/server/users";

export async function POST(req: NextRequest) {
  const bad = checkSameOrigin(req);
  if (bad) return bad;
  let body: { mode?: string; username?: string; password?: string };
  try {
    body = await req.json();
  } catch {
    return jsonError(400, "bad_request", "入力内容が不正です");
  }
  let token: string | null;
  if (body.mode === "demo") {
    if (!demoEnabled()) return jsonError(403, "demo_disabled", "デモモードは無効です");
    token = encodeSession({ u: "demo", m: "demo", a: ["demo"], r: "admin" });
  } else {
    const username = String(body.username ?? "").slice(0, 64);
    const password = String(body.password ?? "").slice(0, 256);
    const ip = req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ?? "local";
    const key = `${ip}:${username}`;
    if (!throttle(key)) return jsonError(429, "too_many_attempts", "試行回数が多すぎます。15分後に再度お試しください");
    const user = username && password ? authenticate(username, password) : null;
    if (!user) {
      recordFailure(key);
      return jsonError(401, "invalid_credentials", "ユーザー名またはパスワードが違います");
    }
    clearFailures(key);
    token = encodeSession({ u: user.username, m: "live", a: user.accounts, r: user.role });
  }
  if (!token) return jsonError(500, "session_secret_missing", "CC_SESSION_SECRET（32文字以上）が未設定のためログインできません");
  const res = NextResponse.json({ ok: true });
  res.cookies.set(SESSION_COOKIE, token, cookieOptions);
  return res;
}
