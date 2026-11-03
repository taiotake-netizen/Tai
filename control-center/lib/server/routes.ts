/**
 * Allowlist of upstream operations the browser may reach through the BFF.
 * Path is relative to /v1/accounts/{accountId}/ on the Threads engine. Anything else is rejected.
 */
export type Method = "GET" | "POST" | "PUT" | "PATCH";
type Rule = { method: Method; pattern: RegExp; write: boolean; demoOnly?: boolean };

const ID = "\\d{1,10}";
export const RULES: Rule[] = [
  { method: "GET", pattern: /^overview$/, write: false },
  { method: "GET", pattern: /^capabilities$/, write: false },
  { method: "GET", pattern: /^jobs$/, write: false },
  { method: "POST", pattern: new RegExp(`^jobs/${ID}/(cancel|retry)$`), write: true },
  { method: "GET", pattern: /^posts$/, write: false },
  { method: "GET", pattern: new RegExp(`^posts/${ID}$`), write: false },
  { method: "POST", pattern: new RegExp(`^posts/${ID}/(approve|cancel|resolve)$`), write: true },
  { method: "PATCH", pattern: new RegExp(`^posts/${ID}/text$`), write: true },
  { method: "GET", pattern: /^events$/, write: false },
  { method: "GET", pattern: /^ideas$/, write: false },
  { method: "POST", pattern: /^ideas$/, write: true },
  { method: "GET", pattern: new RegExp(`^ideas/${ID}$`), write: false },
  { method: "PUT", pattern: new RegExp(`^ideas/${ID}$`), write: true },
  { method: "POST", pattern: new RegExp(`^ideas/${ID}/status$`), write: true },
  { method: "GET", pattern: /^policy$/, write: false },
  { method: "POST", pattern: /^policy\/rollback$/, write: true },
  { method: "GET", pattern: /^experiments$/, write: false },
  { method: "POST", pattern: /^experiments\/stop$/, write: true },
  { method: "GET", pattern: /^reports$/, write: false },
  { method: "GET", pattern: new RegExp(`^reports/${ID}$`), write: false },
  { method: "POST", pattern: /^reports\/regenerate$/, write: true },
  { method: "GET", pattern: /^settings$/, write: false },
  { method: "PATCH", pattern: /^settings$/, write: true },
  { method: "POST", pattern: /^control\/(autopilot|improvement|stop)$/, write: true },
  { method: "POST", pattern: /^connection\/check$/, write: true },
  { method: "GET", pattern: /^usage$/, write: false },
  { method: "GET", pattern: /^audit$/, write: false },
  { method: "GET", pattern: /^assistant\/runs$/, write: false },
  { method: "POST", pattern: /^assistant\/runs$/, write: true },
  { method: "POST", pattern: /^demo\/scenario$/, write: true, demoOnly: true },
];

export function matchRule(method: string, path: string): Rule | null {
  return RULES.find((r) => r.method === method && r.pattern.test(path)) ?? null;
}

const ALLOWED_QUERY = new Set(["view", "limit", "offset", "status", "theme", "q", "after_seq", "kind", "before_id"]);

export function cleanQuery(params: URLSearchParams): string {
  const out = new URLSearchParams();
  params.forEach((v, k) => {
    if (ALLOWED_QUERY.has(k) && v.length <= 200) out.append(k, v);
  });
  const s = out.toString();
  return s ? `?${s}` : "";
}
