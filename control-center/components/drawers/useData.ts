"use client";

import { useEffect, useState } from "react";
import { ApiError, type Api } from "@/lib/client/api";

/** Fetch a resource while `enabled`; re-fetches when `version` changes. */
export function useData<T>(client: Api | null, path: string | null, enabled: boolean, version: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!client || !path || !enabled) return;
    let alive = true;
    client.get<T>(path).then((d) => { if (alive) { setData(d); setError(null); } })
      .catch((e: unknown) => { if (alive) setError(e instanceof ApiError ? e.message : "取得に失敗しました"); });
    return () => { alive = false; };
  }, [client, path, enabled, version, tick]);
  return { data, error, reload: () => setTick((t) => t + 1), setData };
}
