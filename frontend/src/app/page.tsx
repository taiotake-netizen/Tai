"use client";
import Link from "next/link";
import type { EventSummary, Forecast } from "@/lib/api";
import { fmtJst, pct, usd } from "@/lib/format";
import { CategoryLabel, Countdown, Dir, Importance, Loading, ProbBar, Stat, StatusBadge, Tag, useApi } from "@/components/ui";

interface Acc { n_evaluations: number; direction_n: number; direction_accuracy: number | null; d5_mae: number | null; d5_n: number;
  max_excursion_mae: number | null; brier_reach: number | null; indicator_mae: number | null }
interface Home {
  now: string; next_event: EventSummary | null; latest_forecast: (Forecast & { event_title: string }) | null;
  week_events: EventSummary[]; recent_results: EventSummary[];
  accuracy: { confirmed: Acc; tentative: Acc };
  research: { status_counts: Record<string, number>; reports: number; improvements: { event_id: number; text: string }[];
    models: { name: string; version: string; status: string; kind: string }[] };
  data: { coverage: { symbol: string; timeframe_min: number; bars: number; first: string; last: string }[];
    sources: { key: string; name: string; status: string }[]; last_job: { status: string; message: string; finished_at: string } | null };
}

export default function HomePage() {
  const { data, error, loading } = useApi<Home>("/api/home");
  if (!data) return <Loading error={error} loading={loading} />;
  const n = data.next_event;
  const f = n?.latest_forecast;
  return (
    <div className="space-y-4">
      <div className="grid lg:grid-cols-3 gap-4">
        <section className="card lg:col-span-2">
          <div className="card-title">次に発表される重要経済指標</div>
          {n ? (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <CategoryLabel c={n.category} />
                <StatusBadge status={n.status} label={n.status_ja} />
                {n.release_time_confirmed ? <Tag tone="green">公式日程</Tag> : <Tag tone="red">時刻未確定</Tag>}
              </div>
              <Link href={`/events/${n.id}`} className="text-xl sm:text-2xl font-bold hover:text-gold block">{n.title}</Link>
              <div className="flex flex-wrap items-end gap-x-6 gap-y-2">
                <div><div className="label">発表日時（日本時間）</div><div className="num">{fmtJst(n.release_at)}</div></div>
                <div><div className="label">発表まで</div><div className="text-3xl text-gold"><Countdown target={n.release_at!} /></div></div>
                <div><div className="label">重要度</div><Importance value={n.importance} /></div>
              </div>
              {f ? (
                <div className="grid sm:grid-cols-4 gap-3 pt-2">
                  <div className="sm:col-span-2 bg-panel2 rounded-lg p-3 border border-line">
                    <div className="label mb-2">最新AI予測 Ver.{f.version_no}（{f.label}）</div>
                    <ProbBar f={f} />
                  </div>
                  <Stat label="5分後終着地" value={<span className={f.d5 == null ? "" : f.d5 < 0 ? "text-down" : "text-up"}>{usd(f.d5)}</span>} sub="ドル（直前価格比）" />
                  <Stat label="5分最大到達幅" value={f.max_excursion_5m ?? "—"} sub="ドル（上下どちらか）" />
                </div>
              ) : <div className="text-sm text-muted">まだ事前予測がありません。</div>}
            </div>
          ) : <div className="text-muted text-sm">今後のイベントが登録されていません。</div>}
        </section>

        <section className="card">
          <div className="card-title">過去の予測精度</div>
          <div className="grid grid-cols-2 gap-2">
            <Stat label="方向正答率（確定）" value={pct(data.accuracy.confirmed.direction_accuracy)} sub={`n=${data.accuracy.confirmed.direction_n}`} />
            <Stat label="5分後MAE（確定）" value={data.accuracy.confirmed.d5_mae ?? "—"} sub={`ドル n=${data.accuracy.confirmed.d5_n}`} />
            <Stat label="方向正答率（暫定）" value={pct(data.accuracy.tentative.direction_accuracy)} sub={`会話記録 n=${data.accuracy.tentative.direction_n}`} />
            <Stat label="5分後MAE（暫定）" value={data.accuracy.tentative.d5_mae ?? "—"} sub={`ドル n=${data.accuracy.tentative.d5_n}`} />
          </div>
          <p className="text-[11px] text-muted mt-2">確定＝価格データで検証済み。暫定＝会話由来の未照合記録（参考値）。</p>
          <Link href="/accuracy" className="text-xs text-sky-300 mt-2 inline-block">ダッシュボードへ →</Link>
        </section>
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <section className="card">
          <div className="card-title">今週の経済指標</div>
          {data.week_events.length ? (
            <ul className="divide-y divide-line">
              {data.week_events.map((e) => (
                <li key={e.id} className="py-2 flex items-center gap-3">
                  <div className="text-xs text-muted num w-28 shrink-0">{fmtJst(e.release_at, false)}</div>
                  <Link href={`/events/${e.id}`} className="flex-1 hover:text-gold text-sm">{e.title}</Link>
                  <Importance value={e.importance} />
                </li>
              ))}
            </ul>
          ) : <div className="text-sm text-muted">今週の登録イベントはありません。</div>}
        </section>

        <section className="card">
          <div className="card-title">直近の予測結果</div>
          <ul className="divide-y divide-line">
            {data.recent_results.map((e) => {
              const lf = e.latest_forecast;
              const o = e.outcome;
              return (
                <li key={e.id} className="py-2">
                  <div className="flex items-center gap-2">
                    <Link href={`/events/${e.id}`} className="flex-1 hover:text-gold text-sm">{e.title}</Link>
                    <StatusBadge status={e.status} label={e.status_ja} />
                  </div>
                  <div className="text-xs text-muted mt-1 flex flex-wrap gap-x-4">
                    <span>予測: <Dir d={lf?.dominant_direction} /></span>
                    <span>実際: <Dir d={o?.direction_5m ?? o?.observed_direction} /></span>
                    {e.report && <span className="text-slate-300">{e.report.summary}</span>}
                  </div>
                </li>
              );
            })}
          </ul>
        </section>
      </div>

      <div className="grid lg:grid-cols-3 gap-4">
        <section className="card">
          <div className="card-title">最新AI予測</div>
          {data.latest_forecast ? (
            <div className="text-sm space-y-1">
              <Link href={`/events/${data.latest_forecast.event_id}`} className="hover:text-gold">{data.latest_forecast.event_title}</Link>
              <div className="text-xs text-muted">Ver.{data.latest_forecast.version_no} {data.latest_forecast.label} / {data.latest_forecast.model_name}</div>
              <ProbBar f={data.latest_forecast} />
            </div>
          ) : <div className="text-muted text-sm">予測なし</div>}
        </section>
        <section className="card">
          <div className="card-title">AIの研究・改善状況</div>
          <div className="text-xs text-muted mb-2">検証レポート {data.research.reports}件 / モデル {data.research.models.length}件</div>
          <div className="flex flex-wrap gap-1 mb-2">
            {Object.entries(data.research.status_counts).map(([k, v]) => <Tag key={k}>{k}: {v}</Tag>)}
          </div>
          <ul className="text-xs space-y-1 list-disc pl-4">
            {data.research.improvements.slice(0, 5).map((i, k) => <li key={k}><Link href={`/events/${i.event_id}`} className="hover:text-gold">{i.text}</Link></li>)}
          </ul>
        </section>
        <section className="card">
          <div className="card-title">データ取得状況</div>
          <ul className="text-xs space-y-1">
            {data.data.sources.map((s) => (
              <li key={s.key} className="flex justify-between gap-2">
                <span>{s.name}</span>
                <Tag tone={s.status.startsWith("利用中") || s.status.startsWith("自動") ? "green" : "slate"}>{s.status}</Tag>
              </li>
            ))}
          </ul>
          <div className="text-xs text-muted mt-2">
            {data.data.coverage.length ? data.data.coverage.map((c) => `${c.symbol} ${c.timeframe_min}分足 ${c.bars.toLocaleString()}本`).join(" / ") : "価格データ未取込"}
          </div>
          {data.data.last_job && <div className="text-[11px] text-muted mt-1">最終ジョブ: {data.data.last_job.status} {data.data.last_job.message} ({fmtJst(data.data.last_job.finished_at)})</div>}
        </section>
      </div>
    </div>
  );
}
