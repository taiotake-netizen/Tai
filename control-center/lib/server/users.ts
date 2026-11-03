import "server-only";
import { scryptSync, timingSafeEqual } from "node:crypto";

export type User = { username: string; accounts: string[]; role: "admin" | "viewer" };
type StoredUser = User & { password_hash: string };

/** CC_USERS = JSON array: [{"username","password_hash":"scrypt$<salt-b64>$<hash-b64>","accounts":["main"],"role":"admin"}] */
function load(): StoredUser[] {
  const raw = process.env.CC_USERS;
  if (!raw) return [];
  try {
    const arr = JSON.parse(raw) as unknown;
    if (!Array.isArray(arr)) return [];
    return arr
      .filter((u): u is StoredUser =>
        typeof u?.username === "string" && typeof u?.password_hash === "string" && Array.isArray(u?.accounts))
      .map((u) => ({ ...u, role: u.role === "viewer" ? "viewer" : "admin" }));
  } catch {
    return [];
  }
}

export function verifyPassword(password: string, stored: string): boolean {
  const [scheme, saltB64, hashB64] = stored.split("$");
  if (scheme !== "scrypt" || !saltB64 || !hashB64) return false;
  const expected = Buffer.from(hashB64, "base64");
  const actual = scryptSync(password, Buffer.from(saltB64, "base64"), expected.length, { N: 16384, r: 8, p: 1 });
  return expected.length === actual.length && timingSafeEqual(expected, actual);
}

export function authenticate(username: string, password: string): User | null {
  const u = load().find((x) => x.username === username);
  // run a dummy hash when the user does not exist, to keep timing similar
  const ok = verifyPassword(password, u?.password_hash ?? "scrypt$AAAAAAAAAAAAAAAAAAAAAA==$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=");
  if (!u || !ok) return null;
  return { username: u.username, accounts: u.accounts.map(String), role: u.role };
}

export function usersConfigured(): boolean {
  return load().length > 0;
}
