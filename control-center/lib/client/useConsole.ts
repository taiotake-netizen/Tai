"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { deriveCore, mergeEvents, newCelebrations, type CoreVisual } from "../coreState";
import type { Capabilities, EventItem, Overview, SessionInfo } from "../types";
import { api, ApiError, sessionApi } from "./api";

const EVENTS_MS = 4000;
const OVERVIEW_MS = 10000;
const PLAYED_KEY = "cc.playedSuccess";

function loadPlayed(): Set<string> {
  try {
    return new Set(JSON.parse(sessionStorage.getItem(PLAYED_KEY) ?? "[]") as string[]);
  } catch {
    return new Set();
  }
}

function savePlayed(s: Set<string>) {
  try {
    sessionStorage.setItem(PLAYED_KEY, JSON.stringify([...s].slice(-300)));
  } catch {
    /* storage may be unavailable; replay protection then lasts for this page only */
  }
}

export type ConsoleState = ReturnType<typeof useConsole>;

export function useConsole() {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [account, setAccount] = useState<string | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [events, setEvents] = useState<EventItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [reachable, setReachable] = useState(true);
  const [lastSync, setLastSync] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [pulse, setPulse] = useState<{ id: string; at: number } | null>(null);
  const [version, setVersion] = useState(0);               // bump to force data refresh in panels
  const cursor = useRef(0);
  const played = useRef<Set<string>>(new Set());
  const client = useMemo(() => (account ? api(account) : null), [account]);

  useEffect(() => {
    played.current = loadPlayed();
    sessionApi.get<SessionInfo>().then((s) => {
      setSession(s);
      setAccount(s.accounts[0] ?? null);
      if (s.engine.status !== 200) {
        setReachable(false);
        setError(s.engine.error?.error?.message ?? "Threads運用エンジンに接続できません");
      }
      if (!s.accounts.length) setLoading(false);
    }).catch((e: unknown) => {
      setError(e instanceof ApiError ? e.message : "セッションを確認できません");
      setLoading(false);
    });
  }, []);

  const refreshOverview = useCallback(async () => {
    if (!client) return;
    try {
      const [o, c] = await Promise.all([client.get<Overview>("overview"), client.get<Capabilities>("capabilities")]);
      setOverview(o);
      setCaps(c);
      setReachable(true);
      setError(null);
      setLastSync(new Date().toISOString());
    } catch (e) {
      setReachable(false);
      setError(e instanceof ApiError ? e.message : "取得に失敗しました");
    } finally {
      setLoading(false);
    }
  }, [client]);

  const pollEvents = useCallback(async (initial: boolean) => {
    if (!client) return;
    try {
      let more = true;
      let guard = 0;
      while (more && guard++ < 10) {             // catch up after a reconnect without flooding
        const r = await client.get<{ items: EventItem[]; cursor: number; has_more: boolean }>(
          `events?after_seq=${cursor.current}&limit=100`);
        cursor.current = Math.max(cursor.current, r.cursor);
        more = r.has_more;
        if (r.items.length) {
          setEvents((cur) => mergeEvents(cur, r.items));
          if (initial) {
            r.items.forEach((e) => played.current.add(e.event_id));   // history is not celebrated
          } else {
            const fresh = newCelebrations(r.items, played.current);
            if (fresh.length) {
              fresh.forEach((e) => played.current.add(e.event_id));
              setPulse({ id: fresh[fresh.length - 1].event_id, at: Date.now() });
            }
            setVersion((v) => v + 1);
            void refreshOverview();
          }
          savePlayed(played.current);
        }
        initial = false;
      }
      setReachable(true);
    } catch {
      setReachable(false);
    }
  }, [client, refreshOverview]);

  useEffect(() => {
    if (!client) return;
    cursor.current = 0;
    const kick = setTimeout(() => { void refreshOverview(); void pollEvents(true); }, 0);
    const t1 = setInterval(() => { if (!document.hidden) void pollEvents(false); }, EVENTS_MS);
    const t2 = setInterval(() => { if (!document.hidden) void refreshOverview(); }, OVERVIEW_MS);
    const onVis = () => { if (!document.hidden) { void pollEvents(false); void refreshOverview(); } };
    document.addEventListener("visibilitychange", onVis);
    return () => { clearTimeout(kick); clearInterval(t1); clearInterval(t2); document.removeEventListener("visibilitychange", onVis); };
  }, [client, pollEvents, refreshOverview]);

  const core: CoreVisual = deriveCore({ reachable, overview, selected });

  return {
    session, account, setAccount, overview, caps, events: events.filter((e) => e.account_id === account), error, reachable, lastSync, loading, selected, setSelected,
    pulse, core, client, refreshOverview, version, bump: () => setVersion((v) => v + 1),
    can: (action: string) => caps?.actions[action] ?? { enabled: false, reason: "読み込み中" },
  };
}
