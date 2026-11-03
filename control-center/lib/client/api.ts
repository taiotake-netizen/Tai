"use client";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: unknown) {
    super(message);
  }
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, {
      method,
      credentials: "same-origin",
      cache: "no-store",
      headers: method === "GET" ? {} : { "content-type": "application/json", "x-cc-request": "1" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "network", "管理画面サーバーに接続できません");
  }
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!res.ok) {
    const err = (data as { error?: { code?: string; message?: string; details?: unknown } } | null)?.error;
    if (res.status === 401 && typeof window !== "undefined" && !url.startsWith("/api/auth")) {
      // session expired: full navigation (outside React) so no stale client state survives
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.href = "/login";
    }
    throw new ApiError(res.status, err?.code ?? `http_${res.status}`, err?.message ?? `エラー（HTTP ${res.status}）`, err?.details);
  }
  return data as T;
}

export function api(account: string) {
  const base = `/api/cc/${encodeURIComponent(account)}`;
  return {
    get: <T>(path: string) => request<T>("GET", `${base}/${path}`),
    post: <T>(path: string, body: unknown = {}) => request<T>("POST", `${base}/${path}`, body),
    put: <T>(path: string, body: unknown) => request<T>("PUT", `${base}/${path}`, body),
    patch: <T>(path: string, body: unknown) => request<T>("PATCH", `${base}/${path}`, body),
  };
}

export type Api = ReturnType<typeof api>;

export const sessionApi = {
  get: <T>() => request<T>("GET", "/api/session"),
  login: (body: unknown) => request<{ ok: true }>("POST", "/api/auth/login", body),
  logout: () => request<{ ok: true }>("POST", "/api/auth/logout", {}),
};
