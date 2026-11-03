import { NextResponse, type NextRequest } from "next/server";
import { checkSameOrigin } from "@/lib/server/guard";
import { SESSION_COOKIE } from "@/lib/server/session";

export async function POST(req: NextRequest) {
  const bad = checkSameOrigin(req);
  if (bad) return bad;
  const res = NextResponse.json({ ok: true });
  res.cookies.set(SESSION_COOKIE, "", { path: "/", maxAge: 0 });
  return res;
}
