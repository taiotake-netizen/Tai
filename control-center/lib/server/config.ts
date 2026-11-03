import "server-only";

/** Server-side configuration. Secrets stay on the server; nothing here is sent to the browser. */
export type Upstream = { url: string; token: string | null };

function env(name: string): string | undefined {
  const v = process.env[name];
  return v && v.trim() !== "" ? v.trim() : undefined;
}

export const isProduction = process.env.NODE_ENV === "production";

export function sessionSecret(): string | null {
  const s = env("CC_SESSION_SECRET");
  if (s && s.length >= 32) return s;
  if (isProduction) return null; // refuse to run auth in production without a strong secret
  return "dev-only-insecure-session-secret-change-me-0000";
}

export function demoEnabled(): boolean {
  return env("CC_DEMO_ENABLED") === "true";
}

export function liveUpstream(): Upstream | null {
  const url = env("THREADS_OPS_URL");
  if (!url) return null;
  return { url: url.replace(/\/$/, ""), token: env("THREADS_OPS_API_TOKEN") ?? null };
}

export function demoUpstream(): Upstream | null {
  const url = env("DEMO_THREADS_OPS_URL");
  if (!url) return null;
  return { url: url.replace(/\/$/, ""), token: env("DEMO_THREADS_OPS_API_TOKEN") ?? null };
}

/** Only these hosts may be contacted by the adapter (prevents the BFF from becoming an open proxy). */
export function allowedUpstreamHosts(): string[] {
  const extra = (env("CC_ALLOWED_UPSTREAM_HOSTS") ?? "").split(",").map((s) => s.trim()).filter(Boolean);
  return ["127.0.0.1", "localhost", ...extra];
}
