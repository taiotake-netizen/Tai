"use client";
import Link from "next/link";
import { useMemo, useState } from "react";
import type { EventSummary } from "@/lib/api";
import { fmtJst, usd } from "@/lib/format";
import { CategoryLabel, Countdown, Importance, Loading, ProbBar, StatusBadge, Tag, useApi } from "@/components/ui";

const dayKey = (iso: string) =>
  new Date(iso).toLocaleDateString("ja-JP", { timeZone: "Asia/Tokyo", month: "long", day: "numeric", weekday: "short" });

export default function UpcomingPage() {
  const { data, error, loading } = useApi<EventSummary[]>("/api/events?scope=upcoming");
  const [minImp, setMinImp] = useState(6);
  const groups = useMemo(() => {
    const g: [string, EventSummary[]][] = [];
    for (const e of (data ?? []).filter((e) => e.importance >= minImp && !e.parent_id)) {
      const k = dayKey(e.release_at!);
      const last = g[g.length - 1];
      if (last && last[0] === k) last[1].push(e); else g.push([k, [e]]);
    }
    return g;
  }, [data, minImp]);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 justify-between">
        <h1 className="text-lg font-bold">今後の経済指標</h1>
        <div className="flex items-center gap-2 text-sm">
          <span className="label">重要度</span>
          {[1, 6, 8].map((n) => (
            <button key={n} className={`btn ${minImp === n ? "border-gold text-gold" : ""}`} onClick={() => setMinImp(n)}>{n === 1 ? "すべて" : `${n}以上`}</button>
          ))}
          <Link href="/events/new" className="btn">＋ 登録</Link>
        </div>
      </div>
      <p className="text-xs text-muted">日時はすべて日本時間。「公式日程」は発表機関のスケジュールで確認済み、「時刻未確定」は第三者カレンダーや通常パターンに基づくものです。米国は11月1日に夏時間が終わるため、以降は1時間遅くなります。</p>
      {!data ? <Loading error={error} loading={loading} /> : groups.length === 0 ? (
        <div className="card text-sm text-muted">該当するイベントはありません。</div>
      ) : groups.map(([day, list]) => (
        <section key={day} className="space-y-2">
          <div className="text-sm font-semibold text-gold">{day}</div>
          {list.map((e) => {
            const f = e.latest_forecast;
            const ai = Object.fromEntries((f?.indicator_forecasts ?? []).map((x) => [x.code, x.point]));
            return (
              <Link key={e.id} href={`/events/${e.id}`} className="card hover:border-gold/50 transition block">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="num text-sm font-semibold">{new Date(e.release_at!).toLocaleTimeString("ja-JP", { timeZone: "Asia/Tokyo", hour: "2-digit", minute: "2-digit" })}</span>
                  {e.categories.map((c) => <CategoryLabel key={c} c={c} />)}
                  <StatusBadge status={e.status} label={e.status_ja} />
                  {e.release_time_confirmed ? <Tag tone="green">公式日程</Tag> : <Tag tone="red">時刻未確定</Tag>}
                  <span className="ml-auto text-gold text-sm"><Countdown target={e.release_at!} /></span>
                </div>
                <div className="mt-1.5 font-semibold">{e.title}</div>
                <div className="grid md:grid-cols-5 gap-3 mt-3 items-start">
                  <div><div className="label">重要度</div><Importance value={e.importance} /></div>
                  <div className="md:col-span-2">
                    <div className="label mb-1">上昇・横ばい・下落確率</div>
                    {f ? <ProbBar f={f} /> : <span className="text-xs text-muted">予測なし</span>}
                  </div>
                  <div><div className="label">最大変動幅予測（5分）</div><div className="num">{f?.max_excursion_5m != null ? `${f.max_excursion_5m}ドル` : "—"}</div></div>
                  <div><div className="label">5分後終着地予測</div><div className={`num ${f?.d5 == null ? "" : f.d5 < 0 ? "text-down" : "text-up"}`}>{f?.d5 != null ? `${usd(f.d5)}ドル` : "—"}</div></div>
                </div>
                {e.indicators.length > 0 && (
                  <div className="overflow-x-auto mt-3">
                    <table className="tbl">
                      <thead><tr><th>指標</th><th>前回実績</th><th>市場コンセンサス</th><th>AI独自予想</th></tr></thead>
                      <tbody>
                        {e.indicators.map((i) => (
                          <tr key={i.id} className="num">
                            <td>{i.name}</td>
                            <td>{i.previous_revised ?? i.previous ?? "—"}{(i.previous_revised ?? i.previous) != null && i.unit}</td>
                            <td>{i.consensus ?? "—"}{i.consensus != null && i.unit}</td>
                            <td className="text-gold">{ai[i.code] ?? "—"}{ai[i.code] != null && i.unit}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                <div className="text-[11px] text-muted mt-2">予測の最終更新: {f ? `${fmtJst(f.created_at)}（Ver.${f.version_no} ${f.label}）` : "—"}</div>
              </Link>
            );
          })}
        </section>
      ))}
    </div>
  );
}
