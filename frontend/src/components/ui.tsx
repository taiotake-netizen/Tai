"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, errorText, type Forecast } from "@/lib/api";
import { CATEGORY_JA, dirClass, dirJa, pct } from "@/lib/format";

export function useApi<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const reload = useCallback(async () => {
    if (!path) return;
    setLoading(true);
    try {
      setData(await api<T>(path));
      setError(null);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setLoading(false);
    }
  }, [path]);
  useEffect(() => { reload(); }, [reload]);
  return { data, error, loading, reload };
}

export function Loading({ error, loading }: { error: string | null; loading: boolean }) {
  if (error) return <div className="card text-down text-sm whitespace-pre-wrap">読み込みに失敗しました: {error}</div>;
  if (loading) return <div className="card text-muted text-sm">読み込み中…</div>;
  return null;
}

const STATUS_STYLE: Record<string, string> = {
  upcoming: "bg-sky-500/15 text-sky-300 border-sky-500/30",
  forecasted: "bg-gold/15 text-gold border-gold/30",
  awaiting_data: "bg-orange-500/15 text-orange-300 border-orange-500/30",
  verifying: "bg-purple-500/15 text-purple-300 border-purple-500/30",
  verified: "bg-up/15 text-up border-up/30",
  historical_unverified: "bg-slate-500/15 text-slate-300 border-slate-500/30",
};

export function StatusBadge({ status, label }: { status: string; label: string }) {
  return <span className={`text-[11px] px-2 py-0.5 rounded-full border whitespace-nowrap ${STATUS_STYLE[status] ?? ""}`}>{label}</span>;
}

export function Tag({ children, tone = "slate" }: { children: React.ReactNode; tone?: "slate" | "gold" | "red" | "green" }) {
  const t = { slate: "border-line text-muted", gold: "border-gold/40 text-gold", red: "border-down/40 text-down", green: "border-up/40 text-up" }[tone];
  return <span className={`text-[11px] px-1.5 py-0.5 rounded border whitespace-nowrap ${t}`}>{children}</span>;
}

export function Unverified({ verified }: { verified: boolean }) {
  return verified ? <Tag tone="green">検証済み</Tag> : <Tag tone="red">未検証</Tag>;
}

export function Importance({ value }: { value: number }) {
  return (
    <span className="inline-flex items-center gap-1" title={`重要度 ${value}/10`}>
      <span className="flex gap-[2px]">
        {Array.from({ length: 10 }).map((_, i) => (
          <span key={i} className={`h-2.5 w-1 rounded-sm ${i < value ? (value >= 8 ? "bg-gold" : "bg-sky-400") : "bg-line"}`} />
        ))}
      </span>
      <span className="text-xs text-muted num">{value}</span>
    </span>
  );
}

export function CategoryLabel({ c }: { c: string }) {
  return <Link href={`/lab/${c}`} className="text-[11px] px-1.5 py-0.5 rounded bg-panel2 border border-line hover:border-gold/50">{CATEGORY_JA[c] ?? c}</Link>;
}

export function ProbBar({ f }: { f: Pick<Forecast, "prob_up" | "prob_down" | "prob_flat"> }) {
  const { prob_up: u, prob_down: d, prob_flat: fl } = f;
  if (u == null && d == null && fl == null) return <span className="text-muted text-xs">確率記録なし</span>;
  return (
    <div className="min-w-[140px]">
      <div className="flex h-2 rounded overflow-hidden bg-line">
        <div className="bg-up" style={{ width: `${u ?? 0}%` }} />
        <div className="bg-flat" style={{ width: `${fl ?? 0}%` }} />
        <div className="bg-down" style={{ width: `${d ?? 0}%` }} />
      </div>
      <div className="flex justify-between text-[11px] mt-1 num">
        <span className="text-up">上 {pct(u)}</span>
        <span className="text-flat">横 {pct(fl)}</span>
        <span className="text-down">下 {pct(d)}</span>
      </div>
    </div>
  );
}

export function Dir({ d, suffix }: { d: string | null | undefined; suffix?: string }) {
  return <span className={dirClass(d)}>{dirJa(d)}{d && suffix ? suffix : ""}</span>;
}

export function Countdown({ target }: { target: string }) {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    setNow(Date.now());
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  if (now === null) return <span className="num">--</span>;
  let s = Math.max(0, Math.floor((new Date(target).getTime() - now) / 1000));
  if (s === 0) return <span className="text-gold">発表済み</span>;
  const d = Math.floor(s / 86400); s -= d * 86400;
  const h = Math.floor(s / 3600); s -= h * 3600;
  const m = Math.floor(s / 60); s -= m * 60;
  return (
    <span className="num font-mono">
      {d > 0 && <>{d}<span className="text-xs text-muted mx-0.5">日</span></>}
      {String(h).padStart(2, "0")}:{String(m).padStart(2, "0")}:{String(s).padStart(2, "0")}
    </span>
  );
}

export function Stat({ label, value, sub }: { label: string; value: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <div className="bg-panel2 rounded-lg p-3 border border-line">
      <div className="label">{label}</div>
      <div className="text-lg font-semibold num mt-0.5">{value}</div>
      {sub && <div className="text-[11px] text-muted mt-0.5">{sub}</div>}
    </div>
  );
}
