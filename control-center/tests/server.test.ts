import { randomBytes, scryptSync } from "node:crypto";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/headers", () => ({ cookies: async () => ({ get: () => undefined }) }));

describe("session tokens", () => {
  afterEach(() => vi.unstubAllEnvs());
  it("round-trips and rejects tampering and expiry", async () => {
    vi.stubEnv("CC_SESSION_SECRET", "x".repeat(40));
    const { encodeSession, decodeSession } = await import("@/lib/server/session");
    const t = encodeSession({ u: "tai", m: "live", a: ["main"], r: "admin" })!;
    expect(decodeSession(t)?.u).toBe("tai");
    const [body, sig] = t.split(".");
    const forged = Buffer.from(JSON.stringify({ u: "tai", m: "live", a: ["main", "other"], r: "admin", exp: 9e9 })).toString("base64url");
    expect(decodeSession([forged, sig].join("."))).toBeNull();
    expect(decodeSession([body, "AAAA"].join("."))).toBeNull();
    expect(decodeSession(t, Date.now() + 13 * 3600 * 1000)).toBeNull();
  });
});

describe("users", () => {
  it("verifies scrypt hashes", async () => {
    const salt = randomBytes(16);
    const digest = scryptSync("correct horse battery", salt, 32, { N: 16384, r: 8, p: 1 }).toString("base64");
    const hash = ["scrypt", salt.toString("base64"), digest].join("$");
    vi.stubEnv("CC_USERS", JSON.stringify([{ username: "tai", password_hash: hash, accounts: ["main"] }]));
    const { authenticate } = await import("@/lib/server/users");
    expect(authenticate("tai", "correct horse battery")?.accounts).toEqual(["main"]);
    expect(authenticate("tai", "wrong")).toBeNull();
    expect(authenticate("nobody", "correct horse battery")).toBeNull();
  });
});

describe("BFF allowlist", () => {
  it("only allows known method+path combinations", async () => {
    const { matchRule, cleanQuery } = await import("@/lib/server/routes");
    expect(matchRule("GET", "overview")).not.toBeNull();
    expect(matchRule("POST", "jobs/12/cancel")).not.toBeNull();
    expect(matchRule("POST", "overview")).toBeNull();
    expect(matchRule("GET", "../../health")).toBeNull();
    expect(matchRule("GET", "posts/1/../../x")).toBeNull();
    expect(matchRule("DELETE", "posts/1")).toBeNull();
    expect(matchRule("POST", "demo/scenario")?.demoOnly).toBe(true);
    expect(cleanQuery(new URLSearchParams("view=history&evil=1&limit=5"))).toBe("?view=history&limit=5");
  });
});
