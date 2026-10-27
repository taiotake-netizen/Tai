"use client";
import Link from "next/link";
import { CATEGORY_JA, fmtJst, pct } from "@/lib/format";
import { Loading, Stat, Tag, useApi } from "@/components/ui";

interface Sum { direction_basis?: string; direction_by_horizon?: Record<string, { n: number; accuracy: number | null }>;
  direction_observed_reference?: { n: number; hits: number }; n_evaluations: number; direction_n: number; direction_accuracy: number | null; d5_mae: number | null; d5_n: number;
  d30_mae: number | null; max_excursion_mae: number | null; max_excursion_n: number; indicator_mae: number | null; indicator_n: number;
  brier_reach: number | null; brier_direction: number | null }
interface Block { overall: Sum; by_category: Record<string, Sum>; by_model: Record<string, Sum>; calibration: { bin: string; n: number; mean_prob: number; hit_rate: number }[] }
interface Acc { confirmed: Block; tentative: Block; notice: string;
  history: { event_id: number; event: string; release_at: string | null; version_no: number; label: string; model: string; verified: boolean; outcome_kind: string; direction_hit: boolean | null; d5_abs_error: number | null; excursion_abs_error: number | null; brier_reach: number | null }[] }
interface Model { id: number; name: string; version: string; scope: string; kind: string; status: string; description: string; backtest: Record<string, unknown>; adopted_at: string | null }

function SumTable({ rows }: { rows: Record<string, Sum> }) {
  const keys = Object.keys(rows);
  if (!keys.length) return <div className="text-sm text-muted">データなし</div>;
  return (
    <div className="overflow-x-auto"><table className="tbl">
      <thead><tr><th></th><th>評価数</th><th>方向正答率(5分)</th><th>5分後MAE</th><th>30分後MAE</th><th>最大変動幅MAE</th><th>指標数値MAE</th><th>Brier(到達)</th><th>Brier(方向)</th></tr></thead>
      <tbody>{keys.map((k) => { const s = rows[k]; return (
        <tr key={k} className="num"><td>{CATEGORY_JA[k] ?? k}</td><td>{s.n_evaluations}</td><td>{pct(s.direction_accuracy)} <span className="text-muted text-[10px]">n={s.direction_n}</span></td>
          <td>{s.d5_mae ?? "—"}</td><td>{s.d30_mae ?? "—"}</td><td>{s.max_excursion_mae ?? "—"}</td><td>{s.indicator_mae ?? "—"}</td><td>{s.brier_reach ?? "—"}</td><td>{s.brier_direction ?? "—"}</td></tr>); })}</tbody>
    </table></div>
  );
}

function BlockView({ b, title, tone }: { b: Block; title: string; tone: "green" | "red" }) {
  const o = b.overall;
  return (
    <section className="card space-y-4">
      <div className="card-title"><Tag tone={tone}>{title}</Tag></div>
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2">
        <Stat label="方向正答率（5分後基準）" value={pct(o.direction_accuracy)} sub={`n=${o.direction_n}`} />
        <Stat label="5分後終着地MAE" value={o.d5_mae ?? "—"} sub={`ドル n=${o.d5_n}`} />
        <Stat label="最大変動幅MAE" value={o.max_excursion_mae ?? "—"} sub={`ドル n=${o.max_excursion_n}`} />
        <Stat label="指標数値の予測誤差" value={o.indicator_mae ?? "—"} sub={`MAE n=${o.indicator_n}`} />
        <Stat label="到達確率Brier" value={o.brier_reach ?? "—"} sub="0に近いほど良い" />
        <Stat label="方向確率Brier" value={o.brier_direction ?? "—"} sub="3クラス" />
        <Stat label="評価数" value={o.n_evaluations} sub="主評価=最終版" />
      </div>
      <div>
        <div className="text-xs font-semibold mb-1">時間幅別の方向正答率</div>
        <div className="overflow-x-auto"><table className="tbl">
          <thead><tr>{["1", "5", "15", "30", "60"].map((n) => <th key={n}>{n}分後</th>)}</tr></thead>
          <tbody><tr className="num">{["1", "5", "15", "30", "60"].map((n) => { const h = o.direction_by_horizon?.[n]; return <td key={n}>{pct(h?.accuracy)} <span className="text-[10px] text-muted">n={h?.n ?? 0}</span></td>; })}</tr></tbody>
        </table></div>
        <p className="text-[11px] text-muted mt-1">判定: 発表直前価格からの各時点の価格差。{o.direction_basis ?? ""}。予測の「短期優勢方向」を各時点の実際の方向と比較しています。
          {o.direction_observed_reference && o.direction_observed_reference.n > 0 && ` 時間幅不明の記録との比較 ${o.direction_observed_reference.hits}/${o.direction_observed_reference.n} 件一致（参考・正答率に含めない）。`}</p>
      </div>
      <div><div className="text-xs font-semibold mb-1">指標別の成績</div><SumTable rows={b.by_category} /></div>
      <div><div className="text-xs font-semibold mb-1">モデル別の成績</div><SumTable rows={b.by_model} /></div>
      <div>
        <div className="text-xs font-semibold mb-1">予測確率の校正（到達確率）</div>
        {b.calibration.length === 0 ? <div className="text-sm text-muted">データなし</div> : (
          <div className="space-y-1">{b.calibration.map((c) => (
            <div key={c.bin} className="flex items-center gap-2 text-xs num">
              <span className="w-16">{c.bin}</span>
              <div className="flex-1 h-3 bg-line rounded relative">
                <div className="absolute h-3 bg-sky-500/60 rounded" style={{ width: `${c.hit_rate}%` }} />
                <div className="absolute h-3 w-0.5 bg-gold" style={{ left: `${c.mean_prob}%` }} />
              </div>
              <span className="w-40">予測{c.mean_prob}% / 実際{c.hit_rate}% (n={c.n})</span>
            </div>
          ))}<div className="text-[10px] text-muted">金線=平均予測確率、青=実際の到達率。一致するほど校正が良い。</div></div>
        )}
      </div>
    </section>
  );
}

export default function AccuracyPage() {
  const { data, error, loading } = useApi<Acc>("/api/accuracy");
  const models = useApi<Model[]>("/api/models");
  if (!data) return <Loading error={error} loading={loading} />;
  return (
    <div className="space-y-4">
      <h1 className="text-lg font-bold">予測精度ダッシュボード</h1>
      <p className="text-xs text-muted">{data.notice}</p>
      <BlockView b={data.confirmed} title="確定（価格データで検証済み）" tone="green" />
      <BlockView b={data.tentative} title="暫定（会話由来・未照合の参考値）" tone="red" />
      <section className="card">
        <div className="card-title">予測の改善履歴（イベント×バージョン）</div>
        <div className="overflow-x-auto"><table className="tbl">
          <thead><tr><th>発表</th><th>イベント</th><th>Ver.</th><th>モデル</th><th>実績</th><th>方向</th><th>5分後誤差</th><th>最大到達幅誤差</th><th>Brier(到達)</th></tr></thead>
          <tbody>{data.history.map((h, i) => (
            <tr key={i} className="num">
              <td className="text-xs">{fmtJst(h.release_at)}</td>
              <td><Link className="hover:text-gold" href={`/events/${h.event_id}`}>{h.event}</Link></td>
              <td>Ver.{h.version_no} <span className="text-[10px] text-muted">{h.label}</span></td>
              <td className="text-xs">{h.model}</td>
              <td>{h.verified ? <Tag tone="green">検証済み</Tag> : <Tag tone="red">未検証</Tag>}</td>
              <td>{h.direction_hit == null ? "—" : h.direction_hit ? <span className="text-up">的中</span> : <span className="text-down">外れ</span>}</td>
              <td>{h.d5_abs_error ?? "—"}</td><td>{h.excursion_abs_error ?? "—"}</td><td>{h.brier_reach ?? "—"}</td>
            </tr>
          ))}</tbody>
        </table></div>
      </section>
      <section className="card">
        <div className="card-title">モデル登録簿</div>
        <p className="text-xs text-muted mb-2">改善モデルは、時系列バックテストで未使用データでも精度が改善した場合のみ採用します（Phase 4）。根拠となる数値がない限り改善を宣言しません。</p>
        <ul className="text-sm space-y-1">{(models.data ?? []).map((m) => (
          <li key={m.id} className="flex flex-wrap gap-2 items-center"><span className="font-medium">{m.name} v{m.version}</span><Tag>{m.kind}</Tag><Tag tone={m.status === "active" ? "green" : "slate"}>{m.status}</Tag><span className="text-xs text-muted">{m.description}</span></li>
        ))}</ul>
      </section>
    </div>
  );
}
