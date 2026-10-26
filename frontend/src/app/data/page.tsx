"use client";
import { useState } from "react";
import { api, errorText } from "@/lib/api";
import { fmtJst } from "@/lib/format";
import { Loading, Tag, useApi } from "@/components/ui";

interface Status {
  coverage: { symbol: string; timeframe_min: number; bars: number; first: string; last: string }[];
  batches: { id: number; filename: string; symbol: string; timeframe_min: number | null; status: string; message: string | null; rows_inserted: number; rows_skipped: number; assumed_tz: string; created_at: string }[];
  jobs: { id: number; job: string; status: string; message: string | null; started_at: string; finished_at: string | null }[];
  sources: { key: string; name: string; targets: string; phase: number; status: string }[];
  supported_symbols: string[];
}

export default function DataPage() {
  const { data, error, loading, reload } = useApi<Status>("/api/data/status");
  const [file, setFile] = useState<File | null>(null);
  const [symbol, setSymbol] = useState("XAUUSD");
  const [tz, setTz] = useState("UTC");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function upload() {
    if (!file) return;
    setBusy(true); setMsg(null);
    const fd = new FormData();
    fd.append("file", file); fd.append("symbol", symbol); fd.append("assumed_tz", tz);
    try {
      const r = await api<any>("/api/data/import", { method: "POST", body: fd });
      setMsg(`${r.batch.message}。検証完了: ${r.refresh.verified.length}件`);
    } catch (e) { setMsg("取込失敗: " + errorText(e)); }
    finally { setBusy(false); reload(); }
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
        <div className="card-title">TradingView CSVインポート</div>
        <p className="text-xs text-muted">TradingViewの「チャートデータをエクスポート」で出力したCSV（time,open,high,low,close,…）を取り込みます。1分足を推奨（初動・反転の判定に必要）。time列がタイムゾーンなしの日時の場合は、その前提タイムゾーンを指定してください（UNIX時刻ならUTC固定）。取込後、発表済みイベントの自動検証が実行されます。</p>
        <div className="grid sm:grid-cols-4 gap-3 items-end">
          <label className="block sm:col-span-2"><span className="label">CSVファイル</span><input type="file" accept=".csv,text/csv" className="input" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></label>
          <label className="block"><span className="label">シンボル</span>
            <select className="input" value={symbol} onChange={(e) => setSymbol(e.target.value)}>{(data?.supported_symbols ?? ["XAUUSD"]).map((s) => <option key={s}>{s}</option>)}</select></label>
          <label className="block"><span className="label">タイムゾーン前提</span>
            <select className="input" value={tz} onChange={(e) => setTz(e.target.value)}>{["UTC", "Asia/Tokyo", "America/New_York", "Europe/London"].map((s) => <option key={s}>{s}</option>)}</select></label>
        </div>
        <div className="flex gap-2">
          <button className="btn btn-gold" disabled={!file || busy} onClick={upload}>{busy ? "処理中…" : "インポート"}</button>
          <button className="btn" disabled={busy} onClick={refresh}>ステータス更新・自動検証を実行</button>
        </div>
        {msg && <div className="text-sm text-sky-300 whitespace-pre-wrap">{msg}</div>}
      </section>
      {!data ? <Loading error={error} loading={loading} /> : (
        <>
          <section className="card">
            <div className="card-title">データソース</div>
            <div className="overflow-x-auto"><table className="tbl"><thead><tr><th>ソース</th><th>対象</th><th>フェーズ</th><th>状態</th></tr></thead>
              <tbody>{data.sources.map((s) => <tr key={s.key}><td>{s.name}</td><td className="text-xs">{s.targets}</td><td>Phase {s.phase}</td><td><Tag tone={s.status === "利用中" ? "green" : "slate"}>{s.status}</Tag></td></tr>)}</tbody></table></div>
            <p className="text-[11px] text-muted mt-2">外部API（有料のものを含む）への接続は、利用規約と契約内容を確認したうえで設定します。</p>
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
