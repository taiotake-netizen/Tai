"use client";

import { useState } from "react";
import type { ConsoleState } from "@/lib/client/useConsole";
import { fmtTime, type Tone } from "@/lib/format";
import type { Idea } from "@/lib/types";
import type { Act } from "../Console";
import { Badge, Button, Drawer, Empty, ErrorNote, Field, inputCls, Skeleton } from "../ui/primitives";
import { useData } from "./useData";

const STATUS: Record<string, { label: string; tone: Tone }> = {
  ready: { label: "未使用", tone: "ok" }, used: { label: "使用済み", tone: "muted" }, reserved: { label: "生成で使用中", tone: "accent" },
  held: { label: "保留", tone: "warn" }, retired: { label: "終了", tone: "muted" }, draft: { label: "下書き", tone: "muted" },
};
const ORIGIN: Record<string, string> = { manual: "手動", ai_refill: "AI補充", derived: "派生", seed: "初期" };

type IdeaDetail = Idea & {
  posts: { id: number; status: string; slot_at: string; published_at: string | null; views: number | null; likes: number | null; metrics_status: string | null }[];
  children: { id: number; theme: string; angle: string; status: string; origin: string }[];
  history: { actor: string; action: string; created_at: string }[];
};

export function IdeasDrawer({ open, onClose, c, act }: { open: boolean; onClose: () => void; c: ConsoleState; act: Act }) {
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [sel, setSel] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const params = new URLSearchParams({ limit: "100", ...(status ? { status } : {}), ...(query ? { q: query } : {}) });
  const list = useData<{ items: Idea[]; total: number; counts: Record<string, number> }>(c.client, `ideas?${params}`, open, c.version);
  const settings = useData<{ settings: { content: { themes: string[]; appeals: string[] } } }>(c.client, "settings", open, 0);
  const themes = settings.data?.settings.content.themes ?? [];
  const appeals = settings.data?.settings.content.appeals ?? [];
  return (
    <Drawer open={open} onClose={onClose} title="ネタ管理" wide>
      {sel !== null ? (
        <IdeaEditor id={sel} c={c} act={act} themes={themes} appeals={appeals} onBack={() => { setSel(null); list.reload(); }} onOpen={setSel} />
      ) : creating ? (
        <IdeaForm themes={themes} appeals={appeals} onCancel={() => setCreating(false)} onSubmit={async (v) => {
          if (await act("ネタの追加", () => c.client!.post("ideas", v))) { setCreating(false); list.reload(); }
        }} />
      ) : (
        <div className="space-y-4">
          <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); setQuery(q); }}>
            <Field label="検索"><input className={inputCls} value={q} onChange={(e) => setQ(e.target.value)} placeholder="テーマ・悩み・切り口" /></Field>
            <Field label="状態">
              <select className={inputCls} value={status} onChange={(e) => setStatus(e.target.value)}>
                <option value="">すべて</option>
                {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}（{list.data?.counts[k] ?? 0}）</option>)}
              </select>
            </Field>
            <Button type="submit">絞り込む</Button>
            {c.session?.role === "admin" && <Button variant="primary" className="ml-auto" type="button" onClick={() => setCreating(true)}>ネタを追加</Button>}
          </form>
          {list.error ? <ErrorNote>{list.error}</ErrorNote> : !list.data ? <Skeleton lines={6} /> : !list.data.items.length ? <Empty>該当するネタはありません</Empty> : (
            <ul className="divide-y divide-line/60">
              {list.data.items.map((i) => (
                <li key={i.id}>
                  <button className="flex w-full items-start gap-3 py-2.5 text-left hover:bg-white/[0.02]" onClick={() => setSel(i.id)}>
                    <Badge tone={STATUS[i.status]?.tone ?? "muted"}>{STATUS[i.status]?.label ?? i.status}</Badge>
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm">{i.theme}<span className="text-muted">／{i.angle || i.pain || "（切り口未設定）"}</span></span>
                      <span className="block text-[11px] text-muted">{ORIGIN[i.origin] ?? i.origin}・使用{i.use_count}回・最終使用 {fmtTime(i.last_used_at)}{i.parent_idea_id ? `・#${i.parent_idea_id}から派生` : ""}</span>
                    </span>
                    <span className="num text-xs text-muted">#{i.id}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Drawer>
  );
}

type IdeaValues = { theme: string; pain: string; appeal: string; angle: string; notes: string; status: string };

function IdeaForm({ initial, themes, appeals, onSubmit, onCancel }: { initial?: Partial<IdeaValues>; themes: string[]; appeals: string[];
  onSubmit: (v: IdeaValues) => void; onCancel: () => void }) {
  const [v, setV] = useState<IdeaValues>({ theme: initial?.theme ?? themes[0] ?? "", pain: initial?.pain ?? "", appeal: initial?.appeal ?? "",
    angle: initial?.angle ?? "", notes: initial?.notes ?? "", status: initial?.status ?? "ready" });
  const theme = v.theme || themes[0] || "";
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); onSubmit({ ...v, theme }); }}>
      <Field label="テーマ"><select className={inputCls} value={theme} onChange={(e) => setV({ ...v, theme: e.target.value })}>{themes.map((t) => <option key={t}>{t}</option>)}</select></Field>
      <Field label="読者の悩み"><input className={inputCls} maxLength={200} value={v.pain} onChange={(e) => setV({ ...v, pain: e.target.value })} /></Field>
      <Field label="訴求"><select className={inputCls} value={v.appeal} onChange={(e) => setV({ ...v, appeal: e.target.value })}><option value="">（指定なし）</option>{appeals.map((t) => <option key={t}>{t}</option>)}</select></Field>
      <Field label="切り口"><input className={inputCls} maxLength={200} value={v.angle} onChange={(e) => setV({ ...v, angle: e.target.value })} /></Field>
      <Field label="メモ" hint="事実や実績を書く場合は、設定の「承認済みの事実」に登録したものだけが投稿に使われます"><textarea className={`${inputCls} min-h-20`} maxLength={1000} value={v.notes} onChange={(e) => setV({ ...v, notes: e.target.value })} /></Field>
      <div className="flex gap-2"><Button type="submit" variant="primary">保存</Button><Button type="button" onClick={onCancel}>戻る</Button></div>
    </form>
  );
}

function IdeaEditor({ id, c, act, themes, appeals, onBack, onOpen }: { id: number; c: ConsoleState; act: Act; themes: string[]; appeals: string[];
  onBack: () => void; onOpen: (id: number) => void }) {
  const { data: d, error, reload } = useData<IdeaDetail>(c.client, `ideas/${id}`, true, c.version);
  const [editing, setEditing] = useState(false);
  if (error) return <div className="space-y-3"><ErrorNote>{error}</ErrorNote><Button onClick={onBack}>一覧へ戻る</Button></div>;
  if (!d || d.id !== id) return <Skeleton lines={6} />;
  const admin = c.session?.role === "admin";
  if (editing) return <IdeaForm initial={d} themes={themes} appeals={appeals} onCancel={() => setEditing(false)} onSubmit={async (v) => {
    if (await act("ネタの更新", () => c.client!.put(`ideas/${id}`, { ...v, status: ["used", "reserved"].includes(d.status) ? "ready" : v.status, expected_updated_at: d.updated_at }))) {
      setEditing(false); reload();
    }
  }} />;
  return (
    <div className="space-y-4 text-sm">
      <Button variant="ghost" onClick={onBack}>← 一覧へ戻る</Button>
      <div className="flex flex-wrap items-center gap-2"><Badge tone={STATUS[d.status]?.tone ?? "muted"}>{STATUS[d.status]?.label ?? d.status}</Badge><span className="text-muted">#{d.id}・{ORIGIN[d.origin]}</span></div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
        <dt className="text-muted">テーマ</dt><dd>{d.theme}</dd><dt className="text-muted">悩み</dt><dd>{d.pain || "—"}</dd>
        <dt className="text-muted">訴求</dt><dd>{d.appeal || "—"}</dd><dt className="text-muted">切り口</dt><dd>{d.angle || "—"}</dd>
        <dt className="text-muted">メモ</dt><dd className="whitespace-pre-wrap">{d.notes || "—"}</dd>
        <dt className="text-muted">派生元</dt><dd>{d.parent_idea_id ? <button className="text-accent hover:underline" onClick={() => onOpen(d.parent_idea_id!)}>#{d.parent_idea_id}</button> : "—"}</dd>
      </dl>
      {admin && d.status !== "reserved" && (
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => setEditing(true)}>編集</Button>
          {d.status !== "held" ? <Button onClick={async () => { if (await act("保留", () => c.client!.post(`ideas/${id}/status`, { status: "held" }))) reload(); }}>保留にする</Button>
            : <Button onClick={async () => { if (await act("保留解除", () => c.client!.post(`ideas/${id}/status`, { status: "ready" }))) reload(); }}>保留を解除</Button>}
          {d.status !== "retired" && <Button variant="danger" onClick={async () => { if (await act("使用終了", () => c.client!.post(`ideas/${id}/status`, { status: "retired" }))) reload(); }}>今後使わない</Button>}
        </div>
      )}
      <section>
        <h3 className="panel-title mb-1">使用履歴</h3>
        {!d.posts.length ? <p className="text-xs text-muted">まだ使われていません</p> : (
          <ul className="space-y-1 text-xs">{d.posts.map((p) => <li key={p.id} className="flex gap-2"><span className="num text-muted">{fmtTime(p.published_at ?? p.slot_at)}</span><span>投稿#{p.id}</span><span>{p.status}</span>
            <span className="num ml-auto">{p.metrics_status === "ok" ? `閲覧 ${p.views ?? "—"}・いいね ${p.likes ?? "—"}` : p.metrics_status ? "実績未取得" : ""}</span></li>)}</ul>
        )}
      </section>
      <section>
        <h3 className="panel-title mb-1">派生したネタ</h3>
        {!d.children.length ? <p className="text-xs text-muted">なし</p> : <ul className="space-y-1">{d.children.map((ch) => <li key={ch.id}><button className="text-accent hover:underline" onClick={() => onOpen(ch.id)}>#{ch.id} {ch.theme}／{ch.angle}</button></li>)}</ul>}
      </section>
      <section>
        <h3 className="panel-title mb-1">変更履歴</h3>
        <ul className="space-y-1 text-xs text-muted">{d.history.map((h, i) => <li key={i}><span className="num">{fmtTime(h.created_at)}</span> {h.actor} {h.action}</li>)}</ul>
      </section>
    </div>
  );
}
