"use client";

import { useState } from "react";
import type { ConsoleState } from "@/lib/client/useConsole";
import { fmtNum, fmtPct, fmtTime } from "@/lib/format";
import type { Act } from "../Console";
import { Badge, Button, Drawer, Empty, ErrorNote, Skeleton } from "../ui/primitives";
import { useData } from "./useData";

type ReportRow = { id: number; kind: "daily" | "weekly"; period_start: string; period_end: string; version: number; summary_status: string; generated_at: string; data_as_of: string };
type Group = { value: string; n: number; mean_er: number };
type ReportData = {
  planned_slots: number; published_count: number; post_status_counts: Record<string, number>;
  publish_attempts: { success: number; failed: number; unknown: number; total: number }; success_rate: number | null;
  metrics: { posts_with_metrics: number; posts_without_metrics: number; totals: Record<string, number | null>; mean_er: number | null; metric_failures: number };
  by_theme: Group[]; by_hook: Group[]; top_posts: { id: number; text: string; er: number; views: number }[];
  experiments: { id: number; variable: string; control_value: string; treatment_value: string; status: string; result: { note?: string } | null }[];
  policy_changes: { version: number; source: string; reason: string; created_at: string }[];
  next: { running_experiment: { variable: string; control_value: string; treatment_value: string; hypothesis: string } | null };
  errors: { message: string; occurred_at: string }[]; notes: string[]; definitions: Record<string, unknown>; last_metrics_observed_at: string | null;
};
type ReportDetail = ReportRow & { data: ReportData; summary_text: string | null; generated_by: string;
  versions: { id: number; version: number; is_current: number; generated_at: string; generated_by: string }[] };

const SUM: Record<string, string> = { ok: "AI要約あり", skipped_no_ai: "AI未接続のため要約なし", skipped_budget: "予算の都合で要約なし", failed: "要約に失敗" };

export function ReportsDrawer({ open, onClose, c, act }: { open: boolean; onClose: () => void; c: ConsoleState; act: Act }) {
  const [kind, setKind] = useState<"" | "daily" | "weekly">("");
  const [sel, setSel] = useState<number | null>(null);
  const list = useData<{ items: ReportRow[] }>(c.client, `reports${kind ? `?kind=${kind}` : ""}`, open, c.version);
  const det = useData<ReportDetail>(c.client, sel ? `reports/${sel}` : null, open && sel !== null, c.version);
  const d = det.data && det.data.id === sel ? det.data : null;
  return (
    <Drawer open={open} onClose={onClose} title="レポート" wide>
      {sel === null ? (
        <div className="space-y-3">
          <div className="flex gap-1" role="tablist">
            {(["", "daily", "weekly"] as const).map((k) => <Button key={k} role="tab" aria-selected={kind === k} variant={kind === k ? "primary" : "ghost"} className="min-h-7 px-2 text-xs" onClick={() => setKind(k)}>{{ "": "すべて", daily: "日次", weekly: "週次" }[k]}</Button>)}
          </div>
          <p className="text-xs text-muted">日次は毎日09:00（前日分）、週次は毎週月曜09:15（前週分）に自動作成します（日本時間・設定で変更可）。</p>
          {list.error ? <ErrorNote>{list.error}</ErrorNote> : !list.data ? <Skeleton /> : !list.data.items.length ? <Empty>まだレポートはありません</Empty> : (
            <ul className="divide-y divide-line/60">{list.data.items.map((r) => (
              <li key={r.id}><button className="flex w-full items-center gap-3 py-2.5 text-left hover:bg-white/[0.02]" onClick={() => setSel(r.id)}>
                <Badge tone={r.kind === "daily" ? "accent" : "ok"}>{r.kind === "daily" ? "日次" : "週次"}</Badge>
                <span className="num text-sm">{fmtTime(r.period_start)} 〜 {fmtTime(r.period_end)}</span>
                <span className="text-xs text-muted">v{r.version}</span>
                <span className="ml-auto text-xs text-muted">{SUM[r.summary_status]}</span>
              </button></li>))}</ul>
          )}
        </div>
      ) : det.error ? <ErrorNote>{det.error}</ErrorNote> : !d ? <Skeleton lines={8} /> : (
        <div className="space-y-5 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="ghost" onClick={() => setSel(null)}>← 一覧へ</Button>
            {c.session?.role === "admin" && <Button className="ml-auto" onClick={() => void act("レポート再生成",
              () => c.client!.post("reports/regenerate", { kind: d.kind, period_start: d.period_start }), () => "再生成を受け付けました（完了すると新しい版が表示されます）")}>再生成</Button>}
          </div>
          <div>
            <h3 className="text-base">{d.kind === "daily" ? "日次" : "週次"}レポート v{d.version}</h3>
            <p className="num text-xs text-muted">対象 {fmtTime(d.period_start)}〜{fmtTime(d.period_end)}（JST）／生成 {fmtTime(d.generated_at)}／最終データ取得 {fmtTime(d.data.last_metrics_observed_at)}</p>
          </div>
          <div className="rounded-lg border border-line/60 bg-bg/40 p-3">
            <p className="panel-title mb-1">要約</p>
            {d.summary_text ? <p className="whitespace-pre-wrap leading-relaxed">{d.summary_text}</p> : <p className="text-muted">{SUM[d.summary_status]}。下の集計値は確認できます。</p>}
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {[["投稿数", fmtNum(d.data.published_count)], ["公開試行", fmtNum(d.data.publish_attempts.total)],
              ["成功／失敗／不明", `${d.data.publish_attempts.success}／${d.data.publish_attempts.failed}／${d.data.publish_attempts.unknown}`],
              ["成功率", fmtPct(d.data.success_rate, 0)], ["閲覧", fmtNum(d.data.metrics.totals.views)], ["いいね", fmtNum(d.data.metrics.totals.likes)],
              ["平均反応率", fmtPct(d.data.metrics.mean_er, 2)], ["実績未取得", `${d.data.metrics.posts_without_metrics}件`]].map(([l, v]) => (
              <div key={l} className="rounded-lg border border-line/60 px-3 py-2"><p className="text-[11px] text-muted">{l}</p><p className="num text-base">{v}</p></div>))}
          </div>
          {d.data.notes.length > 0 && <ul className="list-disc space-y-1 pl-5 text-xs text-warn">{d.data.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
          <GroupTable title="テーマ別（比較可能な投稿のみ）" rows={d.data.by_theme} />
          <GroupTable title="書き出し別" rows={d.data.by_hook} />
          <section>
            <h3 className="panel-title mb-1">改善実験</h3>
            {!d.data.experiments.length ? <p className="text-xs text-muted">期間中の実験はありません</p> :
              <ul className="space-y-1 text-xs">{d.data.experiments.map((e) => <li key={e.id}>#{e.id} {e.variable}：{e.control_value}→{e.treatment_value}（{e.status}）{e.result?.note && ` — ${e.result.note}`}</li>)}</ul>}
          </section>
          <section>
            <h3 className="panel-title mb-1">自動変更した方針</h3>
            {!d.data.policy_changes.length ? <p className="text-xs text-muted">変更なし</p> :
              <ul className="space-y-1 text-xs">{d.data.policy_changes.map((p) => <li key={p.version}>v{p.version}（{p.source}）{p.reason}</li>)}</ul>}
          </section>
          <section>
            <h3 className="panel-title mb-1">次に試すこと</h3>
            <p className="text-xs">{d.data.next.running_experiment ? `${d.data.next.running_experiment.variable}：${d.data.next.running_experiment.control_value} と ${d.data.next.running_experiment.treatment_value} の比較を継続（${d.data.next.running_experiment.hypothesis}）` : "実績が集まり次第、自動で次の実験を開始します"}</p>
          </section>
          <section>
            <h3 className="panel-title mb-1">エラー・対応が必要な事項</h3>
            {!d.data.errors.length ? <p className="text-xs text-muted">なし</p> : <ul className="space-y-1 text-xs text-error">{d.data.errors.map((e, i) => <li key={i}><span className="num">{fmtTime(e.occurred_at)}</span> {e.message}</li>)}</ul>}
          </section>
          <section>
            <h3 className="panel-title mb-1">版の履歴</h3>
            <ul className="space-y-1 text-xs">{d.versions.map((v) => <li key={v.id}><button className="text-accent hover:underline" onClick={() => setSel(v.id)}>v{v.version}</button>{v.is_current ? "（最新）" : ""} <span className="num text-muted">{fmtTime(v.generated_at)}</span> {v.generated_by}</li>)}</ul>
          </section>
        </div>
      )}
    </Drawer>
  );
}

function GroupTable({ title, rows }: { title: string; rows: Group[] }) {
  return (
    <section>
      <h3 className="panel-title mb-1">{title}</h3>
      {!rows.length ? <p className="text-xs text-muted">比較できるデータがありません</p> : (
        <table className="w-full text-xs"><thead className="text-muted"><tr><th className="text-left font-normal">項目</th><th className="text-right font-normal">件数</th><th className="text-right font-normal">平均反応率</th></tr></thead>
          <tbody className="num">{rows.map((r) => <tr key={r.value} className="border-t border-line/50"><td className="font-sans">{r.value}</td><td className="text-right">{r.n}</td><td className="text-right">{fmtPct(r.mean_er, 2)}{r.n < 3 ? "（参考）" : ""}</td></tr>)}</tbody></table>
      )}
    </section>
  );
}
