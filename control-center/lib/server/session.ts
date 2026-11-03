import "server-only";
import { createHmac, timingSafeEqual } from "node:crypto";
import { cookies } from "next/headers";
import { isProduction, sessionSecret } from "./config";

export const SESSION_COOKIE = "cc_session";
const TTL_SECONDS = 60 * 60 * 12;

export type Session = {
  u: string;              // username
  m: "live" | "demo";     // data source — never mixed
  a: string[];            // accounts this user may access
  r: "admin" | "viewer";
  exp: number;            // unix seconds
};

function sign(payload: string, secret: string): string {
  return createHmac("sha256", secret).update(payload).digest("base64url");
}

export function encodeSession(s: Omit<Session, "exp">, now = Date.now()): string | null {
  const secret = sessionSecret();
  if (!secret) return null;
  const body = Buffer.from(JSON.stringify({ ...s, exp: Math.floor(now / 1000) + TTL_SECONDS })).toString("base64url");
  return `${body}.${sign(body, secret)}`;
}

export function decodeSession(token: string | undefined, now = Date.now()): Session | null {
  const secret = sessionSecret();
  if (!token || !secret) return null;
  const [body, sig] = token.split(".");
  if (!body || !sig) return null;
  const expected = Buffer.from(sign(body, secret));
  const given = Buffer.from(sig);
  if (expected.length !== given.length || !timingSafeEqual(expected, given)) return null;
  try {
    const s = JSON.parse(Buffer.from(body, "base64url").toString()) as Session;
    if (typeof s.exp !== "number" || s.exp * 1000 < now) return null;
    if (s.m !== "live" && s.m !== "demo") return null;
    if (!Array.isArray(s.a)) return null;
    return s;
  } catch {
    return null;
  }
}

export async function currentSession(): Promise<Session | null> {
  const jar = await cookies();
  return decodeSession(jar.get(SESSION_COOKIE)?.value);
}

export const cookieOptions = {
  httpOnly: true,
  sameSite: "lax" as const,
  secure: isProduction,
  path: "/",
  maxAge: TTL_SECONDS,
};
