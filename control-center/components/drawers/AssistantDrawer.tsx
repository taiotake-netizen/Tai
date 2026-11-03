"use client";

import { useState } from "react";
import type { ConsoleState } from "@/lib/client/useConsole";
import { fmtTime, type Tone } from "@/lib/format";
import type { Act } from "../Console";
import { Badge, Button, Drawer, Empty, ErrorNote, Field, inputCls, Skeleton } from "../ui/primitives";
import { useData } from "./useData";

type Run = { id: number; kind: "summary" | "draft" | "improvement"; status: string; error: string | null; created_at: string; created_by: string;
  input: { instruction?: string; theme?: string | null }; draft_post_id: number | null;
  output: { summary?: string; suggestions?: string[]; note?: string; text?: string | null; status?: string; draft_post_id?: number } | null };

const KIND: Record<string, string> = { summary: "運用状況の要約", draft: "投稿案の作成（下書き保存）", improvement: "改善案の提案" };
const ST: Record<string, { label: string; tone: Tone }> = {
  queued: { label: "待機", tone: "muted" }, running: { label: "実行中", tone: "accent" }, succeeded: { label: "完了", tone: "ok" },
  failed: { label: "失敗", tone: "error" }, unavailable: { label: "実行不可", tone: "warn" },
};

export function AssistantDrawer({ open, onClose, c, act, onOpenPost }: { open: boolean; onClose: () => void; c: ConsoleState; act: Act; onOpenPost: (id: number) => void }) {
  const runs = useData<{ items: Run[] }>(c.client, "assistant/runs", open, c.version);
  const settings = useData<{ settings: { content: { themes: string[]; hook_styles: string[] } } }>(c.client, "settings", open, 0);
  const [kind, setKind] = useState<Run["kind"]>("summary");
  const [instruction, setInstruction] = useState("");
  const [theme, setTheme] = useState("");
  const [hook, setHook] = useState("");
  const cap = c.can(`assistant.${kind}`);
  return (
    <Drawer open={open} onClose={onClose} title="AI補助" wide>
      <div className="space-y-5 text-sm">
        <p className="text-xs text-muted">AI補助は3つの機能に限定しています。入力した文章は要望としてAIに渡すだけで、外部操作やコードの実行には使いません。投稿案は必ず「承認待ち」の下書きとして保存されます。</p>
        {c.session?.role === "admin" && (
          <form className="space-y-3 rounded-xl border border-line/60 p-4" onSubmit={async (e) => {
            e.preventDefault();
            const body: Record<string, unknown> = { kind, instruction };
            if (kind === "draft") { if (theme) body.theme = theme; if (hook) body.hook = hook; }
            if (await act("AI補助の依頼", () => c.client!.post("assistant/runs", body), (r) => (r as Run).status === "unavailable" ? `実行できません：${(r as Run).error}` : "依頼しました（結果は下に表示されます）")) {
              setInstruction(""); runs.reload();
            }
          }}>
            <div className="flex flex-wrap gap-1" role="radiogroup" aria-label="機能">
              {(Object.keys(KIND) as Run["kind"][]).map((k) => <Button key={k} type="button" role="radio" aria-checked={kind === k} variant={kind === k ? "primary" : "default"} className="text-xs" onClick={() => setKind(k)}>{KIND[k]}</Button>)}
            </div>
            {kind === "draft" && (
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="テーマ"><select className={inputCls} value={theme} onChange={(e) => setTheme(e.target.value)}><option value="">（方針に任せる）</option>{settings.data?.settings.content.themes.map((t) => <option key={t}>{t}</option>)}</select></Field>
                <Field label="書き出し"><select className={inputCls} value={hook} onChange={(e) => setHook(e.target.value)}><option value="">（方針に任せる）</option>{settings.data?.settings.content.hook_styles.map((t) => <option key={t}>{t}</option>)}</select></Field>
              </div>
            )}
            <Field label="要望（任意・500文字まで）"><textarea className={`${inputCls} min-h-20`} maxLength={500} value={instruction} onChange={(e) => setInstruction(e.target.value)} /></Field>
            <Button type="submit" variant="primary" disabled={!cap.enabled}>依頼する</Button>
            {!cap.enabled && <p className="text-xs text-warn">実行できません：{cap.reason}</p>}
          </form>
        )}
        <section>
          <h3 className="panel-title mb-2">結果</h3>
          {runs.error ? <ErrorNote>{runs.error}</ErrorNote> : !runs.data ? <Skeleton /> : !runs.data.items.length ? <Empty>まだ依頼はありません</Empty> : (
            <ul className="space-y-2">{runs.data.items.map((r) => (
              <li key={r.id} className="rounded-lg border border-line/60 p-3">
                <div className="flex flex-wrap items-center gap-2"><Badge tone={ST[r.status]?.tone ?? "muted"} spin={r.status === "running"}>{ST[r.status]?.label ?? r.status}</Badge>
                  <span>{KIND[r.kind]}</span><span className="num ml-auto text-xs text-muted">{fmtTime(r.created_at)}</span></div>
                {r.input.instruction && <p className="mt-1 text-xs text-muted">要望：{r.input.instruction}</p>}
                {r.error && <p className="mt-1 text-xs text-warn">{r.error}</p>}
                {r.output?.summary && <p className="mt-2 whitespace-pre-wrap">{r.output.summary}</p>}
                {r.output?.suggestions && <ul className="mt-2 list-disc space-y-1 pl-5">{r.output.suggestions.map((s, i) => <li key={i}>{s}</li>)}</ul>}
                {r.output?.note && <p className="mt-1 text-xs text-muted">{r.output.note}</p>}
                {r.output?.text && <p className="mt-2 whitespace-pre-wrap rounded border border-line/50 bg-bg/50 p-2 text-[13px]">{r.output.text}</p>}
                {r.draft_post_id && <Button className="mt-2 text-xs" onClick={() => onOpenPost(r.draft_post_id!)}>下書き #{r.draft_post_id} を開く</Button>}
              </li>))}</ul>
          )}
        </section>
      </div>
    </Drawer>
  );
}
