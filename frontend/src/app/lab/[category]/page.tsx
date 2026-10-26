"use client";
import Link from "next/link";
import { use } from "react";
import type { EventSummary } from "@/lib/api";
import { CATEGORY_JA, fmtJst, pct, usd } from "@/lib/format";
import { Dir, Loading, Stat, StatusBadge, Tag, useApi } from "@/components/ui";

interface Lab {
  category: string; upcoming: EventSummary[]; past: EventSummary[];
  distribution: Record<"verified" | "tentative", Record<string, { event_id: number; value: number }[]>>;
  reversal_patterns: Record<"verified" | "tentative", { event_id: number; title: string; initial_direction: string; initial_move: number | null; d5: number | null; reversed: boolean | null; reversal_size: number | null; observations: string[] }[]>;
  lessons: { event_id: number; generated_by: string; tentative: boolean; reflections: string[]; improvements: string[] }[];
  accuracy: Record<"confirmed" | "tentative", any>;
}

const DIST_LABEL: Record<string, string> = {
  max_excursion_5m: "5分最大到達幅", max_up_5m: "5分最大上昇幅", max_down_5m: "5分最大下落幅",
  range_5m: "5分レンジ", range_30m: "30分レンジ", range_60m: "60分レンジ", d5: "5分後終着地", d60: "60分後終着地",
};

function Dist({ data, title }: { data: Record<string, { value: number }[]>; title: string }) {
  const keys = Object.keys(data);
  return (
    <div>
      <div className="text-xs font-semibold mb-1">{title}</div>
      {keys.length === 0 ? <div className="text-xs text-muted">データなし</div> : (
        <table className="tbl"><thead><tr><th>項目</th><th>n</th><th>最小</th><th>中央値</th><th>最大</th></tr></thead>
          <tbody>{keys.map((k) => {
            const v = data[k].map((x) => x.value).sort((a, b) => a - b);
            return <tr key={k} className="num"><td>{DIST_LABEL[k] ?? k}</td><td>{v.length}</td><td>{usd(v[0], k.startsWith("d"))}</td><td>{usd(v[Math.floor(v.length / 2)], k.startsWith("d"))}</td><td>{usd(v[v.length - 1], k.startsWith("d"))}</td></tr>;
          })}</tbody></table>
      )}
    </div>
  );
}

export default function LabCategory({ params }: { params: Promise<{ category: string }> }) {
  const { category } = use(params);
  const { data, error, loading } = useApi<Lab>(`/api/lab/${category}`);
  if (!data) return <Loading error={error} loading={loading} />;
  const c = data.accuracy.confirmed, t = data.accuracy.tentative;
  return (
    <div className="space-y-4">
      <h1 className="text-lg font-bold">AI研究室: {CATEGORY_JA[category] ?? category}</h1>
      <section className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Stat label="方向正答率（確定）" value={pct(c?.direction_accuracy)} sub={`n=${c?.direction_n ?? 0}`} />
        <Stat label="5分後MAE（確定）" value={c?.d5_mae ?? "—"} sub="ドル" />
        <Stat label="方向正答率（暫定）" value={pct(t?.direction_accuracy)} sub={`n=${t?.direction_n ?? 0}`} />
        <Stat label="5分後MAE（暫定）" value={t?.d5_mae ?? "—"} sub="ドル" />
      </section>
      <section className="card">
        <div className="card-title">イベント一覧（今後 {data.upcoming.length} / 過去 {data.past.length}）</div>
        <div className="overflow-x-auto">
          <table className="tbl">
            <thead><tr><th>日時</th><th>イベント</th><th>状態</th><th>予測方向</th><th>実際</th><th>予測5分後</th><th>実際5分後</th><th>予測最大到達幅</th><th>実際</th></tr></thead>
            <tbody>{[...data.upcoming, ...data.past].map((e) => (
              <tr key={e.id} className="num">
                <td className="text-xs">{e.release_at ? fmtJst(e.release_at) : e.date_label}</td>
                <td><Link href={`/events/${e.id}`} className="hover:text-gold">{e.title}</Link></td>
                <td><StatusBadge status={e.status} label={e.status_ja} /></td>
                <td><Dir d={e.latest_forecast?.dominant_direction} /></td>
                <td><Dir d={e.outcome?.direction_5m ?? e.outcome?.observed_direction} /></td>
                <td>{usd(e.latest_forecast?.d5)}</td><td>{usd(e.outcome?.d5)}</td>
                <td>{e.latest_forecast?.max_excursion_5m ?? "—"}</td><td>{e.outcome?.max_excursion_5m ?? "—"}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </section>
      <section className="card grid lg:grid-cols-2 gap-4">
        <Dist data={data.distribution.verified} title="値幅分布（検証済み）" />
        <Dist data={data.distribution.tentative} title="値幅分布（未検証・参考）" />
      </section>
      <section className="card">
        <div className="card-title">反転パターン（初動 → 5分後）</div>
        {(["verified", "tentative"] as const).map((k) => (
          <div key={k} className="mb-3">
            <div className="text-xs mb-1">{k === "verified" ? <Tag tone="green">検証済み</Tag> : <Tag tone="red">未検証</Tag>}</div>
            {data.reversal_patterns[k].length === 0 ? <div className="text-xs text-muted">データなし</div> : (
              <ul className="text-sm space-y-1">{data.reversal_patterns[k].map((r, i) => (
                <li key={i}><Link href={`/events/${r.event_id}`} className="hover:text-gold">{r.title}</Link>: 初動 <Dir d={r.initial_direction} /> {r.initial_move != null && usd(r.initial_move)} → 5分後 {usd(r.d5)}
                  {r.reversed != null && <span className="text-muted">（反転{r.reversed ? `あり ${r.reversal_size}ドル` : "なし"}）</span>}
                  {r.observations.length > 0 && <div className="text-xs text-muted">{r.observations.join(" / ")}</div>}
                </li>
              ))}</ul>
            )}
          </div>
        ))}
      </section>
      <section className="card">
        <div className="card-title">蓄積された教訓・改善点</div>
        <ul className="text-sm space-y-2">{data.lessons.filter((l) => l.reflections.length || l.improvements.length).map((l, i) => (
          <li key={i} className="border-l-2 border-line pl-3">
            <div className="text-[11px] text-muted"><Link href={`/events/${l.event_id}`} className="hover:text-gold">イベント#{l.event_id}</Link> / {l.generated_by} {l.tentative && "（暫定）"}</div>
            {l.reflections.map((r, j) => <div key={j}>・{r}</div>)}
            {l.improvements.map((r, j) => <div key={`i${j}`} className="text-sky-300">→ {r}</div>)}
          </li>
        ))}</ul>
      </section>
    </div>
  );
}
