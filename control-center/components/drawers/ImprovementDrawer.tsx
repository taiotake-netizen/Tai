"use client";

import { useState } from "react";
import type { ConsoleState } from "@/lib/client/useConsole";
import { fmtPct, fmtTime, type Tone } from "@/lib/format";
import type { Act } from "../Console";
import { Badge, Button, Confirm, Drawer, Empty, ErrorNote, Skeleton } from "../ui/primitives";
import { useData } from "./useData";

type Policy = Record<string, Record<string, number> | string[]>;
type Version = { version: number; parent_version: number | null; source: string; reason: string; is_active: number; created_at: string; created_by: string; policy: Policy };
type Experiment = { id: number; variable: string; hypothesis: string; control_value: string; treatment_value: string; status: string;
  started_at: string; ended_at: string | null; adopted_policy_version: number | null;
  result: { n_treatment?: number; n_control?: number; mean_treatment?: number | null; mean_control?: number | null; lift?: number | null; t_stat?: number | null; note?: string } | null };

const VAR: Record<string, string> = { hook: "書き出し", theme: "テーマ", cta: "CTA", appeal: "訴求", length: "文章量", structure: "構成", post_time: "投稿時間" };
const SRC: Record<string, string> = { initial: "初期", auto: "自動改善", manual: "手動", rollback: "差し戻し" };
const EXP: Record<string, { label: string; tone: Tone }> = {
  running: { label: "実験中", tone: "accent" }, adopted: { label: "採用", tone: "ok" }, rejected: { label: "不採用", tone: "muted" },
  inconclusive: { label: "判定保留", tone: "warn" }, stopped: { label: "停止", tone: "muted" },
};
const W: Record<string, string> = { hook_weights: "書き出し", theme_weights: "テーマ", cta_weights: "CTA", appeal_weights: "訴求", length_weights: "文章量", structure_weights: "構成" };

export function ImprovementDrawer({ open, onClose, c, act }: { open: boolean; onClose: () => void; c: ConsoleState; act: Act }) {
  const pol = useData<{ active: Version; versions: Version[]; locked: string[]; improvement: Record<string, unknown> }>(c.client, "policy", open, c.version);
  const exps = useData<{ items: Experiment[] }>(c.client, "experiments", open, c.version);
  const [rb, setRb] = useState<number | null>(null);
  const admin = c.session?.role === "admin";
  const running = exps.data?.items.find((e) => e.status === "running");
  return (
    <Drawer open={open} onClose={onClose} title="運用方針と改善実験" wide>
      {pol.error ? <ErrorNote>{pol.error}</ErrorNote> : !pol.data ? <Skeleton lines={8} /> : (
        <div className="space-y-6 text-sm">
          <section className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="panel-title">現在の方針</h3>
              <Badge tone="accent">v{pol.data.active.version}</Badge>
              <span className="text-xs text-muted">{SRC[pol.data.active.source]}・{pol.data.active.reason}</span>
              {admin && (
                <Button className="ml-auto text-xs" onClick={() => void act(c.overview?.improvement_enabled ? "自動改善の停止" : "自動改善の再開",
                  () => c.client!.post("control/improvement", { enabled: !c.overview?.improvement_enabled }))}>
                  自動改善を{c.overview?.improvement_enabled ? "停止" : "再開"}
                </Button>
              )}
            </div>
            <p className="text-xs text-muted">自動改善は「重み」と「投稿時間（候補の中から）」だけを、1回あたり最大{String(pol.data.improvement.max_weight_step)}の幅で変更します。
              商品情報・禁止事項・投稿数の上限・予算・固定した項目（{pol.data.locked.length ? pol.data.locked.map((l) => VAR[l] ?? l).join("、") : "なし"}）は変更しません。</p>
            <div className="grid gap-3 sm:grid-cols-2">
              {Object.entries(W).map(([k, label]) => {
                const w = pol.data!.active.policy[k] as Record<string, number> | undefined;
                if (!w) return null;
                return (
                  <div key={k} className="rounded-lg border border-line/60 p-3">
                    <p className="mb-2 text-xs text-muted">{label}</p>
                    <ul className="space-y-1">{Object.entries(w).sort((a, b) => b[1] - a[1]).map(([name, v]) => (
                      <li key={name} className="grid grid-cols-[minmax(0,1fr)_90px_44px] items-center gap-2 text-xs">
                        <span className="truncate">{name}</span>
                        <span className="h-1.5 rounded bg-white/5"><span className="block h-1.5 rounded bg-accent/70" style={{ width: `${Math.min(100, v * 100)}%` }} /></span>
                        <span className="num text-right text-muted">{(v * 100).toFixed(0)}%</span>
                      </li>))}</ul>
                  </div>
                );
              })}
              <div className="rounded-lg border border-line/60 p-3">
                <p className="mb-2 text-xs text-muted">投稿時間</p>
                <p className="num">{(pol.data.active.policy.post_times as string[]).join("・")}</p>
              </div>
            </div>
          </section>

          <section className="space-y-2">
            <div className="flex items-center gap-2">
              <h3 className="panel-title">改善実験</h3>
              {admin && running && <Button className="ml-auto text-xs" onClick={() => void act("実験の停止", () => c.client!.post("experiments/stop"))}>実行中の実験を停止</Button>}
            </div>
            {exps.error ? <ErrorNote>{exps.error}</ErrorNote> : !exps.data ? <Skeleton /> : !exps.data.items.length ? <Empty>まだ実験はありません（実績が集まると自動で開始します）</Empty> : (
              <ul className="space-y-2">{exps.data.items.map((e) => {
                const r = e.result;
                return (
                  <li key={e.id} className="rounded-lg border border-line/60 p-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone={EXP[e.status]?.tone ?? "muted"}>{EXP[e.status]?.label ?? e.status}</Badge>
                      <span>#{e.id} {VAR[e.variable] ?? e.variable}：{e.control_value} → {e.treatment_value}</span>
                      <span className="num ml-auto text-xs text-muted">{fmtTime(e.started_at)}〜{e.ended_at ? fmtTime(e.ended_at) : ""}</span>
                    </div>
                    <p className="mt-1 text-xs text-muted">仮説：{e.hypothesis}</p>
                    {r && (
                      <p className="num mt-1 text-xs">
                        対照 n={r.n_control ?? 0}・反応率 {fmtPct(r.mean_control ?? null, 2)} ／ 試行 n={r.n_treatment ?? 0}・反応率 {fmtPct(r.mean_treatment ?? null, 2)}
                        {r.lift !== null && r.lift !== undefined && ` ／ 差 ${fmtPct(r.lift, 0)}`}
                      </p>
                    )}
                    {r?.note && <p className="mt-1 text-xs text-muted">{r.note}</p>}
                  </li>
                );
              })}</ul>
            )}
          </section>

          <section className="space-y-2">
            <h3 className="panel-title">変更履歴</h3>
            <ul className="divide-y divide-line/60">{pol.data.versions.map((v) => (
              <li key={v.version} className="flex flex-wrap items-center gap-2 py-2">
                <Badge tone={v.is_active ? "accent" : "muted"}>v{v.version}{v.is_active ? "（有効）" : ""}</Badge>
                <span className="text-xs text-muted">{SRC[v.source]}</span>
                <span className="min-w-0 flex-1 truncate text-xs">{v.reason}</span>
                <span className="num text-xs text-muted">{fmtTime(v.created_at)}</span>
                {admin && !v.is_active && <Button className="min-h-7 px-2 text-xs" onClick={() => setRb(v.version)}>この版に戻す</Button>}
              </li>))}</ul>
          </section>
        </div>
      )}
      <Confirm open={rb !== null} title={`v${rb}に差し戻しますか？`} confirmLabel="差し戻す" onCancel={() => setRb(null)}
        body="選んだ版の内容で新しい版を作り、次回の投稿生成から適用します。履歴は残ります。"
        onConfirm={() => { const v = rb; setRb(null); void act("差し戻し", () => c.client!.post("policy/rollback", { version: v }), (r) => `v${(r as { new_version: number }).new_version}として差し戻しました`); }} />
    </Drawer>
  );
}
