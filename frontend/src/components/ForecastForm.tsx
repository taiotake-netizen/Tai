"use client";
import { useState } from "react";
import { api, errorText, type EventDetail } from "@/lib/api";

const THRESHOLDS = [10, 15, 20, 30, 50, 70, 100];
const KINDS = [["up", "上"], ["down", "下"], ["either", "どちらか"], ["both", "両方"]] as const;
const NUMS: [string, string][] = [
  ["d1", "1分後"], ["d5", "5分後"], ["d15", "15分後"], ["d30", "30分後"], ["d60", "60分後"],
  ["max_up_5m", "最大上昇幅"], ["max_down_5m", "最大下落幅"], ["max_excursion_5m", "最大到達幅(一点)"],
  ["max_excursion_5m_low", "到達幅 区間下限"], ["max_excursion_5m_high", "到達幅 区間上限"],
  ["range_5m", "5分レンジ"], ["range_30m", "30分レンジ"], ["range_60m", "60分レンジ"],
  ["initial_move", "初動の最大値幅(符号付)"], ["reversal_prob", "反転確率%"], ["reversal_size", "反転幅"],
];
const MARKET: [string, string][] = [
  ["price", "XAUUSD直近価格"], ["trend", "直近トレンド"], ["m5", "5分足の分析"], ["m30", "30分足の分析"],
  ["us2y", "米2年債利回り"], ["us10y", "米10年債利回り"], ["dxy", "DXY"], ["levels", "重要な価格帯"],
  ["rate_pricing", "利上げ・利下げ織り込み"],
];

const num = (s: string) => (s.trim() === "" ? null : Number(s));

export default function ForecastForm({ ev, onSaved }: { ev: EventDetail; onSaved: () => void }) {
  const last = ev.forecasts[ev.forecasts.length - 1];
  const [v, setV] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = { label: "", model_name: "manual", model_version: "1", rationale: "" };
    if (last) {
      for (const k of ["prob_up", "prob_down", "prob_flat", ...NUMS.map((n) => n[0])])
        init[k] = (last as any)[k] != null ? String((last as any)[k]) : "";
      for (const t of THRESHOLDS) for (const [k] of KINDS) {
        const x = last.reach_probs?.[String(t)]?.[k];
        init[`r_${t}_${k}`] = x != null ? String(x) : "";
      }
    }
    return init;
  });
  const [news, setNews] = useState<{ title: string; url: string; source: string; published_at: string }[]>([]);
  const [errors, setErrors] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setV((p) => ({ ...p, [k]: e.target.value }));

  async function submit() {
    setSaving(true);
    setErrors(null);
    const market: Record<string, unknown> = {};
    for (const [k] of MARKET) if (v[`m_${k}`]) market[k] = k === "price" ? Number(v[`m_${k}`]) : v[`m_${k}`];
    const reach: Record<string, Record<string, number | null>> = {};
    for (const t of THRESHOLDS) {
      const row: Record<string, number | null> = {};
      for (const [k] of KINDS) if ((v[`r_${t}_${k}`] ?? "") !== "") row[k] = Number(v[`r_${t}_${k}`]);
      if (Object.keys(row).length) reach[String(t)] = row;
    }
    const body: Record<string, unknown> = {
      label: v.label || null, model_name: v.model_name || "manual", model_version: v.model_version || "1",
      market_snapshot: market, rationale: v.rationale || null,
      prob_up: num(v.prob_up ?? ""), prob_down: num(v.prob_down ?? ""), prob_flat: num(v.prob_flat ?? ""),
      importance: num(v.importance ?? ""), confidence: num(v.confidence ?? ""),
      initial_direction: v.initial_direction || null, reach_probs: reach,
      indicator_forecasts: ev.indicators.filter((i) => (v[`i_${i.code}`] ?? "") !== "")
        .map((i) => ({ code: i.code, point: Number(v[`i_${i.code}`]), rationale: v[`ir_${i.code}`] || null })),
      news_used: news.filter((n) => n.title).map((n) => ({
        title: n.title, url: n.url || null, source: n.source || "不明",
        published_at: n.published_at ? new Date(n.published_at).toISOString() : null,
      })),
    };
    for (const [k] of NUMS) body[k] = num(v[k] ?? "");
    try {
      await api(`/api/events/${ev.id}/forecasts`, { method: "POST", body: JSON.stringify(body) });
      onSaved();
    } catch (e) {
      setErrors(errorText(e));
    } finally {
      setSaving(false);
    }
  }

  const F = (k: string, label: string, type = "number") => (
    <label className="block" key={k}><span className="label">{label}</span>
      <input className="input num" type={type} step="any" value={v[k] ?? ""} onChange={set(k)} /></label>
  );

  return (
    <div className="space-y-4">
      <p className="text-xs text-muted">新しいバージョンとして保存されます（既存の予測は変更されません）。発表時刻を過ぎると保存できません。値は前バージョンから引き継いでいます。</p>
      <div className="grid sm:grid-cols-3 gap-3">
        {F("label", "バージョン名（例: 前日予測・直前予測）", "text")}
        {F("model_name", "モデル名", "text")}
        {F("model_version", "モデルバージョン", "text")}
      </div>
      <fieldset className="border border-line rounded-lg p-3">
        <legend className="text-xs text-gold px-1">4-1 現在の市場状況</legend>
        <div className="grid sm:grid-cols-3 gap-3">{MARKET.map(([k, l]) => F(`m_${k}`, l, k === "price" ? "number" : "text"))}</div>
        <div className="mt-3 space-y-2">
          <div className="label">使用したニュース（URLが不明な場合は空欄。捏造しないこと）</div>
          {news.map((n, i) => (
            <div key={i} className="grid sm:grid-cols-4 gap-2">
              {(["title", "url", "source", "published_at"] as const).map((k) => (
                <input key={k} className="input" placeholder={{ title: "見出し", url: "URL", source: "出所", published_at: "" }[k]}
                  type={k === "published_at" ? "datetime-local" : "text"} value={n[k]}
                  onChange={(e) => setNews((p) => p.map((x, j) => (j === i ? { ...x, [k]: e.target.value } : x)))} />
              ))}
            </div>
          ))}
          <button type="button" className="btn" onClick={() => setNews((p) => [...p, { title: "", url: "", source: "", published_at: "" }])}>＋ ニュース</button>
        </div>
      </fieldset>
      {ev.indicators.length > 0 && (
        <fieldset className="border border-line rounded-lg p-3">
          <legend className="text-xs text-gold px-1">4-2 経済指標の数値予測</legend>
          <div className="grid sm:grid-cols-2 gap-3">
            {ev.indicators.map((i) => (
              <div key={i.code} className="grid grid-cols-2 gap-2">
                {F(`i_${i.code}`, `${i.name}（${i.unit || "値"}）`)}
                {F(`ir_${i.code}`, "根拠", "text")}
              </div>
            ))}
          </div>
        </fieldset>
      )}
      <fieldset className="border border-line rounded-lg p-3">
        <legend className="text-xs text-gold px-1">4-3 方向予測（合計100%）</legend>
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
          {F("prob_up", "上昇%")}{F("prob_flat", "横ばい%")}{F("prob_down", "下落%")}
          {F("importance", "重要度(1-10)")}{F("confidence", "信頼度%")}
        </div>
      </fieldset>
      <fieldset className="border border-line rounded-lg p-3">
        <legend className="text-xs text-gold px-1">4-4〜4-7 終着地・最大変動幅・往復（ドル）</legend>
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
          {NUMS.map(([k, l]) => F(k, l))}
          <label className="block"><span className="label">初動方向</span>
            <select className="input" value={v.initial_direction ?? ""} onChange={set("initial_direction")}>
              <option value="">—</option><option value="up">上昇</option><option value="down">下落</option><option value="flat">横ばい</option>
            </select></label>
        </div>
      </fieldset>
      <fieldset className="border border-line rounded-lg p-3 overflow-x-auto">
        <legend className="text-xs text-gold px-1">4-6 5分以内の到達確率（%）</legend>
        <table className="tbl">
          <thead><tr><th>値幅</th>{KINDS.map(([k, l]) => <th key={k}>{l}</th>)}</tr></thead>
          <tbody>
            {THRESHOLDS.map((t) => (
              <tr key={t}><td>{t}ドル</td>
                {KINDS.map(([k]) => <td key={k}><input className="input num w-20" type="number" step="any" value={v[`r_${t}_${k}`] ?? ""} onChange={set(`r_${t}_${k}`)} /></td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </fieldset>
      <label className="block"><span className="label">予測根拠</span>
        <textarea className="input min-h-[80px]" value={v.rationale} onChange={set("rationale")} /></label>
      {errors && <div className="text-sm text-down whitespace-pre-wrap border border-down/40 rounded-lg p-2">{errors}</div>}
      <button className="btn btn-gold" disabled={saving} onClick={submit}>{saving ? "保存中…" : "新しいバージョンとして保存"}</button>
    </div>
  );
}
