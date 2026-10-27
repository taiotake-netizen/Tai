"use client";
import { useState } from "react";
import { api, errorText } from "@/lib/api";
import { fmtJst } from "@/lib/format";
import { Loading, Tag, useApi } from "@/components/ui";

interface Status {
  coverage: { symbol: string; timeframe_min: number; bars: number; first: string; last: string }[];
  batches: { id: number; filename: string; symbol: string; timeframe_min: number | null; status: string; message: string | null; rows_inserted: number; rows_skipped: number; assumed_tz: string; created_at: string }[];
  jobs: { id: number; job: string; status: string; message: string | null; started_at: string; finished_at: string | null }[];
  sources: { key: string; name: string; targets: string; status: string }[];
  supported_symbols: string[];
}

export default function DataPage() {
  const { data, error, loading, reload } = useApi<Status>("/api/data/status");
  const [files, setFiles] = useState<File[]>([]);
  const [eventsOnly, setEventsOnly] = useState(true);
  const [symbol, setSymbol] = useState("XAUUSD");
  const [tz, setTz] = useState("UTC");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function upload() {
    if (!files.length) return;
    setBusy(true); setMsg(null);
    const lines: string[] = [];
    for (const [i, file] of files.entries()) {
      setMsg(`取込中 ${i + 1}/${files.length}: ${file.name}`);
      const fd = new FormData();
      fd.append("file", file); fd.append("symbol", symbol); fd.append("assumed_tz", tz);
      fd.append("events_only", String(eventsOnly));
      try {
        const r = await api<any>("/api/data/import", { method: "POST", body: fd });
        lines.push(`✓ ${file.name}: ${r.batch.message}。検証完了 ${r.refresh.verified.length}件`);
      } catch (e) { lines.push(`✗ ${file.name}: ${errorText(e)}`); }
    }
    setMsg(lines.join("\n"));
    setBusy(false); reload();
  }
  async function calendar() {
    setBusy(true); setMsg(null);
    try {
      const r = await api<any>("/api/data/calendar/fetch", { method: "POST" });
      const mm = r.time_mismatches.map((m: any) => `・${m.title}: カレンダー ${new Date(m.feed_time).toLocaleString("ja-JP", { timeZone: "Asia/Tokyo" })} / 登録 ${new Date(m.event_time).toLocaleString("ja-JP", { timeZone: "Asia/Tokyo" })}`).join("\n");
      setMsg(`予想・前回値を更新 ${r.updated.length}件、追加 ${r.created.length}件${mm ? `\n時刻不一致（要確認）:\n${mm}` : ""}`);
    } catch (e) { setMsg(errorText(e)); } finally { setBusy(false); reload(); }
  }
  async function refresh() {
    setBusy(true);
    try { const r = await api<any>("/api/jobs/refresh", { method: "POST" }); setMsg(`過去へ移動 ${r.moved.length}件 / 検証完了 ${r.verified.length}件`); }
    catch (e) { setMsg(errorText(e)); } finally { setBusy(false); reload(); }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-bold">データ取得</h1>
      <section className="card space-y-3">
        <div className="card-title">価格CSVインポート（TradingView / Dukascopy）</div>
        <p className="text-xs text-muted">TradingViewの「チャートデータをエクスポート」のCSVと、Dukascopyのヒストリカルデータ（Gmt time / Local time形式）を取り込めます。形式は自動で判定します。1分足を推奨します（初動・反転の判定に必要）。複数ファイルを選ぶと順番に取り込みます。取込後、発表済みイベントの自動検証が実行されます。</p>
        <div className="grid sm:grid-cols-4 gap-3 items-end">
          <label className="block sm:col-span-2"><span className="label">CSVファイル（複数可）</span><input id="csv-files" type="file" multiple accept=".csv,text/csv" className="input" onChange={(e) => setFiles(Array.from(e.target.files ?? []))} /></label>
          <label className="block"><span className="label">シンボル</span>
            <select className="input" value={symbol} onChange={(e) => setSymbol(e.target.value)}>{(data?.supported_symbols ?? ["XAUUSD"]).map((s) => <option key={s}>{s}</option>)}</select></label>
          <label className="block"><span className="label">タイムゾーン前提</span>
            <select className="input" value={tz} onChange={(e) => setTz(e.target.value)}>{["UTC", "Asia/Tokyo", "America/New_York", "Europe/London"].map((s) => <option key={s}>{s}</option>)}</select></label>
        </div>
        <label className="text-sm flex items-center gap-2"><input id="events-only" type="checkbox" checked={eventsOnly} onChange={(e) => setEventsOnly(e.target.checked)} />
          登録済みイベントの発表前後3時間だけを保存する（数年分のファイルを取り込むときに推奨）</label>
        <div className="flex gap-2">
          <button className="btn btn-gold" disabled={!files.length || busy} onClick={upload}>{busy ? "処理中…" : "インポート"}</button>
          <button className="btn" disabled={busy} onClick={refresh}>ステータス更新・自動検証を実行</button>
        </div>
        {msg && <div className="text-sm text-sky-300 whitespace-pre-wrap">{msg}</div>}
      </section>
      {!data ? <Loading error={error} loading={loading} /> : (
        <>
          <section className="card">
            <div className="card-title">データソース</div>
            <div className="overflow-x-auto"><table className="tbl"><thead><tr><th>ソース</th><th>対象</th><th>状態</th></tr></thead>
              <tbody>{data.sources.map((s) => <tr key={s.key}><td className="whitespace-normal">{s.name}</td><td className="text-xs whitespace-normal">{s.targets}</td><td><Tag tone={s.status.startsWith("利用中") || s.status.startsWith("自動") ? "green" : "slate"}>{s.status}</Tag></td></tr>)}</tbody></table></div>
            <div className="flex flex-wrap gap-2 mt-3">
              <button className="btn" disabled={busy} onClick={calendar}>週間カレンダーから市場予想・前回値を取得</button>
            </div>
            <details className="text-xs text-muted mt-3">
              <summary className="cursor-pointer text-slate-300">APIキーの設定方法</summary>
              <div className="mt-2 space-y-1">
                <p>プロジェクト直下の <code>.env</code> に設定して <code>docker compose up -d</code> で再起動します（<code>.env.example</code> 参照）。</p>
                <p><code>ANTHROPIC_API_KEY</code>: AI予測・検証レポートの仮説生成。重要度8以上のイベントは前日・直前に自動でAI予測を作成（<code>AUTO_AI_FORECAST=0</code>で停止）。</p>
                <p><code>TWELVEDATA_API_KEY</code>: XAUUSD 1分足を発表65分後に自動取得し、自動検証まで実行（無料プランあり）。</p>
                <p><code>CALENDAR_FEED_ENABLED=1</code>: 週間カレンダーを6時間ごとに取得し、市場予想・前回値を補完。公式日程との時刻不一致は自動変更せず報告します。</p>
              </div>
            </details>
          </section>
          <section className="card">
            <div className="card-title">価格データの保有範囲</div>
            {data.coverage.length === 0 ? <div className="text-sm text-muted">まだ取り込まれていません。</div> : (
              <table className="tbl"><thead><tr><th>シンボル</th><th>時間足</th><th>本数</th><th>開始（日本時間）</th><th>終了</th></tr></thead>
                <tbody>{data.coverage.map((c) => <tr key={`${c.symbol}${c.timeframe_min}`} className="num"><td>{c.symbol}</td><td>{c.timeframe_min}分</td><td>{c.bars.toLocaleString()}</td><td>{fmtJst(c.first)}</td><td>{fmtJst(c.last)}</td></tr>)}</tbody></table>
            )}
          </section>
          <section className="card">
            <div className="card-title">インポート履歴</div>
            <div className="overflow-x-auto"><table className="tbl"><thead><tr><th>日時</th><th>ファイル</th><th>シンボル</th><th>結果</th><th>詳細</th></tr></thead>
              <tbody>{data.batches.map((b) => <tr key={b.id}><td className="text-xs num">{fmtJst(b.created_at)}</td><td>{b.filename}</td><td>{b.symbol}</td><td><Tag tone={b.status === "success" ? "green" : "red"}>{b.status === "success" ? "成功" : "失敗"}</Tag></td><td className="text-xs whitespace-normal">{b.message}</td></tr>)}</tbody></table></div>
          </section>
          <section className="card">
            <div className="card-title">ジョブ実行履歴</div>
            <div className="overflow-x-auto"><table className="tbl"><thead><tr><th>開始</th><th>ジョブ</th><th>結果</th><th>内容</th></tr></thead>
              <tbody>{data.jobs.map((j) => <tr key={j.id}><td className="text-xs num">{fmtJst(j.started_at)}</td><td>{j.job}</td><td><Tag tone={j.status === "success" ? "green" : j.status === "failed" ? "red" : "slate"}>{j.status}</Tag></td><td className="text-xs whitespace-normal">{j.message}</td></tr>)}</tbody></table></div>
          </section>
        </>
      )}
    </div>
  );
}
