import { NextResponse, type NextRequest } from "next/server";
import { checkSameOrigin, jsonError } from "@/lib/server/guard";
import { cleanQuery, matchRule } from "@/lib/server/routes";
import { decodeSession, SESSION_COOKIE } from "@/lib/server/session";
import { callUpstream } from "@/lib/server/upstream";

/**
 * BFF adapter: /api/cc/{accountId}/{path} → engine /v1/accounts/{accountId}/{path}
 * - session required; account must be in the session's allowed list
 * - only allowlisted method+path combinations
 * - demo sessions only ever reach the demo engine; live sessions only the live engine
 */
async function handle(req: NextRequest, params: Promise<{ path: string[] }>) {
  const session = decodeSession(req.cookies.get(SESSION_COOKIE)?.value);
  if (!session) return jsonError(401, "unauthorized", "ログインが必要です");
  const method = req.method.toUpperCase();
  if (method !== "GET") {
    const bad = checkSameOrigin(req);
    if (bad) return bad;
    if (session.r !== "admin") return jsonError(403, "forbidden", "閲覧専用ユーザーは操作できません");
  }
  const { path } = await params;
  if (!Array.isArray(path) || path.length < 2) return jsonError(404, "not_found", "対象が見つかりません");
  const [accountId, ...rest] = path;
  if (!/^[A-Za-z0-9_-]{1,64}$/.test(accountId) || !session.a.includes(accountId)) {
    return jsonError(404, "not_found", "対象が見つかりません");
  }
  const sub = rest.join("/");
  const rule = matchRule(method, sub);
  if (!rule) return jsonError(404, "not_found", "対象が見つかりません");
  if (rule.demoOnly && session.m !== "demo") return jsonError(404, "not_found", "対象が見つかりません");
  let body: string | undefined;
  if (method !== "GET") {
    const text = await req.text();
    if (text.length > 64 * 1024) return jsonError(413, "too_large", "入力が大きすぎます");
    if (text) {
      try {
        JSON.parse(text);
      } catch {
        return jsonError(400, "bad_request", "入力内容が不正です");
      }
    }
    body = text || "{}";
  }
  const upstreamPath = rule.demoOnly ? `/v1/${sub}` : `/v1/accounts/${encodeURIComponent(accountId)}/${sub}${cleanQuery(req.nextUrl.searchParams)}`;
  const r = await callUpstream(session, method, upstreamPath, body);
  return NextResponse.json(r.body, { status: r.status, headers: { "cache-control": "no-store", "x-cc-data-source": session.m } });
}

type Ctx = { params: Promise<{ path: string[] }> };
export async function GET(req: NextRequest, ctx: Ctx) { return handle(req, ctx.params); }
export async function POST(req: NextRequest, ctx: Ctx) { return handle(req, ctx.params); }
export async function PUT(req: NextRequest, ctx: Ctx) { return handle(req, ctx.params); }
export async function PATCH(req: NextRequest, ctx: Ctx) { return handle(req, ctx.params); }
