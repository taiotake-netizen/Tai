"use client";
import Link from "next/link";
import { use, useMemo, useState } from "react";
import { api, errorText, type Evaluation, type EventDetail, type Indicator, type Outcome } from "@/lib/api";
import { dirJa, fmtJst, pct, usd } from "@/lib/format";
import ForecastView from "@/components/ForecastView";
import ForecastForm from "@/components/ForecastForm";
import PriceChart from "@/components/PriceChart";
import { CategoryLabel, Dir, Importance, Loading, StatusBadge, Tag, Unverified, useApi } from "@/components/ui";

function IndicatorRow({ i, released, onSaved }: { i: Indicator; released: boolean; onSaved: () => void }) {
  const [edit, setEdit] = useState(false);
  const [v, setV] = useState({
    previous: i.previous ?? "", previous_revised: i.previous_revised ?? "", consensus: i.consensus ?? "",
    consensus_source: i.consensus_source ?? "", actual: i.actual ?? "", actual_source: i.actual_source ?? "",
    actual_verified: i.actual_verified,
  });
  const [err, setErr] = useState<string | null>(null);
  const n = (x: string | number) => (x === "" ? null : Number(x));
  async function save() {
    setErr(null);
    const body: Record<string, unknown> = {
      previous: n(v.previous), previous_revised: n(v.previous_revised), consensus: n(v.consensus),
      consensus_source: v.consensus_source || null,
    };
    if (released) Object.assign(body, { actual: n(v.actual), actual_source: v.actual_source || null, actual_verified: v.actual_verified });
    try {
      await api(`/api/indicators/${i.id}`, { method: "PATCH", body: JSON.stringify(body) });
      setEdit(false);
      onSaved();
    } catch (e) { setErr(errorText(e)); }
  }
  if (!edit)
    return (
      <tr className="num">
        <td>{i.name}<div className="text-[10px] text-muted">{i.code}</div></td>
        <td>{i.previous ?? "—"}</td><td>{i.previous_revised ?? "—"}</td>
        <td>{i.consensus ?? "—"}{i.consensus_source && <div className="text-[10px] text-muted whitespace-normal max-w-[180px]">{i.consensus_source}</div>}</td>
        <td className="text-gold">{i.actual ?? "—"}{i.actual != null && i.unit}</td>
        <td>{i.actual != null ? <Unverified verified={i.actual_verified} /> : "—"}<div className="text-[10px] text-muted whitespace-normal max-w-[180px]">{i.actual_source}</div></td>
        <td><button className="btn" onClick={() => setEdit(true)}>編集</button></td>
      </tr>
    );
  const inp = (k: keyof typeof v, type = "number") => (
    <input className="input num w-24" type={type} step="any" value={v[k] as string | number}
      onChange={(e) => setV((p) => ({ ...p, [k]: e.target.value }))} />
  );
  return (
    <tr className="align-top">
      <td>{i.name}</td><td>{inp("previous")}</td><td>{inp("previous_revised")}</td>
      <td>{inp("consensus")}<div className="mt-1">{inp("consensus_source", "text")}</div></td>
      <td>{released ? inp("actual") : <span className="text-xs text-muted">発表後に入力</span>}</td>
      <td className="whitespace-normal">
        {released && <>
          <input className="input w-40" placeholder="出所（例: BLS発表）" value={v.actual_source}
            onChange={(e) => setV((p) => ({ ...p, actual_source: e.target.value }))} />
          <label className="text-xs flex items-center gap-1 mt-1"><input type="checkbox" checked={v.actual_verified}
            onChange={(e) => setV((p) => ({ ...p, actual_verified: e.target.checked }))} />公式データと照合済み</label>
        </>}
        {err && <div className="text-xs text-down mt-1">{err}</div>}
      </td>
      <td className="space-x-1"><button className="btn btn-gold" onClick={save}>保存</button><button className="btn" onClick={() => setEdit(false)}>取消</button></td>
    </tr>
  );
}

function OutcomeCard({ o }: { o: Outcome }) {
  const rows: [string, React.ReactNode][] = [
    ["発表直前価格", o.base_price != null ? `${o.base_price.toLocaleString()}ドル` : "—"],
    ...([1, 5, 15, 30, 60] as const).map((n) => [`${n}分後終着地`, usd(o[`d${n}` as "d1"])] as [string, React.ReactNode]),
    ["5分 最高値 / 最安値", `${o.high_5m ?? "—"} / ${o.low_5m ?? "—"}`],
    ["5分 最大上昇幅 / 最大下落幅", `${o.max_up_5m ?? "—"} / ${o.max_down_5m ?? "—"}`],
    ["5分 最大到達幅", o.max_excursion_5m ?? "—"],
    ["高値安値レンジ 5/30/60分", `${o.range_5m ?? "—"} / ${o.range_30m ?? "—"} / ${o.range_60m ?? "—"}`],
    ["5分後の方向", <Dir key="d" d={o.direction_5m} />],
    ["初動", <span key="i"><Dir d={o.initial_direction} /> {o.initial_move != null && usd(o.initial_move)}</span>],
    ["反転", o.reversed == null ? "—" : o.reversed ? `あり（${o.reversal_size}ドル戻し）` : "なし"],
  ];
  if (o.headline_move != null) rows.push(["観測値動き（時間幅不明）", usd(o.headline_move)]);
  if (o.observed_direction) rows.push(["観測方向（時間幅不明）", <Dir key="o" d={o.observed_direction} />]);
  return (
    <div className="bg-panel2 border border-line rounded-lg p-3">
      <div className="flex flex-wrap items-center gap-2 mb-2">
        <Tag tone={o.kind === "price_bars" ? "gold" : "slate"}>{o.kind === "price_bars" ? "価格データから算出" : "会話由来の記録"}</Tag>
        <Unverified verified={o.verified} />
        <span className="text-xs text-muted">{o.source}</span>
      </div>
      <div className="grid sm:grid-cols-2 gap-x-6">
        {rows.map(([k, val]) => (
          <div key={k} className="flex justify-between text-sm py-0.5"><span className="text-muted">{k}</span><span className="num">{val}</span></div>
        ))}
      </div>
      {o.observations?.length > 0 && (
        <ul className="text-sm mt-2 list-disc pl-5">{o.observations.map((x, i) => <li key={i}>{x.label}: {x.value}</li>)}</ul>
      )}
      {Object.keys(o.related_markets || {}).length > 0 && (
        <div className="text-xs mt-2">関連市場: {Object.entries(o.related_markets).map(([s, m]) => `${s} 5分 ${usd(m.d5 ?? null)} / 60分 ${usd(m.d60 ?? null)}`).join("　")}</div>
      )}
      {o.missing?.length > 0 && <div className="text-xs text-orange-300 mt-2">欠損: {o.missing.join("、")}</div>}
      {o.notes && <div className="text-xs text-muted mt-1">{o.notes}</div>}
    </div>
  );
}

function EvalTable({ ev, evals }: { ev: EventDetail; evals: Evaluation[] }) {
  const byOutcome = useMemo(() => {
    const m = new Map<number, Evaluation[]>();
    evals.forEach((e) => m.set(e.outcome_id, [...(m.get(e.outcome_id) ?? []), e]));
    return m;
  }, [evals]);
  if (!evals.length) return <div className="text-sm text-muted">比較できる予測と実績の組み合わせがありません。</div>;
  return (
    <div className="space-y-4">
      {ev.outcomes.map((o) => {
        const list = (byOutcome.get(o.id) ?? []).sort((a, b) =>
          (ev.forecasts.find((f) => f.id === a.forecast_id)?.version_no ?? 0) - (ev.forecasts.find((f) => f.id === b.forecast_id)?.version_no ?? 0));
        if (!list.length) return null;
        return (
          <div key={o.id}>
            <div className="text-xs mb-1 flex gap-2 items-center">対象の実績: <Tag>{o.kind === "price_bars" ? "価格データ" : "会話記録"}</Tag><Unverified verified={o.verified} /></div>
            <div className="overflow-x-auto">
              <table className="tbl">
                <thead><tr><th>Ver.</th><th>方向</th><th>Brier(方向)</th><th>1分後誤差</th><th>5分後誤差</th><th>30分後誤差</th><th>最大到達幅誤差</th><th>Brier(到達)</th><th>指標数値の誤差</th><th>その他</th></tr></thead>
                <tbody>
                  {list.map((e) => {
                    const f = ev.forecasts.find((x) => x.id === e.forecast_id)!;
                    const m = e.metrics;
                    const errCell = (k: string) => m[k] ? <span className={Math.abs(m[k].error) <= 5 ? "text-up" : ""}>{usd(m[k].error)}</span> : "—";
                    return (
                      <tr key={e.id} className="num align-top">
                        <td>Ver.{f.version_no}<div className="text-[10px] text-muted">{f.label}</div></td>
                        <td>{m.direction ? <span className={m.direction.hit ? "text-up" : "text-down"}>{m.direction.hit ? "的中" : "外れ"}<div className="text-[10px] text-muted">{dirJa(m.direction.pred)}→{dirJa(m.direction.actual)}</div></span> : "—"}</td>
                        <td>{m.brier_direction ?? "—"}</td>
                        <td>{errCell("d1")}</td><td>{errCell("d5")}</td><td>{errCell("d30")}</td>
                        <td>{m.max_excursion_5m ? <>{usd(m.max_excursion_5m.error)}<div className="text-[10px] text-muted">{m.excursion_bias}</div></> : "—"}</td>
                        <td>{m.brier_reach_mean ?? "—"}</td>
                        <td className="whitespace-normal text-xs">{(m.indicators ?? []).map((r: any) => (
                          <div key={r.code}>{r.name}: {r.error > 0 ? "+" : ""}{Math.round(r.error * 100) / 100}{r.unit}{!r.actual_verified && <span className="text-orange-300">（実績未照合）</span>}</div>
                        ))}</td>
                        <td className="whitespace-normal text-xs max-w-[280px]">
                          {m.headline_move && <div>時間幅未指定の一点予想との差 {usd(m.headline_move.error)}ドル（比較不可・参考）</div>}
                          {(m.scenarios ?? []).map((s: any, i: number) => (
                            <div key={i}>シナリオ「{s.label}」: {s.triggered ? (s.reaction_in_range == null ? "成立" : `成立・反応${s.reaction_in_range ? "範囲内" : "範囲外"}`) : "不成立"}</div>
                          ))}
                          {m.reversal && <div>反転確率{pct(m.reversal.prob)} → {m.reversal.reversed ? "反転あり" : "反転なし"}</div>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {list[0]?.notes?.length > 0 && <ul className="text-[11px] text-muted mt-1 list-disc pl-5">{Array.from(new Set(list.flatMap((e) => e.notes))).map((n, i) => <li key={i}>{n}</li>)}</ul>}
          </div>
        );
      })}
    </div>
  );
}

export default function EventPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: ev, error, loading, reload } = useApi<EventDetail>(`/api/events/${id}`);
  const bars = useApi<{ bars: any[]; timeframe_min: number | null }>(`/api/events/${id}/bars`);
  const [sel, setSel] = useState<number | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!ev) return <Loading error={error} loading={loading} />;
  const released = !ev.release_at || new Date(ev.release_at).getTime() <= Date.now();
  const fv = ev.forecasts.find((f) => f.version_no === sel) ?? ev.forecasts[ev.forecasts.length - 1];
  const latestReport = [...ev.reports].reverse().find((r) => r.generated_by !== "conversation_import");
  const convReport = ev.reports.find((r) => r.generated_by === "conversation_import");
  const priceOutcome = ev.outcomes.find((o) => o.kind === "price_bars");

  async function action(path: string, okMsg: (r: any) => string) {
    setBusy(true); setMsg(null);
    try {
      const r = await api<any>(path, { method: "POST" });
      setMsg(okMsg(r));
      await reload(); await bars.reload();
    } catch (e) { setMsg(errorText(e)); } finally { setBusy(false); }
  }

  return (
    <div className="space-y-4">
      <section className="card">
        <div className="flex flex-wrap items-center gap-2">
          {ev.categories.map((c) => <CategoryLabel key={c} c={c} />)}
          <StatusBadge status={ev.status} label={ev.status_ja} />
          {ev.is_composite && <Tag>複合イベント</Tag>}
          {ev.origin === "conversation" && <Tag tone="red">会話由来・未照合</Tag>}
          {ev.release_time_confirmed ? <Tag tone="green">公式日程で確認済み</Tag> : <Tag tone="red">時刻未確定</Tag>}
        </div>
        <h1 className="text-xl font-bold mt-2">{ev.title}</h1>
        <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm mt-1">
          <span className="num">{ev.release_at ? `${fmtJst(ev.release_at)}（日本時間）` : ev.date_label}</span>
          <Importance value={ev.importance} />
          {ev.cluster && <span className="text-muted">関連: {ev.cluster}</span>}
        </div>
        {ev.date_label && ev.release_at && <div className="text-xs text-muted mt-1">日付表記: {ev.date_label}</div>}
        {ev.notes && <p className="text-xs text-muted mt-2">{ev.notes}</p>}
        {ev.schedule_sources?.length > 0 && (
          <div className="text-[11px] text-muted mt-1">日程の根拠: {ev.schedule_sources.map((s, i) => (
            <a key={i} href={s.url} target="_blank" rel="noreferrer" className="text-sky-300 underline mr-3">{s.name}</a>
          ))}</div>
        )}
        {ev.parent && <div className="text-xs mt-2">親イベント: <Link className="text-sky-300" href={`/events/${ev.parent.id}`}>{ev.parent.title}</Link></div>}
        {ev.children.length > 0 && <div className="text-xs mt-2">関連する子イベント: {ev.children.map((c) => <Link key={c.id} className="text-sky-300 mr-3" href={`/events/${c.id}`}>{c.title}（{fmtJst(c.release_at, false)}）</Link>)}</div>}
        <div className="flex flex-wrap gap-2 mt-3">
          {!released && <button className="btn btn-gold" onClick={() => setShowForm((s) => !s)}>{showForm ? "入力を閉じる" : "＋ 新しい予測バージョン"}</button>}
          {!released && <button className="btn" disabled={busy} onClick={() => action(`/api/events/${ev.id}/forecasts/ai`, (r) => `AI予測 Ver.${r.version_no} を作成しました`)}>{busy ? "処理中…（AI予測は1〜2分かかります）" : "AI予測を作成"}</button>}
          {!released && <button className="btn" disabled={busy} onClick={() => action(`/api/events/${ev.id}/forecasts/baseline`, (r) => `統計ベースライン Ver.${r.version_no} を作成しました`)}>統計ベースライン予測を作成</button>}
          {released && ev.release_at && !priceOutcome?.verified && <button className="btn" disabled={busy} onClick={() => action(`/api/events/${ev.id}/prices/fetch`, (r) => `価格データ ${r.inserted}本を追加。検証結果: ${r.verification.result}`)}>価格データをAPIから取得</button>}
          {released && ev.release_at && <button className="btn btn-gold" disabled={busy} onClick={() => action(`/api/events/${ev.id}/verify`, (r) => `検証結果: ${r.result}${r.missing?.length ? `（不足: ${r.missing.join("、")}）` : ""}`)}>検証を実行</button>}
        </div>
        {msg && <div className="text-sm mt-2 whitespace-pre-wrap text-sky-300">{msg}</div>}
      </section>

      {showForm && <section className="card"><div className="card-title">新しい予測バージョン</div><ForecastForm ev={ev} onSaved={() => { setShowForm(false); reload(); }} /></section>}

      {ev.indicators.length > 0 && (
        <section className="card">
          <div className="card-title">経済指標の数値（個別管理）</div>
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead><tr><th>指標</th><th>前回値</th><th>前回改定値</th><th>市場予想</th><th>実績</th><th>照合</th><th></th></tr></thead>
              <tbody>{ev.indicators.map((i) => <IndicatorRow key={i.id} i={i} released={released} onSaved={reload} />)}</tbody>
            </table>
          </div>
        </section>
      )}

      <section className="card">
        <div className="card-title">事前予測（バージョン履歴・上書きなし）</div>
        {ev.forecasts.length === 0 ? <div className="text-sm text-muted">事前予測の記録はありません。</div> : (
          <>
            <div className="overflow-x-auto mb-3">
              <table className="tbl">
                <thead><tr><th>Ver.</th><th>名称</th><th>上/横/下</th><th>5分後</th><th>30分後</th><th>最大到達幅</th><th>5/30/60分レンジ</th><th>出所</th></tr></thead>
                <tbody>
                  {ev.forecasts.map((f) => (
                    <tr key={f.id} onClick={() => setSel(f.version_no)} className={`num cursor-pointer ${fv?.id === f.id ? "bg-panel2" : "hover:bg-panel2/50"}`}>
                      <td>Ver.{f.version_no}</td><td>{f.label}</td>
                      <td>{pct(f.prob_up)} / {pct(f.prob_flat)} / {pct(f.prob_down)}</td>
                      <td>{usd(f.d5)}</td><td>{usd(f.d30)}</td><td>{f.max_excursion_5m ?? "—"}</td>
                      <td>{f.range_5m ?? "—"} / {f.range_30m ?? "—"} / {f.range_60m ?? "—"}</td>
                      <td className="text-xs">{f.as_of_label ?? fmtJst(f.as_of ?? f.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {fv && <ForecastView f={fv} indicators={ev.indicators} />}
          </>
        )}
      </section>

      {ev.release_at && (
        <section className="card">
          <div className="card-title">XAUUSD 値動き（発表前60分〜発表後120分）{bars.data?.timeframe_min && <Tag>{bars.data.timeframe_min}分足</Tag>}</div>
          <PriceChart bars={bars.data?.bars ?? []} releaseAt={ev.release_at} basePrice={priceOutcome?.base_price} />
        </section>
      )}

      {released && (
        <section className="card">
          <div className="card-title">発表後の実績</div>
          {ev.outcomes.length === 0 ? <div className="text-sm text-muted">実績データはまだありません（データ待ち）。</div> : (
            <div className="grid lg:grid-cols-2 gap-3">{ev.outcomes.map((o) => <OutcomeCard key={o.id} o={o} />)}</div>
          )}
        </section>
      )}

      {released && ev.evaluations.length > 0 && (
        <section className="card">
          <div className="card-title">予測と実績の比較（全バージョン）</div>
          <EvalTable ev={ev} evals={ev.evaluations} />
        </section>
      )}

      {(latestReport || convReport) && (
        <section className="card">
          <div className="card-title">検証レポート</div>
          {latestReport && (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                {latestReport.tentative ? <Tag tone="red">暫定</Tag> : <Tag tone="green">確定</Tag>}
                <Tag>{latestReport.generated_by}</Tag><span className="text-muted">{fmtJst(latestReport.created_at)}</span>
              </div>
              <div className="font-medium">{latestReport.summary}</div>
              <div className="grid lg:grid-cols-3 gap-4">
                <div>
                  <div className="text-xs font-semibold text-up mb-1">確認できた事実</div>
                  <ul className="text-sm space-y-1">{latestReport.confirmed_facts.map((f, i) => (
                    <li key={i} className="flex gap-2"><span className={`mt-1.5 h-1.5 w-1.5 rounded-full shrink-0 ${f.verified ? "bg-up" : "bg-orange-400"}`} title={f.verified ? "検証済み" : "未照合"} /><span>{f.text}</span></li>
                  ))}</ul>
                  <div className="text-[10px] text-muted mt-1">● 緑=検証済み ● 橙=未照合の記録</div>
                </div>
                <div>
                  <div className="text-xs font-semibold text-gold mb-1">AIの仮説</div>
                  <ul className="text-sm space-y-1 list-disc pl-4">{latestReport.hypotheses.map((h, i) => <li key={i}>{h.text}{h.by && <span className="text-[10px] text-muted ml-1">({h.by})</span>}</li>)}</ul>
                </div>
                <div>
                  <div className="text-xs font-semibold text-sky-300 mb-1">次回への改善点</div>
                  <ul className="text-sm space-y-1 list-disc pl-4">{latestReport.improvements.map((h, i) => <li key={i}>{h}</li>)}</ul>
                </div>
              </div>
            </div>
          )}
          {convReport && (
            <div className="mt-4 border-t border-line pt-3">
              <div className="text-xs font-semibold mb-1">会話記録に残る反省（未検証）</div>
              <ul className="text-sm list-disc pl-4 space-y-0.5">{convReport.reflections.map((r, i) => <li key={i}>{r}</li>)}</ul>
              {convReport.improvements.length > 0 && <ul className="text-sm list-disc pl-4 space-y-0.5 mt-1 text-sky-300">{convReport.improvements.map((r, i) => <li key={i}>{r}</li>)}</ul>}
            </div>
          )}
        </section>
      )}

      {ev.similar_events.length > 0 && (
        <section className="card">
          <div className="card-title">研究材料: 同カテゴリの過去イベント</div>
          <ul className="divide-y divide-line">{ev.similar_events.map((s) => (
            <li key={s.id} className="py-2 text-sm flex flex-wrap gap-x-4 items-center">
              <Link href={`/events/${s.id}`} className="hover:text-gold">{s.title}</Link>
              <StatusBadge status={s.status} label={s.status_ja} />
              <span className="text-xs text-muted">予測 <Dir d={s.latest_forecast?.dominant_direction} /> / 実際 <Dir d={s.outcome?.direction_5m ?? s.outcome?.observed_direction} /></span>
              {s.report && <span className="text-xs text-muted">{s.report.summary}</span>}
            </li>
          ))}</ul>
        </section>
      )}
    </div>
  );
}
