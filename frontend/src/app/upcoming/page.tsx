"use client";
import Link from "next/link";
import type { EventSummary } from "@/lib/api";
import { fmtJst, usd } from "@/lib/format";
import { CategoryLabel, Countdown, Importance, Loading, ProbBar, StatusBadge, Tag, useApi } from "@/components/ui";

export default function UpcomingPage() {
  const { data, error, loading } = useApi<EventSummary[]>("/api/events?scope=upcoming");
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-bold">今後の経済指標</h1>
        <Link href="/events/new" className="btn">＋ イベント登録</Link>
      </div>
      {!data ? <Loading error={error} loading={loading} /> : data.length === 0 ? (
        <div className="card text-sm text-muted">今後のイベントはありません。</div>
      ) : (
        <div className="grid gap-3">
          {data.map((e) => {
            const f = e.latest_forecast;
            const cons = e.indicators.filter((i) => i.consensus != null || i.previous != null);
            const ai = Object.fromEntries((f?.indicator_forecasts ?? []).map((x) => [x.code, x.point]));
            return (
              <Link key={e.id} href={`/events/${e.id}`} className="card hover:border-gold/50 transition block">
                <div className="flex flex-wrap items-center gap-2">
                  <CategoryLabel c={e.category} />
                  <StatusBadge status={e.status} label={e.status_ja} />
                  {!e.release_time_confirmed && <Tag tone="red">時刻未確定</Tag>}
                  {e.is_composite && <Tag>複合イベント</Tag>}
                  <span className="ml-auto text-gold text-sm"><Countdown target={e.release_at!} /></span>
                </div>
                <div className="mt-2 font-semibold">{e.title}</div>
                <div className="text-sm text-muted num">{fmtJst(e.release_at)}（日本時間）</div>
                <div className="grid md:grid-cols-5 gap-3 mt-3 items-start">
                  <div><div className="label">重要度</div><Importance value={e.importance} /></div>
                  <div className="md:col-span-2">
                    <div className="label mb-1">上昇・横ばい・下落確率</div>
                    {f ? <ProbBar f={f} /> : <span className="text-xs text-muted">予測なし</span>}
                  </div>
                  <div>
                    <div className="label">最大変動幅予測（5分）</div>
                    <div className="num">{f?.max_excursion_5m != null ? `${f.max_excursion_5m}ドル` : "—"}</div>
                  </div>
                  <div>
                    <div className="label">5分後終着地予測</div>
                    <div className={`num ${f?.d5 == null ? "" : f.d5 < 0 ? "text-down" : "text-up"}`}>{f?.d5 != null ? `${usd(f.d5)}ドル` : "—"}</div>
                  </div>
                </div>
                {e.indicators.length > 0 && (
                  <div className="overflow-x-auto mt-3">
                    <table className="tbl">
                      <thead><tr><th>指標</th><th>前回実績</th><th>市場コンセンサス</th><th>AI独自予想</th></tr></thead>
                      <tbody>
                        {e.indicators.map((i) => (
                          <tr key={i.id} className="num">
                            <td>{i.name}</td>
                            <td>{i.previous_revised ?? i.previous ?? "—"}{(i.previous ?? i.previous_revised) != null && i.unit}</td>
                            <td>{i.consensus ?? "—"}{i.consensus != null && i.unit}</td>
                            <td className="text-gold">{ai[i.code] ?? "—"}{ai[i.code] != null && i.unit}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {cons.length === 0 && <div className="text-[11px] text-muted mt-1">前回値・市場予想は未登録（Phase 2で自動取得予定。詳細画面から手入力可）</div>}
                  </div>
                )}
                <div className="text-[11px] text-muted mt-2">予測の最終更新: {f ? `${fmtJst(f.created_at)}（Ver.${f.version_no} ${f.label}）` : "—"}</div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
