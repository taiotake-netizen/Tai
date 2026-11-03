"use client";

import {
  Activity, BarChart3, Bot, Brain, CalendarClock, FileText, FlaskConical, Lightbulb, LogOut, Megaphone, Pause, Play,
  PlugZap, Power, RefreshCw, Send, Settings, Sparkles, Square,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, sessionApi } from "@/lib/client/api";
import { useConsole, type ConsoleState } from "@/lib/client/useConsole";
import { CORE_LABEL } from "@/lib/coreState";
import { AGENT_STATE, kindLabel, fmtNum, fmtPct, fmtRelative, fmtTime, fmtUsd, JOB_STATUS, POST_STATUS, type Tone } from "@/lib/format";
import type { Agent, EventItem, Job, Post } from "@/lib/types";
import { CoreStage } from "./core/CoreStage";
import { CoreHud, HudStrip } from "./Hud";
import { OrgChart } from "./OrgChart";
import { AssistantDrawer } from "./drawers/AssistantDrawer";
import { IdeasDrawer } from "./drawers/IdeasDrawer";
import { ImprovementDrawer } from "./drawers/ImprovementDrawer";
import { PostDrawer } from "./drawers/PostDrawer";
import { ReportsDrawer } from "./drawers/ReportsDrawer";
import { SettingsDrawer } from "./drawers/SettingsDrawer";
import { Badge, Button, Confirm, Empty, ErrorNote, Panel, Skeleton, Toasts, type ToastMsg } from "./ui/primitives";

export type Act = (label: string, fn: () => Promise<unknown>, okText?: (r: unknown) => string) => Promise<boolean>;
type DrawerKey = "ideas" | "improvement" | "reports" | "settings" | "assistant" | `post:${number}` | null;

const AGENT_ICON: Record<string, typeof Bot> = { orchestrator: Megaphone, threads_ops: Send, content: Sparkles, analytics: BarChart3 };

export function Console() {
  const c = useConsole();
  const [toasts, setToasts] = useState<ToastMsg[]>([]);
  const [drawer, setDrawer] = useState<DrawerKey>(null);
  const [confirm, setConfirm] = useState<null | { title: string; body: string; label: string; danger?: boolean; run: () => void }>(null);

  const toast = useCallback((tone: Tone, text: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t.slice(-3), { id, tone, text }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 6000);
  }, []);

  const act: Act = useCallback(async (label, fn, okText) => {
    try {
      const r = await fn();
      toast("ok", okText ? okText(r) : `${label}：受け付けました`);
      await c.refreshOverview();
      c.bump();
      return true;
    } catch (e) {
      toast("error", `${label}：${e instanceof ApiError ? e.message : "失敗しました"}`);
      return false;
    }
  }, [toast, c]);

  if (c.loading && !c.overview) {
    return <main className="mx-auto max-w-[1600px] p-4"><Panel><Skeleton lines={6} /></Panel></main>;
  }
  if (c.session && !c.account) {
    return <main className="mx-auto max-w-xl p-6"><ErrorNote>このユーザーに割り当てられたアカウントがありません（CC_USERS の accounts を確認してください）。</ErrorNote></main>;
  }

  return (
    <div className="mx-auto max-w-[1600px] px-3 pb-10 sm:px-4">
      <Header c={c} onOpen={setDrawer} />
      <HudStrip c={c} />
      {c.error && !c.overview && (
        <div className="mb-3"><ErrorNote>{c.error}</ErrorNote></div>
      )}
      {c.session?.mode === "demo" && c.client && <DemoBar c={c} act={act} />}
      <main className="grid gap-3 lg:grid-cols-[minmax(240px,300px)_minmax(0,1fr)_minmax(260px,340px)]">
        <div className="order-2 min-w-0 lg:order-1">
          <AgentColumn c={c} />
        </div>
        <div className="order-1 min-w-0 lg:order-2">
          <CorePanel c={c} act={act} askConfirm={setConfirm} />
        </div>
        <div className="order-3 min-w-0">
          <ActivityFeed events={c.events} reachable={c.reachable} onPost={(id) => setDrawer(`post:${id}`)} />
        </div>
      </main>
      <div className="mt-3 grid gap-3">
        <OrgChart c={c} />
        <KpiRow c={c} />
        <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <PostsPanel c={c} onOpen={(id) => setDrawer(`post:${id}`)} />
          <div className="grid min-w-0 gap-3">
            <Connections c={c} act={act} />
            <TasksPanel c={c} act={act} />
          </div>
        </div>
      </div>

      {c.client && (
        <>
          <IdeasDrawer open={drawer === "ideas"} onClose={() => setDrawer(null)} c={c} act={act} />
          <ImprovementDrawer open={drawer === "improvement"} onClose={() => setDrawer(null)} c={c} act={act} />
          <ReportsDrawer open={drawer === "reports"} onClose={() => setDrawer(null)} c={c} act={act} />
          <SettingsDrawer open={drawer === "settings"} onClose={() => setDrawer(null)} c={c} act={act} />
          <AssistantDrawer open={drawer === "assistant"} onClose={() => setDrawer(null)} c={c} act={act}
            onOpenPost={(id) => setDrawer(`post:${id}`)} />
          <PostDrawer postId={drawer?.startsWith("post:") ? Number(drawer.slice(5)) : null} onClose={() => setDrawer(null)} c={c} act={act} />
        </>
      )}
      <Confirm open={!!confirm} title={confirm?.title ?? ""} body={confirm?.body ?? ""} confirmLabel={confirm?.label ?? "OK"}
        danger={confirm?.danger} onCancel={() => setConfirm(null)} onConfirm={() => { confirm?.run(); setConfirm(null); }} />
      <Toasts items={toasts} onDismiss={(id) => setToasts((t) => t.filter((x) => x.id !== id))} />
    </div>
  );
}

// ------------------------------------------------------------------ header

function overall(c: ConsoleState): { tone: Tone; label: string } {
  const o = c.overview;
  if (!c.reachable || !o) return { tone: "error", label: "接続待ち" };
  if (!o.runtime.scheduler_alive || !o.runtime.worker_alive) return { tone: "error", label: "エンジン停止" };
  if (o.attention.some((a) => a.status === "unknown" || a.status === "failed")) return { tone: "warn", label: "要確認あり" };
  if (!o.autopilot_enabled) return { tone: "muted", label: "自動運用OFF" };
  return { tone: "ok", label: "正常稼働" };
}

function Header({ c, onOpen }: { c: ConsoleState; onOpen: (k: DrawerKey) => void }) {
  const router = useRouter();
  const st = overall(c);
  const data = c.session?.mode === "demo" ? { tone: "warn" as Tone, label: "デモデータ" }
    : c.overview?.mode.data === "live" ? (c.overview.mode.live_publishing ? { tone: "ok" as Tone, label: "実データ・本番投稿ON" }
      : { tone: "accent" as Tone, label: "実データ・本番投稿OFF" })
    : c.overview ? { tone: "warn" as Tone, label: "テスト（実投稿なし）" } : { tone: "muted" as Tone, label: "—" };
  const nav: { k: DrawerKey; label: string; icon: typeof Bot }[] = [
    { k: "ideas", label: "ネタ", icon: Lightbulb },
    { k: "improvement", label: "改善", icon: FlaskConical },
    { k: "reports", label: "レポート", icon: FileText },
    { k: "assistant", label: "AI補助", icon: Brain },
    { k: "settings", label: "設定", icon: Settings },
  ];
  return (
    <header className="flex flex-wrap items-center gap-x-4 gap-y-2 py-3">
      <div className="flex min-w-0 items-center gap-3">
        <span className="relative grid size-9 place-items-center" aria-hidden>
          <svg viewBox="0 0 36 36" className="absolute inset-0"><polygon points="18,1.5 32.3,9.75 32.3,26.25 18,34.5 3.7,26.25 3.7,9.75" fill="rgb(0 217 255 / 0.08)" stroke="#00D9FF" strokeOpacity="0.7" /></svg>
          <Activity className="relative size-4 text-accent" />
        </span>
        <div className="min-w-0">
          <h1 className="hud text-[15px] font-semibold tracking-[0.3em] text-text [text-shadow:0_0_16px_rgba(0,217,255,0.35)]">AI CONTROL CENTER</h1>
          <p className="truncate text-[11px] text-muted">{c.overview?.account.display_name ?? c.account ?? ""}</p>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2" aria-live="polite">
        <Badge tone={st.tone}>{st.label}</Badge>
        <Badge tone={data.tone}>{data.label}</Badge>
        <span className="text-[11px] text-muted">最終同期 <span className="num">{fmtTime(c.lastSync, false)}</span></span>
      </div>
      <nav className="ml-auto flex flex-wrap items-center gap-1" aria-label="詳細メニュー">
        {nav.map((n) => (
          <Button key={n.label} variant="ghost" onClick={() => onOpen(n.k)}>
            <n.icon className="size-4" aria-hidden /><span>{n.label}</span>
          </Button>
        ))}
        {c.session && c.session.accounts.length > 1 && (
          <select aria-label="アカウント" className="rounded-lg border border-line bg-panel px-2 py-1.5 text-sm"
            value={c.account ?? ""} onChange={(e) => c.setAccount(e.target.value)}>
            {c.session.accounts.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        )}
        <Button variant="ghost" aria-label="ログアウト" onClick={async () => { await sessionApi.logout().catch(() => null); router.replace("/login"); router.refresh(); }}>
          <LogOut className="size-4" aria-hidden />
        </Button>
      </nav>
    </header>
  );
}

function DemoBar({ c, act }: { c: ConsoleState; act: Act }) {
  const run = (name: string, label: string) => act(label, () => c.client!.post("demo/scenario", { name }),
    (r) => (r as { message?: string }).message ?? label);
  const items: [string, string][] = [
    ["generate_now", "生成を開始"], ["publish_now", "今すぐテスト公開"], ["fail_publish", "公開失敗を再現"],
    ["unknown_publish", "結果不明を再現"], ["advance_metrics", "実績取得を前倒し"], ["run_analysis", "分析を実行"],
    ["run_reports", "レポート再生成"], ["disconnect", "切断を再現"],
  ];
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2 rounded-xl border border-warn/30 bg-warn/5 px-3 py-2">
      <span className="text-xs text-warn">デモ操作（外部APIは呼ばれません）</span>
      {items.map(([n, l]) => <Button key={n} className="min-h-8 text-xs" onClick={() => void run(n, l)}>{l}</Button>)}
    </div>
  );
}

// ------------------------------------------------------------------ agents

function AgentColumn({ c }: { c: ConsoleState }) {
  const agents = c.overview?.agents;
  return (
    <Panel title="担当" id="agents-title">
      {!agents ? <Skeleton lines={4} /> : (
        <ul className="flex gap-2 overflow-x-auto pb-1 lg:flex-col lg:overflow-visible">
          {agents.map((a) => <AgentCard key={a.id} a={a} selected={c.selected === a.id}
            onSelect={() => c.setSelected(c.selected === a.id ? null : a.id)} />)}
        </ul>
      )}
    </Panel>
  );
}

function AgentCard({ a, selected, onSelect }: { a: Agent; selected: boolean; onSelect: () => void }) {
  const Icon = AGENT_ICON[a.id] ?? Bot;
  const st = AGENT_STATE[a.state];
  return (
    <li className="min-w-[230px] lg:min-w-0">
      <button onClick={onSelect} aria-pressed={selected}
        className={`w-full rounded-xl border p-3 text-left transition-colors ${selected ? "border-accent/60 bg-accent/[0.07] shadow-[0_0_24px_-8px_rgba(0,217,255,0.5)]" : "border-line bg-panel-2/60 hover:border-[#24507c]"}`}>
        <div className="flex items-center gap-2">
          <Icon className={`size-4 ${a.state === "running" ? "text-accent" : "text-muted"}`} aria-hidden />
          <span className="text-sm font-medium">{a.name}</span>
          <span className="ml-auto"><Badge tone={st.tone} spin={a.state === "running"}>{st.label}</Badge></span>
        </div>
        <p className="mt-1 text-xs text-muted">{a.role}</p>
        <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 text-[11px]">
          <dt className="text-muted">接続</dt><dd className="truncate">{a.tool ?? "—"}</dd>
          <dt className="text-muted">待機</dt><dd className="num">{a.queued}件</dd>
          {a.running[0] && (<><dt className="text-muted">処理</dt><dd className="truncate">#{a.running[0].id} {kindLabel(a.running[0].kind)}</dd></>)}
        </dl>
        {a.reason && <p className="mt-1.5 text-[11px] text-warn">{a.reason}</p>}
        {a.state === "error" && a.last?.last_error && <p className="mt-1 line-clamp-2 text-[11px] text-error">{a.last.last_error}</p>}
      </button>
    </li>
  );
}

// ------------------------------------------------------------------ core

function CorePanel({ c, act, askConfirm }: { c: ConsoleState; act: Act; askConfirm: (x: { title: string; body: string; label: string; danger?: boolean; run: () => void }) => void }) {
  const o = c.overview;
  const sel = o?.agents.find((a) => a.id === c.selected) ?? null;
  const running = (sel ? [sel] : o?.agents ?? []).flatMap((a) => a.running.map((r) => ({ ...r, agent: a.name })));
  const [compact, setCompact] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 767px)");
    const f = () => setCompact(mq.matches);
    f();
    mq.addEventListener("change", f);
    return () => mq.removeEventListener("change", f);
  }, []);
  const canWrite = c.session?.role === "admin";
  return (
    <section className="panel relative overflow-hidden" aria-label="AIコアと現在の処理">
      <div className="relative">
        <CoreStage visual={c.core} pulseKey={c.pulse?.id ?? null} compact={compact} />
        {!compact && <CoreHud c={c} />}
      </div>
      <div className="pointer-events-none absolute inset-x-0 top-0 flex items-start justify-between p-4">
        <div>
          <p className="panel-title">{sel ? sel.name : "AI CORE · 全体"}</p>
          <p className="mt-1 text-xl font-medium tracking-wide [text-shadow:0_0_18px_rgba(0,217,255,0.45)]" aria-live="polite">{CORE_LABEL[c.core]}</p>
          {c.selected && <span className="pointer-events-auto mt-1 inline-block"><Button variant="ghost" className="-ml-3 text-xs" onClick={() => c.setSelected(null)}>全体表示に戻す</Button></span>}
        </div>
      </div>
      <div className="relative border-t border-line/70 bg-[#07111f]/70 p-4 backdrop-blur-sm">
        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
          <div className="min-w-0 space-y-1 text-sm">
            <p className="panel-title">現在の処理</p>
            {!o ? <p className="text-muted">—</p> : running.length ? running.slice(0, 3).map((r) => (
              <p key={r.id} className="truncate"><span className="text-accent">●</span> {r.agent}：{kindLabel(r.kind)}（#{r.id}・{fmtRelative(r.started_at)}開始）</p>
            )) : (
              <p className="text-muted">
                処理中のジョブはありません。次の投稿 <span className="num text-text">{fmtTime(o.next.next_post?.slot_at)}</span>
                ／次の分析 <span className="num text-text">{fmtTime(o.next.next_analysis_at)}</span>
              </p>
            )}
          </div>
          {o && canWrite && (
            <div className="flex flex-wrap items-center gap-2 md:justify-end">
              {o.autopilot_enabled ? (
                <>
                  <Button onClick={() => askConfirm({ title: "予約を停止しますか？", label: "予約停止", run: () => void act("予約停止",
                    () => c.client!.post("control/stop", { mode: "pause_schedule" }), () => "自動運用をOFFにしました（公開済み投稿には影響しません）"),
                    body: "新しい投稿枠の作成と、予約済み投稿の公開を止めます。待機中のジョブは残ります。公開済みの投稿は取り消されません。" })}>
                    <Pause className="size-4" aria-hidden />予約停止
                  </Button>
                  <Button variant="danger" onClick={() => askConfirm({ title: "待機中の処理もすべて取り消しますか？", danger: true, label: "停止して取消",
                    body: "自動運用をOFFにし、待機中のジョブと未公開の投稿予定を取り消します。実行中の処理には取消要求を出します（Threadsへ公開中の処理は取り消せません）。",
                    run: () => void act("停止と取消", () => c.client!.post("control/stop", { mode: "cancel_queued" }), (r) => {
                      const x = r as { jobs_cancelled?: number; cancel_requested?: number; not_cancellable?: unknown[] };
                      return `取消完了 ${x.jobs_cancelled ?? 0}件／取消要求 ${x.cancel_requested ?? 0}件／取消不可 ${x.not_cancellable?.length ?? 0}件`;
                    }) })}>
                    <Square className="size-4" aria-hidden />停止＋取消
                  </Button>
                </>
              ) : (
                <Button variant="primary" onClick={() => askConfirm({ title: "自動運用を開始しますか？", label: "開始",
                  body: o.mode.live_publishing ? "本番投稿が有効です。設定された時刻にThreadsへ実際に投稿されます。"
                    : "本番投稿は無効のため、テスト投稿（実際には投稿しない）として運用します。",
                  run: () => void act("自動運用開始", () => c.client!.post("control/autopilot", { enabled: true }), () => "自動運用をONにしました") })}>
                  <Play className="size-4" aria-hidden />自動運用を開始
                </Button>
              )}
              <Button onClick={() => void act(o.improvement_enabled ? "自動改善の停止" : "自動改善の再開",
                () => c.client!.post("control/improvement", { enabled: !o.improvement_enabled }))}>
                <FlaskConical className="size-4" aria-hidden />自動改善{o.improvement_enabled ? "を停止" : "を再開"}
              </Button>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ activity

const SEV: Record<string, Tone> = { info: "muted", success: "ok", warning: "warn", error: "error" };
const SEV_LABEL: Record<string, string> = { info: "情報", success: "成功", warning: "注意", error: "エラー" };

function ActivityFeed({ events, reachable, onPost }: { events: EventItem[]; reachable: boolean; onPost: (id: number) => void }) {
  const items = useMemo(() => [...events].reverse().slice(0, 60), [events]);
  return (
    <Panel title="直近のアクティビティ" id="activity-title" className="flex h-full max-h-[380px] flex-col lg:max-h-[620px]"
      action={!reachable ? <Badge tone="error">更新停止中</Badge> : undefined}>
      {!items.length ? <Empty>まだアクティビティはありません</Empty> : (
        <ol className="scroll-thin -mr-2 min-h-0 flex-1 space-y-2 overflow-y-auto pr-2">
          {items.map((e) => (
            <li key={e.event_id} className="rounded-lg border border-line/60 bg-white/[0.02] px-2.5 py-2">
              <div className="flex items-center gap-2 text-[11px] text-muted">
                <Badge tone={SEV[e.severity]}>{SEV_LABEL[e.severity]}</Badge>
                <time className="num" dateTime={e.occurred_at}>{fmtTime(e.occurred_at)}</time>
                {e.post_id && <button className="ml-auto text-accent hover:underline" onClick={() => onPost(e.post_id!)}>投稿#{e.post_id}</button>}
              </div>
              <p className="mt-1 break-words text-[13px] leading-snug">{e.message}</p>
            </li>
          ))}
        </ol>
      )}
    </Panel>
  );
}

// ------------------------------------------------------------------ KPI

function KpiRow({ c }: { c: ConsoleState }) {
  const o = c.overview;
  const k = o?.kpi;
  const stale = k?.metrics_7d.last_observed_at && o
    ? (new Date(o.generated_at).getTime() - new Date(k.metrics_7d.last_observed_at).getTime()) > 36 * 3600e3 : false;
  const tiles: { label: string; value: string; sub?: string }[] = k && o ? [
    { label: "本日の投稿", value: fmtNum(k.published_today), sub: `試行 成功${k.publish_attempts_today.success}／失敗${k.publish_attempts_today.failed}／不明${k.publish_attempts_today.unknown}` },
    { label: "本日の成功率", value: fmtPct(k.success_rate_today, 0), sub: "成功÷(成功+失敗)" },
    { label: "7日間の閲覧", value: fmtNum(k.metrics_7d.views), sub: `${k.metrics_7d.posts}件分（取得済みのみ）` },
    { label: "7日間の反応率", value: fmtPct(k.metrics_7d.er, 2), sub: `最終取得 ${fmtTime(k.metrics_7d.last_observed_at)}${stale ? "（古いデータ）" : ""}` },
    { label: "承認待ち", value: fmtNum(k.pending_approvals), sub: o.require_approval ? "投稿前承認ON" : "投稿前承認OFF" },
    { label: "使えるネタ", value: fmtNum(k.ideas_ready), sub: "未使用・利用可" },
    { label: "AI費用（今日／今月）", value: `${fmtUsd(o.budget.today_usd)} / ${fmtUsd(o.budget.month_usd)}`,
      sub: o.llm.provider === "mock" ? "デモ用ローカル生成（費用なし）" : o.budget.budget_configured ?`上限 ${fmtUsd(o.budget.daily_limit_usd)} / ${fmtUsd(o.budget.monthly_limit_usd)}（推定）` : "予算未設定（AI処理停止中）" },
  ] : [];
  return (
    <section aria-label="主要指標" className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-7">
      {!k ? Array.from({ length: 7 }).map((_, i) => <div key={i} className="panel h-[86px] animate-pulse" />) : tiles.map((t) => (
        <div key={t.label} className="panel min-w-0 overflow-hidden px-3 py-2.5">
          <span className="absolute inset-x-3 top-0 h-px bg-gradient-to-r from-transparent via-accent/60 to-transparent" aria-hidden />
          <p className="truncate text-[11px] text-muted">{t.label}</p>
          <p className="num mt-0.5 truncate text-[22px] [text-shadow:0_0_14px_rgba(0,217,255,0.25)]">{t.value}</p>
          {t.sub && <p className="mt-0.5 truncate text-[10px] text-muted" title={t.sub}>{t.sub}</p>}
        </div>
      ))}
    </section>
  );
}

// ------------------------------------------------------------------ connections

function Connections({ c, act }: { c: ConsoleState; act: Act }) {
  const o = c.overview;
  if (!o) return <Panel title="接続"><Skeleton /></Panel>;
  const threadsTone: Tone = o.account.data_scope !== "live" ? "muted" : o.account.connection_status === "connected" ? "ok"
    : o.account.connection_status === "not_configured" ? "warn" : "error";
  const rows: { name: string; icon: typeof Bot; tone: Tone; status: string; detail: string }[] = [
    { name: "Threads", icon: Send, tone: threadsTone,
      status: o.account.data_scope !== "live" ? "接続しない（デモ/テスト）" : ({ connected: "接続済み", not_configured: "未設定", expired: "トークン期限切れ", error: "エラー" } as Record<string, string>)[o.account.connection_status] ?? o.account.connection_status,
      detail: o.mode.live_publishing ? "本番投稿ON" : `本番投稿OFF（${o.mode.publish_mode}）` },
    { name: "AIモデル", icon: Brain, tone: o.llm.available ? "ok" : "warn", status: o.llm.available ? "利用可" : "利用不可",
      detail: o.llm.reason ?? `${o.llm.provider}${o.llm.model ? ` / ${o.llm.model}` : ""}` },
    { name: "スケジューラー", icon: CalendarClock, tone: o.runtime.scheduler_alive ? "ok" : "error", status: o.runtime.scheduler_alive ? "稼働" : "停止",
      detail: `最終実行 ${fmtTime(o.runtime.scheduler_last_tick)}` },
    { name: "ワーカー", icon: Power, tone: o.runtime.worker_alive ? "ok" : "error", status: o.runtime.worker_alive ? "稼働" : "停止",
      detail: `最終応答 ${fmtTime(o.runtime.worker_last_seen)}` },
  ];
  return (
    <Panel title="SNS・システム接続" action={o.account.data_scope === "live" && c.can("connection.check").enabled ? (
      <Button className="text-xs" onClick={() => void act("接続確認", () => c.client!.post("connection/check"))}><PlugZap className="size-4" aria-hidden />接続確認</Button>) : undefined}>
      <ul className="grid gap-2 sm:grid-cols-2">
        {rows.map((r) => (
          <li key={r.name} className="flex min-w-0 items-start gap-2 rounded-lg border border-line/60 px-3 py-2">
            <r.icon className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2"><span className="text-sm">{r.name}</span><Badge tone={r.tone}>{r.status}</Badge></div>
              <p className="truncate text-[11px] text-muted" title={r.detail}>{r.detail}</p>
            </div>
          </li>
        ))}
      </ul>
      {o.account.connection_error && <p className="mt-2 text-xs text-error">{o.account.connection_error}</p>}
    </Panel>
  );
}

// ------------------------------------------------------------------ tasks

function TasksPanel({ c, act }: { c: ConsoleState; act: Act }) {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [filter, setFilter] = useState<"active" | "failed" | "all">("active");
  useEffect(() => {
    if (!c.client) return;
    let alive = true;
    const q = filter === "failed" ? "jobs?status=failed&limit=30" : "jobs?limit=40";
    c.client.get<{ items: Job[] }>(q).then((r) => { if (alive) { setJobs(r.items); setErr(null); } })
      .catch((e: unknown) => { if (alive) setErr(e instanceof ApiError ? e.message : "取得に失敗しました"); });
    return () => { alive = false; };
  }, [c.client, c.version, filter]);
  const shown = (jobs ?? []).filter((j) => filter !== "active" || ["queued", "running", "cancel_requested", "failed"].includes(j.status)).slice(0, 12);
  return (
    <Panel title="タスク" action={
      <div className="flex gap-1" role="tablist" aria-label="タスクの絞り込み">
        {(["active", "failed", "all"] as const).map((f) => (
          <Button key={f} variant={filter === f ? "primary" : "ghost"} className="min-h-7 px-2 text-xs" role="tab" aria-selected={filter === f}
            onClick={() => setFilter(f)}>{{ active: "進行中", failed: "失敗", all: "すべて" }[f]}</Button>
        ))}
      </div>}>
      {err ? <ErrorNote>{err}</ErrorNote> : !jobs ? <Skeleton /> : !shown.length ? <Empty>該当するタスクはありません</Empty> : (
        <ul className="divide-y divide-line/60">
          {shown.map((j) => {
            const st = JOB_STATUS[j.status] ?? { label: j.status, tone: "muted" as Tone };
            const cancellable = ["queued", "running"].includes(j.status) && !(j.status === "running" && j.kind === "publish_post");
            return (
              <li key={j.id} className="flex flex-wrap items-center gap-2 py-2 text-sm">
                <Badge tone={st.tone} spin={j.status === "running"}>{st.label}</Badge>
                <span className="min-w-0 flex-1 truncate">{j.label}<span className="num ml-1 text-xs text-muted">#{j.id}</span></span>
                <span className="num text-xs text-muted">{fmtTime(j.run_at)}</span>
                {c.session?.role === "admin" && cancellable && <Button className="min-h-7 px-2 text-xs" onClick={() => void act("取消", () => c.client!.post(`jobs/${j.id}/cancel`),
                  (r) => (r as { message?: string }).message ?? "取消しました")}>取消</Button>}
                {c.session?.role === "admin" && ["failed", "cancelled"].includes(j.status) && j.kind !== "publish_post" && (
                  <Button className="min-h-7 px-2 text-xs" onClick={() => void act("再試行", () => c.client!.post(`jobs/${j.id}/retry`))}>
                    <RefreshCw className="size-3" aria-hidden />再試行</Button>)}
                {j.last_error && <p className="w-full truncate text-[11px] text-error" title={j.last_error}>{j.last_error}</p>}
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}

// ------------------------------------------------------------------ posts

function PostsPanel({ c, onOpen }: { c: ConsoleState; onOpen: (id: number) => void }) {
  const [view, setView] = useState<"upcoming" | "history" | "attention">("upcoming");
  const [posts, setPosts] = useState<Post[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (!c.client) return;
    let alive = true;
    c.client.get<{ items: Post[] }>(`posts?view=${view}&limit=30`).then((r) => { if (alive) { setPosts(r.items); setErr(null); } })
      .catch((e: unknown) => { if (alive) setErr(e instanceof ApiError ? e.message : "取得に失敗しました"); });
    return () => { alive = false; };
  }, [c.client, c.version, view]);
  return (
    <Panel title="投稿予定・履歴" action={
      <div className="flex gap-1" role="tablist" aria-label="投稿の表示切替">
        {(["upcoming", "history", "attention"] as const).map((v) => (
          <Button key={v} variant={view === v ? "primary" : "ghost"} className="min-h-7 px-2 text-xs" role="tab" aria-selected={view === v}
            onClick={() => { setPosts(null); setView(v); }}>{{ upcoming: "予定", history: "履歴", attention: "要対応" }[v]}</Button>
        ))}
      </div>}>
      {err ? <ErrorNote>{err}</ErrorNote> : !posts ? <Skeleton lines={5} /> : !posts.length ? (
        <Empty>{view === "upcoming" ? "予定されている投稿はありません（自動運用OFFの場合は枠が作られません）" : view === "history" ? "履歴はまだありません" : "対応が必要な投稿はありません"}</Empty>
      ) : (
        <ul className="divide-y divide-line/60">
          {posts.map((p) => {
            const st = POST_STATUS[p.status] ?? { label: p.status, tone: "muted" as Tone };
            const m = p.latest_metrics;
            return (
              <li key={p.id}>
                <button className="flex w-full items-start gap-3 py-2.5 text-left hover:bg-white/[0.02]" onClick={() => onOpen(p.id)}>
                  <span className="num w-[86px] shrink-0 pt-0.5 text-xs text-muted">{fmtTime(p.published_at ?? p.slot_at)}</span>
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-1.5">
                      <Badge tone={st.tone} spin={p.status === "generating" || p.status === "publishing"}>{st.label}</Badge>
                      {p.is_test ? <Badge tone="muted">テスト</Badge> : null}
                      {p.experiment_arm && <Badge tone="accent">実験:{p.experiment_arm === "treatment" ? "試行" : "対照"}</Badge>}
                      {p.theme && <span className="truncate text-xs text-muted">{p.theme}／{p.hook_style}</span>}
                    </span>
                    <span className="mt-1 line-clamp-2 block break-words text-[13px] text-text/90">{p.text ?? p.last_error ?? "（未生成）"}</span>
                  </span>
                  {m && <span className="num hidden shrink-0 text-right text-[11px] text-muted sm:block">
                    {m.status === "ok" ? <>閲覧 {fmtNum(m.views)}<br />いいね {fmtNum(m.likes)}</> : <span className="text-warn">実績{m.status === "failed" ? "取得失敗" : "未提供"}</span>}
                  </span>}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
