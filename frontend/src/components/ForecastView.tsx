"use client";
import type { Forecast, Indicator } from "@/lib/api";
import { SOURCE_JA, fmtJst, pct, usd } from "@/lib/format";
import { Dir, ProbBar, Tag } from "./ui";

const THRESHOLDS = [10, 15, 20, 30, 50, 70, 100];
const HORIZONS = [1, 5, 15, 30, 60] as const;

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border-t border-line pt-3 mt-3">
      <div className="text-xs font-semibold text-gold mb-2">{title}</div>
      {children}
    </div>
  );
}

function KV({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-3 text-sm py-0.5">
      <span className="text-muted">{k}</span>
      <span className="num text-right">{v}</span>
    </div>
  );
}

export function ReachTable({ reach }: { reach: Forecast["reach_probs"] }) {
  const rows = THRESHOLDS.filter((t) => reach?.[String(t)]);
  if (!rows.length) return <div className="text-muted text-sm">記録なし</div>;
  return (
    <div className="overflow-x-auto">
      <table className="tbl">
        <thead><tr><th>値幅</th><th>上方向</th><th>下方向</th><th>どちらか</th><th>両方向</th></tr></thead>
        <tbody>
          {rows.map((t) => {
            const r = reach[String(t)];
            return (
              <tr key={t} className="num">
                <td>{t}ドル</td>
                <td className="text-up">{pct(r.up)}</td>
                <td className="text-down">{pct(r.down)}</td>
                <td>{pct(r.either)}</td>
                <td>{pct(r.both)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function ForecastView({ f, indicators }: { f: Forecast; indicators: Indicator[] }) {
  const ms = f.market_snapshot || {};
  const base = typeof ms.price === "number" ? (ms.price as number) : null;
  const indByCode = Object.fromEntries(indicators.map((i) => [i.code, i]));
  const msEntries = Object.entries(ms).filter(([k]) => k !== "training_event_ids");

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
        <Tag tone="gold">Ver.{f.version_no}</Tag>
        <span className="text-slate-200 font-medium">{f.label}</span>
        <Tag>{SOURCE_JA[f.source] ?? f.source}</Tag>
        <span>モデル: {f.model_name} v{f.model_version}</span>
        <span>予測時点: {f.as_of ? fmtJst(f.as_of) : f.as_of_label ?? "—"}</span>
        <span>登録: {fmtJst(f.created_at)}</span>
      </div>
      {f.change_summary && <div className="text-xs mt-2 text-sky-300">変更点: {f.change_summary}</div>}
      {f.warnings?.length > 0 && (
        <ul className="text-xs mt-2 text-orange-300 list-disc pl-5">{f.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
      )}

      <Section title="4-1 現在の市場状況">
        {msEntries.length ? (
          <div className="grid sm:grid-cols-2 gap-x-6">{msEntries.map(([k, v]) => <KV key={k} k={k} v={String(v)} />)}</div>
        ) : <div className="text-muted text-sm">記録なし</div>}
        {f.news_used?.length > 0 && (
          <ul className="mt-2 text-sm space-y-1">
            {f.news_used.map((n, i) => (
              <li key={i}>
                {n.url ? <a className="text-sky-300 underline" href={n.url} target="_blank" rel="noreferrer">{n.title}</a> : n.title}
                <span className="text-xs text-muted ml-2">{n.source} {n.published_at ? fmtJst(n.published_at) : ""}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="4-2 経済指標の数値予測">
        {f.indicator_forecasts?.length ? (
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead><tr><th>指標</th><th>前回</th><th>改定</th><th>市場予想</th><th>AI一点予想</th><th>予想との差</th><th>根拠・リスク</th></tr></thead>
              <tbody>
                {f.indicator_forecasts.map((x) => {
                  const ind = indByCode[x.code];
                  const diff = ind?.consensus != null && x.point != null ? x.point - ind.consensus : null;
                  return (
                    <tr key={x.code} className="num">
                      <td>{ind?.name ?? x.code}</td>
                      <td>{ind?.previous ?? "—"}</td>
                      <td>{ind?.previous_revised ?? "—"}</td>
                      <td>{ind?.consensus ?? "—"}</td>
                      <td className="text-gold">{x.point ?? "—"}{ind?.unit}</td>
                      <td>{diff == null ? "—" : `${diff > 0 ? "+" : ""}${Math.round(diff * 100) / 100}`}</td>
                      <td className="whitespace-normal text-xs text-muted">{[x.rationale, x.upside_risk && `上振れ: ${x.upside_risk}`, x.downside_risk && `下振れ: ${x.downside_risk}`].filter(Boolean).join(" / ") || "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : <div className="text-muted text-sm">記録なし</div>}
      </Section>

      <Section title="4-3 方向予測">
        <div className="grid sm:grid-cols-2 gap-4 items-center">
          <ProbBar f={f} />
          <div>
            <KV k="短期優勢方向" v={<Dir d={f.dominant_direction} />} />
            <KV k="重要度" v={f.importance ?? "—"} />
            <KV k="信頼度" v={pct(f.confidence)} />
          </div>
        </div>
      </Section>

      <Section title="4-4 発表後の終着地（発表直前価格からの差）">
        <div className="overflow-x-auto">
          <table className="tbl">
            <thead><tr>{HORIZONS.map((h) => <th key={h}>{h}分後</th>)}</tr></thead>
            <tbody>
              <tr className="num">{HORIZONS.map((h) => {
                const v = f[`d${h}` as "d1"];
                return <td key={h} className={v == null ? "text-muted" : v > 0 ? "text-up" : v < 0 ? "text-down" : ""}>
                  {usd(v)}{v != null && "ドル"}
                  {base != null && v != null && <div className="text-[11px] text-muted">{(base + v).toLocaleString()}ドル</div>}
                </td>;
              })}</tr>
            </tbody>
          </table>
        </div>
        {f.headline_move != null && (
          <div className="text-xs text-orange-300 mt-1">時間幅未指定の一点予想: {usd(f.headline_move)}ドル（終着地とは比較しない）</div>
        )}
      </Section>

      <Section title="4-5 発表後5分間の最大変動幅">
        <div className="grid sm:grid-cols-2 gap-x-6">
          <KV k="最大上昇幅" v={f.max_up_5m != null ? `${f.max_up_5m}ドル` : "—"} />
          <KV k="最大下落幅" v={f.max_down_5m != null ? `${f.max_down_5m}ドル` : "—"} />
          <KV k="上下どちらかへの最大到達幅（一点）" v={f.max_excursion_5m != null ? `${f.max_excursion_5m}ドル` : "—"} />
          <KV k="最大到達幅の予測区間" v={f.max_excursion_5m_low != null ? `${f.max_excursion_5m_low}〜${f.max_excursion_5m_high}ドル` : "—"} />
          <KV k="5分 高値−安値レンジ" v={f.range_5m != null ? `${f.range_5m}ドル` : "—"} />
        </div>
      </Section>

      <Section title="4-6 5分以内の到達確率">
        <ReachTable reach={f.reach_probs} />
      </Section>

      <Section title="4-7 上下への往復予測">
        <div className="grid sm:grid-cols-2 gap-x-6">
          <KV k="初動方向" v={<Dir d={f.initial_direction} />} />
          <KV k="初動の最大値幅" v={f.initial_move != null ? `${usd(f.initial_move)}ドル` : "—"} />
          <KV k="反転確率" v={pct(f.reversal_prob)} />
          <KV k="反転幅" v={f.reversal_size != null ? `${f.reversal_size}ドル` : "—"} />
          <KV k="5分レンジ" v={f.range_5m != null ? `${f.range_5m}ドル` : "—"} />
          <KV k="30分レンジ" v={f.range_30m != null ? `${f.range_30m}ドル` : "—"} />
          <KV k="60分レンジ" v={f.range_60m != null ? `${f.range_60m}ドル` : "—"} />
        </div>
      </Section>

      {(f.scenarios?.length > 0 || f.extras?.length > 0) && (
        <Section title="条件付きシナリオ・その他の記録">
          <ul className="text-sm space-y-1">
            {f.scenarios.map((s, i) => (
              <li key={`s${i}`}>
                <Tag>シナリオ</Tag> <span className="ml-1">{s.label}</span>
                {s.value && <span className="text-muted ml-2">{s.value}</span>}
              </li>
            ))}
            {f.extras.map((x, i) => (
              <li key={`x${i}`}><Tag>記録</Tag> <span className="ml-1">{x.label}: {x.value}</span></li>
            ))}
          </ul>
        </Section>
      )}
      {Object.keys(f.phase_analysis || {}).length > 0 && (
        <Section title="フェーズ別分析">
          <pre className="text-xs whitespace-pre-wrap text-muted">{JSON.stringify(f.phase_analysis, null, 2)}</pre>
        </Section>
      )}
      {f.rationale && <Section title="予測根拠"><p className="text-sm whitespace-pre-wrap">{f.rationale}</p></Section>}
    </div>
  );
}
