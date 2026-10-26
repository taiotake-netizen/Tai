"use client";
import Link from "next/link";
import type { EventSummary } from "@/lib/api";
import { fmtJst, usd } from "@/lib/format";
import { CategoryLabel, Dir, Loading, StatusBadge, Tag, useApi } from "@/components/ui";

function err(p: number | null | undefined, a: number | null | undefined) {
  return p == null || a == null ? null : p - a;
}

export default function PastPage() {
  const { data, error, loading } = useApi<EventSummary[]>("/api/events?scope=past");
  return (
    <div className="space-y-4">
      <h1 className="text-lg font-bold">過去の経済指標</h1>
      <p className="text-xs text-muted">会話由来の記録は公式データとの照合前のため「未検証」です。最大変動幅（5分間）と終着地（5分後）は別項目として表示しています。</p>
      {!data ? <Loading error={error} loading={loading} /> : (
        <div className="card p-0 overflow-x-auto">
          <table className="tbl">
            <thead>
              <tr>
                <th>発表日</th><th>指標</th><th>状態</th><th>予測方向</th><th>実際の方向</th>
                <th>予測最大変動幅</th><th>実際の最大変動幅</th><th>予測5分後</th><th>実際の5分後</th><th>5分後誤差</th>
                <th className="min-w-[260px]">AIによる反省</th><th className="min-w-[240px]">次回への改善点</th>
              </tr>
            </thead>
            <tbody>
              {data.map((e) => {
                const f = e.latest_forecast;
                const o = e.outcome;
                const rep = e.report ?? e.conversation_report;
                const refl = [...(e.conversation_report?.reflections ?? []), ...(e.report?.hypotheses ?? []).map((h) => h.text)];
                const imp = Array.from(new Set([...(e.conversation_report?.improvements ?? []), ...(e.report?.improvements ?? [])]));
                const d5e = err(f?.d5, o?.d5);
                const actualDir = o?.direction_5m ?? o?.observed_direction;
                return (
                  <tr key={e.id} className="align-top hover:bg-panel2/50">
                    <td className="num text-xs">{e.release_at ? fmtJst(e.release_at) : e.date_label}</td>
                    <td className="whitespace-normal min-w-[180px]">
                      <Link href={`/events/${e.id}`} className="hover:text-gold font-medium">{e.title}</Link>
                      <div className="mt-1 flex gap-1"><CategoryLabel c={e.category} />{o && !o.verified && <Tag tone="red">未検証</Tag>}</div>
                    </td>
                    <td><StatusBadge status={e.status} label={e.status_ja} /></td>
                    <td><Dir d={f?.dominant_direction} /></td>
                    <td><Dir d={actualDir} />{o && !o.direction_5m && o.observed_direction && <div className="text-[10px] text-muted">時間幅不明</div>}</td>
                    <td className="num">{f?.max_excursion_5m != null ? `${f.max_excursion_5m}` : "—"}</td>
                    <td className="num">{o?.max_excursion_5m ?? (o?.max_down_5m != null || o?.max_up_5m != null ? <span title="片方向のみ記録">上{o?.max_up_5m ?? "?"}/下{o?.max_down_5m ?? "?"}</span> : "—")}</td>
                    <td className="num">{usd(f?.d5)}</td>
                    <td className="num">{usd(o?.d5)}</td>
                    <td className="num">{d5e == null ? "—" : usd(d5e)}</td>
                    <td className="whitespace-normal text-xs">
                      {rep?.summary && <div className="text-slate-300 mb-1">{e.report?.summary}</div>}
                      <ul className="list-disc pl-4 space-y-0.5 text-muted">{refl.slice(0, 4).map((r, i) => <li key={i}>{r}</li>)}</ul>
                    </td>
                    <td className="whitespace-normal text-xs"><ul className="list-disc pl-4 space-y-0.5">{imp.slice(0, 3).map((r, i) => <li key={i}>{r}</li>)}</ul></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
