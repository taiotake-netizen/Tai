"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, errorText } from "@/lib/api";
import { CATEGORY_JA } from "@/lib/format";

export default function NewEventPage() {
  const router = useRouter();
  const [v, setV] = useState({ title: "", category: "CPI", release: "", importance: "7", confirmed: false, notes: "" });
  const [inds, setInds] = useState<{ code: string; name: string; unit: string; previous: string; consensus: string }[]>([]);
  const [err, setErr] = useState<string | null>(null);
  async function submit() {
    setErr(null);
    try {
      const ev = await api<{ id: number }>("/api/events", {
        method: "POST",
        body: JSON.stringify({
          title: v.title, category: v.category, importance: Number(v.importance),
          // 入力は日本時間として解釈
          release_at: v.release ? `${v.release}:00+09:00` : null,
          release_time_confirmed: v.confirmed, notes: v.notes || null,
          indicators: inds.filter((i) => i.code && i.name).map((i) => ({
            code: i.code, name: i.name, unit: i.unit,
            previous: i.previous === "" ? null : Number(i.previous), consensus: i.consensus === "" ? null : Number(i.consensus),
          })),
        }),
      });
      router.push(`/events/${ev.id}`);
    } catch (e) { setErr(errorText(e)); }
  }
  return (
    <div className="card max-w-3xl space-y-3">
      <h1 className="text-lg font-bold">イベント登録</h1>
      <label className="block"><span className="label">指標名</span><input className="input" value={v.title} onChange={(e) => setV({ ...v, title: e.target.value })} /></label>
      <div className="grid sm:grid-cols-3 gap-3">
        <label className="block"><span className="label">カテゴリ</span>
          <select className="input" value={v.category} onChange={(e) => setV({ ...v, category: e.target.value })}>
            {Object.entries(CATEGORY_JA).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select></label>
        <label className="block"><span className="label">発表日時（日本時間）</span><input type="datetime-local" className="input" value={v.release} onChange={(e) => setV({ ...v, release: e.target.value })} /></label>
        <label className="block"><span className="label">重要度（1-10）</span><input type="number" min={1} max={10} className="input" value={v.importance} onChange={(e) => setV({ ...v, importance: e.target.value })} /></label>
      </div>
      <label className="text-sm flex gap-2 items-center"><input type="checkbox" checked={v.confirmed} onChange={(e) => setV({ ...v, confirmed: e.target.checked })} />発表時刻を公式カレンダーで確認済み</label>
      <div>
        <div className="label mb-1">経済指標（同時発表は複数登録）</div>
        {inds.map((i, k) => (
          <div key={k} className="grid grid-cols-5 gap-2 mb-2">
            {(["code", "name", "unit", "previous", "consensus"] as const).map((f) => (
              <input key={f} className="input" placeholder={{ code: "コード(例 CPI_YOY)", name: "名称", unit: "単位", previous: "前回値", consensus: "市場予想" }[f]}
                value={i[f]} onChange={(e) => setInds((p) => p.map((x, j) => (j === k ? { ...x, [f]: e.target.value } : x)))} />
            ))}
          </div>
        ))}
        <button className="btn" onClick={() => setInds((p) => [...p, { code: "", name: "", unit: "", previous: "", consensus: "" }])}>＋ 指標</button>
      </div>
      <label className="block"><span className="label">メモ</span><textarea className="input" value={v.notes} onChange={(e) => setV({ ...v, notes: e.target.value })} /></label>
      {err && <div className="text-sm text-down whitespace-pre-wrap">{err}</div>}
      <button className="btn btn-gold" onClick={submit}>登録</button>
    </div>
  );
}
