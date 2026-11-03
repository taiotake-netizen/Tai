import { NextResponse, type NextRequest } from "next/server";
import { jsonError } from "@/lib/server/guard";
import { decodeSession, SESSION_COOKIE } from "@/lib/server/session";
import { callUpstream } from "@/lib/server/upstream";

/** Who am I + engine reachability (used for the header and the "disconnected" core state). */
export async function GET(req: NextRequest) {
  const s = decodeSession(req.cookies.get(SESSION_COOKIE)?.value);
  if (!s) return jsonError(401, "unauthorized", "ログインが必要です");
  const h = await callUpstream(s, "GET", "/v1/health");
  const accts = await callUpstream(s, "GET", "/v1/accounts");
  return NextResponse.json(
    { user: s.u, mode: s.m, role: s.r, accounts: s.a, engine: { status: h.status, health: h.status === 200 ? h.body : null,
      error: h.status === 200 ? null : h.body }, engineAccounts: accts.status === 200 ? accts.body : null },
    { headers: { "cache-control": "no-store" } },
  );
}
