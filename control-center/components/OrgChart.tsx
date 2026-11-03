"use client";

/**
 * AI organisation chart (detailed). Every node reflects real engine state from /overview:
 *  owner → AI統括 (CEO) → departments → teams → concrete steps, plus the infrastructure each department runs on.
 *  - a step is "active" while a job of its kind is running
 *  - numbers are engine counts (24h unless stated), never placeholders
 * Connection lines carry moving light only while work flows through them.
 */
import { BarChart3, Bot, Brain, Crown, Database, Megaphone, Send, Sparkles, type LucideIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { ConsoleState } from "@/lib/client/useConsole";
import { AGENT_STATE, fmtNum, fmtTime, fmtUsd, kindLabel } from "@/lib/format";
import type { Agent, EventItem, Overview } from "@/lib/types";
import { Badge } from "./ui/primitives";

type Unit = { id: string; label: string; kinds: string[]; value: (o: Overview) => string; alert?: (o: Overview) => boolean; always?: (o: Overview) => boolean };
type Team = { id: string; name: string; units: Unit[] };

const st = (o: Overview, k: string, f: "succeeded" | "failed" = "succeeded") => o.job_stats_24h?.[k]?.[f] ?? 0;
const pc = (o: Overview, s: string) => o.pipeline?.post_counts?.[s] ?? 0;

const TEAMS: Record<"content" | "threads_ops" | "analytics", Team[]> = {
  content: [
    { id: "plan", name: "企画チーム", units: [
      { id: "idea-pick", label: "ネタ選択", kinds: ["generate_post"], value: (o) => `利用可 ${o.kpi.ideas_ready}` },
      { id: "idea-refill", label: "ネタ補充", kinds: ["refill_ideas"], value: (o) => `24h +${o.pipeline?.ideas_added ?? 0}` },
    ] },
    { id: "write", name: "制作チーム", units: [
      { id: "gen", label: "文章生成", kinds: ["generate_post"], value: (o) => `24h ${st(o, "generate_post")}` },
      { id: "rule", label: "ルールチェック", kinds: ["generate_post"],
        value: (o) => `合格${o.pipeline?.generation_checks.passed ?? 0}／不合格${o.pipeline?.generation_checks.rejected ?? 0}`,
        alert: (o) => (o.pipeline?.generation_checks.rejected ?? 0) > (o.pipeline?.generation_checks.passed ?? 0) },
      { id: "review", label: "AI審査", kinds: ["generate_post"], value: (o) => (o.llm.available ? "有効" : "停止") },
      { id: "approval", label: "承認待ち", kinds: [], value: (o) => `${o.kpi.pending_approvals}件`, alert: (o) => o.kpi.pending_approvals > 0 },
    ] },
    { id: "assist", name: "補助チーム", units: [
      { id: "assistant", label: "AI補助（要約・下書き・改善案）", kinds: ["assistant"], value: (o) => `24h ${st(o, "assistant")}` },
    ] },
  ],
  threads_ops: [
    { id: "publish", name: "公開チーム", units: [
      { id: "queue", label: "予約管理", kinds: [], value: (o) => `予約 ${pc(o, "scheduled")}` },
      { id: "pub", label: "投稿公開", kinds: ["publish_post"], value: (o) => `24h ${st(o, "publish_post")}`, alert: (o) => st(o, "publish_post", "failed") > 0 },
      { id: "recon", label: "結果照会", kinds: ["reconcile_post"], value: (o) => `不明 ${pc(o, "unknown")}`, alert: (o) => pc(o, "unknown") > 0 },
    ] },
    { id: "measure", name: "計測チーム", units: [
      { id: "m24", label: "実績取得（24時間後）", kinds: ["collect_metrics"], value: (o) => `24h ${o.pipeline?.metrics_by_bucket?.["24"] ?? 0}` },
      { id: "m72", label: "実績取得（72時間後）", kinds: ["collect_metrics"], value: (o) => `24h ${o.pipeline?.metrics_by_bucket?.["72"] ?? 0}` },
      { id: "conn", label: "接続確認", kinds: ["check_connection"],
        value: (o) => (o.account.data_scope !== "live" ? "対象外" : ({ connected: "接続済み", not_configured: "未設定", expired: "期限切れ", error: "エラー" } as Record<string, string>)[o.account.connection_status] ?? o.account.connection_status),
        alert: (o) => o.account.data_scope === "live" && o.account.connection_status !== "connected" },
    ] },
  ],
  analytics: [
    { id: "analyze", name: "分析チーム", units: [
      { id: "agg", label: "データ集計", kinds: ["analyze"], value: (o) => `比較可能 ${o.pipeline?.analysis_samples ?? 0}件` },
      { id: "exp", label: "改善実験", kinds: ["analyze"], value: (o) => (o.experiment ? `#${o.experiment.id} 実験中` : "なし") },
      { id: "policy", label: "方針更新", kinds: ["analyze"], value: (o) => `v${o.policy.version}` },
      { id: "rollback", label: "自動差し戻し監視", kinds: ["analyze"], value: (o) => (o.improvement_enabled ? "監視中" : "停止") },
    ] },
    { id: "report", name: "報告チーム", units: [
      { id: "daily", label: "日次レポート", kinds: ["daily_report"], value: (o) => `24h ${st(o, "daily_report")}` },
      { id: "weekly", label: "週次レポート", kinds: ["weekly_report"], value: (o) => `24h ${st(o, "weekly_report")}` },
    ] },
  ],
};

const HQ: Unit[] = [
  { id: "sched", label: "スケジュール作成", kinds: [], value: (o) => (o.runtime.scheduler_alive ? "稼働" : "停止"),
    always: (o) => o.runtime.scheduler_alive, alert: (o) => !o.runtime.scheduler_alive },
  { id: "slots", label: "投稿枠", kinds: [], value: (o) => `次 ${fmtTime(o.next.next_post?.slot_at, false).slice(0, 5)}` },
  { id: "budget", label: "予算管理", kinds: [], value: (o) => (o.llm.provider === "mock" ? "費用なし" : o.budget.budget_configured ? fmtUsd(o.budget.today_usd) : "未設定"),
    alert: (o) => o.llm.provider !== "mock" && !o.budget.budget_configured },
  { id: "audit", label: "監査ログ", kinds: [], value: (o) => `24h ${o.pipeline?.audit_entries ?? 0}` },
];

const DEPTS = ["content", "threads_ops", "analytics"] as const;
const ICON: Record<string, LucideIcon> = { orchestrator: Megaphone, content: Sparkles, threads_ops: Send, analytics: BarChart3 };
const DEPT_KINDS: Record<string, string[]> = {
  content: ["generate_post", "refill_ideas", "assistant"], threads_ops: ["publish_post", "reconcile_post", "collect_metrics", "check_connection"],
  analytics: ["analyze", "daily_report", "weekly_report"],
};

function eventOwner(e: EventItem): string {
  const t = e.event_type;
  const k = String(e.payload?.kind ?? "");
  if (t.startsWith("report") || t.startsWith("experiment") || t.startsWith("policy") || ["analyze", "daily_report", "weekly_report"].includes(k)) return "集客分析";
  if (["post.published", "post.unknown", "post.failed", "post.reconciled", "post.not_published"].includes(t) || t.startsWith("metrics") || t.startsWith("connection")
    || ["publish_post", "collect_metrics", "reconcile_post", "check_connection"].includes(k)) return "Threads運用";
  if (t.startsWith("post") || t.startsWith("assistant") || t.startsWith("idea") || ["generate_post", "assistant", "refill_ideas"].includes(k)) return "コンテンツ制作";
  return "AI統括";
}

type Edge = { id: string; d: string; active: boolean; dashed?: boolean };
type Reg = (id: string) => (el: HTMLElement | null) => void;

export function OrgChart({ c }: { c: ConsoleState }) {
  const o = c.overview;
  // registry of node elements, filled by callback refs and read only inside the layout effect
  const [nodes] = useState(() => new Map<string, HTMLElement>());
  const [box, setBox] = useState<HTMLDivElement | null>(null);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [reduced, setReduced] = useState(false);

  const agents = useMemo(() => new Map((o?.agents ?? []).map((a) => [a.id, a])), [o]);
  const runningKinds = useMemo(() => new Set((o?.agents ?? []).flatMap((a) => a.running.map((r) => r.kind))), [o]);
  const unitActive = (u: Unit) => u.kinds.some((k) => runningKinds.has(k)) || (!!o && !!u.always?.(o));
  const deptBusy = (d: string) => DEPT_KINDS[d]?.some((k) => runningKinds.has(k)) ?? false;
  const teamBusy = (t: Team) => t.units.some((u) => u.kinds.some((k) => runningKinds.has(k)));
  const reg: Reg = (id) => (el) => { if (el) nodes.set(id, el); else nodes.delete(id); };
  const key = [...runningKinds].sort().join(",") + `|${o?.kpi.pending_approvals}|${o?.runtime.scheduler_alive}|${o?.runtime.worker_alive}`;

  useEffect(() => {
    if (!box) return;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const compute = () => {
      setReduced(mq.matches);
      const base = box.getBoundingClientRect();
      const r = (id: string) => {
        const n = nodes.get(id);
        if (!n || !n.offsetParent) return null;
        const b = n.getBoundingClientRect();
        return { x: b.left - base.left, y: b.top - base.top, w: b.width, h: b.height };
      };
      const vcurve = (a: string, b: string, active: boolean, dashed = false): Edge | null => {
        const p = r(a), q = r(b);
        if (!p || !q) return null;
        const x1 = p.x + p.w / 2, y1 = p.y + p.h, x2 = q.x + q.w / 2, y2 = q.y, ym = (y1 + y2) / 2;
        return { id: `${a}>${b}`, d: `M${x1},${y1} C${x1},${ym} ${x2},${ym} ${x2},${y2}`, active, dashed };
      };
      const hcurve = (a: string, b: string, active: boolean): Edge | null => {
        const p = r(a), q = r(b);
        if (!p || !q) return null;
        const ltr = q.x > p.x;
        const x1 = ltr ? p.x + p.w : p.x, y1 = p.y + p.h / 2, x2 = ltr ? q.x : q.x + q.w, y2 = q.y + q.h / 2, xm = (x1 + x2) / 2;
        return { id: `${a}>${b}`, d: `M${x1},${y1} C${xm},${y1} ${xm},${y2} ${x2},${y2}`, active };
      };
      const elbow = (a: string, b: string, active: boolean): Edge | null => {
        const p = r(a), q = r(b);
        if (!p || !q) return null;
        const x1 = p.x + 22, y1 = p.y + p.h, x2 = q.x, y2 = q.y + 16;
        return { id: `${a}>${b}`, d: `M${x1},${y1} L${x1},${y2 - 8} Q${x1},${y2} ${x1 + 8},${y2} L${x2},${y2}`, active };
      };
      const list: (Edge | null)[] = [
        vcurve("owner", "ceo", (o?.kpi.pending_approvals ?? 0) > 0),
        hcurve("ceo", "hq", !!o?.runtime.scheduler_alive),
        hcurve("ceo", "policy", deptBusy("analytics")),
        ...DEPTS.map((d) => vcurve("ceo", d, deptBusy(d))),
        ...DEPTS.flatMap((d) => TEAMS[d].map((t) => elbow(d, `team-${d}-${t.id}`, teamBusy(t)))),
        vcurve(`team-content-${TEAMS.content.at(-1)!.id}`, "infra-llm", deptBusy("content") || deptBusy("analytics"), !o?.llm.available),
        vcurve(`team-threads_ops-${TEAMS.threads_ops.at(-1)!.id}`, "infra-threads", deptBusy("threads_ops"), !o?.mode.live_publishing),
        vcurve(`team-analytics-${TEAMS.analytics.at(-1)!.id}`, "infra-db", !!o?.runtime.worker_alive && runningKinds.size > 0),
      ];
      setSize({ w: box.scrollWidth, h: box.scrollHeight });
      setEdges(list.filter((e): e is Edge => !!e));
    };
    const ro = new ResizeObserver(() => compute());
    ro.observe(box);
    const raf = requestAnimationFrame(compute);
    mq.addEventListener("change", compute);
    return () => { ro.disconnect(); cancelAnimationFrame(raf); mq.removeEventListener("change", compute); };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- recompute only when activity or layout-relevant state changes
  }, [box, key]);

  const ticker = c.events.slice(-16).reverse();
  const totalActive = (o?.agents ?? []).reduce((n, a) => n + a.running.length, 0);

  return (
    <section className="panel overflow-hidden p-4" aria-labelledby="org-title">
      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2">
        <h2 id="org-title" className="panel-title">AI組織図</h2>
        <span className="text-[11px] text-muted">部門 → チーム → 工程。部門カードを選ぶと中央のコアがその部門の状態を表示します</span>
        <span className="ml-auto flex flex-wrap items-center gap-3 text-[11px] text-muted">
          <span className="num text-accent">ACTIVE {totalActive}</span>
          <span className="flex items-center gap-1.5"><span className="inline-block h-px w-6 bg-accent shadow-[0_0_6px_#00D9FF]" />処理が流れている経路</span>
          <span className="flex items-center gap-1.5"><span className="inline-block w-6 border-t border-dashed border-muted" />未接続・テストモード</span>
        </span>
      </div>

      {o && <MobileOrg c={c} o={o} agents={agents} unitActive={unitActive} />}

      <div className="scroll-thin -mx-1 hidden overflow-x-auto px-1 pb-2 md:block">
        <div ref={setBox} className="relative mx-auto min-w-[1180px] max-w-[1540px] pb-1">
          <svg className="pointer-events-none absolute inset-0" width={size.w} height={size.h} aria-hidden>
            <defs><filter id="org-glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2.4" /></filter></defs>
            {edges.map((e) => (
              <g key={e.id}>
                <path d={e.d} fill="none" stroke={e.active ? "rgb(0 217 255 / 0.6)" : "rgb(59 130 246 / 0.26)"} strokeWidth={e.active ? 1.6 : 1}
                  strokeDasharray={e.dashed ? "4 5" : undefined} />
                {e.active && <path d={e.d} fill="none" stroke="rgb(0 217 255 / 0.5)" strokeWidth={4} filter="url(#org-glow)" />}
                {!reduced && !e.dashed && (e.active ? [0, 0.7, 1.4] : [0]).map((delay) => (
                  <circle key={delay} r={e.active ? 2.6 : 1.5} fill={e.active ? "#BFF6FF" : "rgb(120 170 255 / 0.5)"} filter={e.active ? "url(#org-glow)" : undefined}>
                    <animateMotion dur={e.active ? "2.1s" : "7.5s"} begin={`${delay}s`} repeatCount="indefinite" path={e.d} />
                  </circle>
                ))}
              </g>
            ))}
          </svg>

          {/* tier 0: owner */}
          <div className="relative flex justify-center">
            <div ref={reg("owner")} className="org-node flex items-center gap-3 px-4 py-2.5" data-active={(o?.kpi.pending_approvals ?? 0) > 0}>
              <Sigil icon={Crown} active={false} />
              <div>
                <p className="hud text-[10px] text-muted">OWNER · 最終決定</p>
                <p className="text-sm font-medium">オーナー（あなた）</p>
                <p className="text-[11px] text-muted">承認待ち <span className="num text-text">{fmtNum(o?.kpi.pending_approvals)}</span>件・本番投稿 {o?.mode.live_publishing ? "ON" : "OFF"}</p>
              </div>
            </div>
          </div>

          {/* tier 1: HQ tools, CEO, policy */}
          <div className="relative mt-9 grid grid-cols-[1fr_auto_1fr] items-center gap-8">
            <div className="flex justify-end">
              <TeamBox id="hq" reg={reg} name="統括室" units={HQ} o={o} unitActive={unitActive} busy={!!o?.runtime.scheduler_alive} />
            </div>
            <DeptNode id="orchestrator" nodeId="ceo" a={agents.get("orchestrator")} c={c} reg={reg} big title="AI統括" eyebrow="CEO · 集客統括"
              done={o ? st(o, "refill_ideas") : 0} />
            <div ref={reg("policy")} className="org-node w-[270px] px-3 py-2.5" data-active={deptBusy("analytics")}>
              <p className="hud text-[10px] text-muted">POLICY · 運用方針</p>
              <p className="text-sm">v{o?.policy.version ?? "—"} <span className="text-xs text-muted">{({ auto: "自動改善", rollback: "差し戻し", manual: "手動" } as Record<string, string>)[o?.policy.source ?? ""] ?? "初期"}</span></p>
              <p className="truncate text-[11px] text-muted" title={o?.experiment?.hypothesis}>{o?.experiment ? `実験中：${o.experiment.control_value} → ${o.experiment.treatment_value}` : "実験なし"}</p>
              <p className="text-[11px] text-muted">自動改善 {o?.improvement_enabled ? "ON" : "OFF"}</p>
            </div>
          </div>

          {/* tier 2-3: departments and teams */}
          <div className="relative mt-11 grid grid-cols-3 gap-7">
            {DEPTS.map((d) => (
              <div key={d} className="min-w-0">
                <DeptNode id={d} nodeId={d} a={agents.get(d)} c={c} reg={reg}
                  done={o ? DEPT_KINDS[d].reduce((n, k) => n + st(o, k), 0) : 0} />
                <div className="mt-5 grid gap-3 pl-10">
                  {TEAMS[d].map((t) => (
                    <TeamBox key={t.id} id={`team-${d}-${t.id}`} reg={reg} name={t.name} units={t.units} o={o} unitActive={unitActive} busy={teamBusy(t)} />
                  ))}
                </div>
              </div>
            ))}
          </div>

          {/* tier 4: infrastructure */}
          <div className="relative mt-10 grid grid-cols-3 gap-7">
            <Infra id="infra-llm" reg={reg} icon={Brain} title="AIモデル" active={deptBusy("content") || deptBusy("analytics")}
              line={o ? (o.llm.available ? `${o.llm.provider} / ${o.llm.model}` : o.llm.reason ?? "未接続") : "—"} ok={!!o?.llm.available} />
            <Infra id="infra-threads" reg={reg} icon={Send} title="Threads API" active={deptBusy("threads_ops")}
              line={o ? (o.mode.live_publishing ? "本番投稿ON" : "テストモード（実投稿なし）") : "—"} ok={!!o?.mode.live_publishing} />
            <Infra id="infra-db" reg={reg} icon={Database} title="データベース・ワーカー" active={!!o?.runtime.worker_alive && runningKinds.size > 0}
              line={o ? `ワーカー${o.runtime.worker_alive ? "稼働" : "停止"}・スケジューラー${o.runtime.scheduler_alive ? "稼働" : "停止"}` : "—"} ok={!!o?.runtime.worker_alive} />
          </div>
        </div>
      </div>

      <div className="ticker mt-3 overflow-hidden border-t border-line/70 pt-2.5 text-[12px]" aria-label="最近の処理">
        {ticker.length === 0 ? <span className="text-muted">まだ処理はありません</span> : (
          <div className={reduced ? "flex flex-wrap gap-x-8 gap-y-1" : "ticker-track"}>
            {(reduced ? ticker : [...ticker, ...ticker]).map((e, i) => (
              <span key={`${e.event_id}-${i}`} className="inline-flex items-center gap-2" aria-hidden={i >= ticker.length}>
                <span className="num text-accent">{fmtTime(e.occurred_at, false).slice(0, 5)}</span>
                <span className="text-muted">{eventOwner(e)}</span>
                <span className="text-muted">→</span>
                <span className={e.severity === "error" ? "text-error" : e.severity === "warning" ? "text-warn" : "text-text/90"}>{e.message}</span>
              </span>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function Sigil({ icon: Icon, active, state }: { icon: LucideIcon; active: boolean; state?: Agent["state"] }) {
  const color = state === "error" ? "#F87171" : state === "unavailable" ? "#F59E0B" : "#00D9FF";
  return (
    <span className="relative grid size-11 shrink-0 place-items-center" aria-hidden>
      <svg viewBox="0 0 44 44" className="absolute inset-0">
        <polygon points="22,2 39.3,12 39.3,32 22,42 4.7,32 4.7,12" fill="rgb(0 217 255 / 0.06)" stroke={color} strokeOpacity="0.55" />
        <polygon points="22,8 34.1,15 34.1,29 22,36 9.9,29 9.9,15" fill="none" stroke={color} strokeOpacity="0.18" />
        {active && <circle cx="22" cy="22" r="20.5" fill="none" stroke={color} strokeWidth="1.2" strokeDasharray="3 6" className="sigil-ring" />}
      </svg>
      <Icon className="relative size-[18px]" style={{ color }} />
    </span>
  );
}

function DeptNode({ id, nodeId, a, c, reg, big, title, eyebrow, done }: { id: string; nodeId: string; a: Agent | undefined; c: ConsoleState; reg: Reg;
  big?: boolean; title?: string; eyebrow?: string; done: number }) {
  const s = a ? AGENT_STATE[a.state] : null;
  const running = (a?.running.length ?? 0) > 0;
  const Icon = ICON[id] ?? Bot;
  const selected = c.selected === id;
  return (
    <button ref={reg(nodeId)} onClick={() => c.setSelected(selected ? null : id)} aria-pressed={selected}
      className={`org-node w-full text-left ${big ? "min-w-[320px] px-4 py-3" : "px-3 py-2.5"}`}
      data-active={running} data-selected={selected} data-state={a?.state}>
      <div className="flex items-center gap-3">
        <Sigil icon={Icon} active={running} state={a?.state} />
        <div className="min-w-0 flex-1">
          {eyebrow ? <p className="hud text-[10px] text-muted">{eyebrow}</p> : <p className="truncate text-[10px] text-muted">{a?.role ?? ""}</p>}
          <p className={`${big ? "text-base" : "text-sm"} truncate font-medium`}>{title ?? a?.name ?? "—"}</p>
          <p className="truncate text-[11px] text-muted">{a?.tool ?? "—"}</p>
        </div>
        {s && <Badge tone={s.tone} spin={a?.state === "running"}>{s.label}</Badge>}
      </div>
      <div className="mt-2 grid grid-cols-3 gap-1 border-t border-line/60 pt-2 text-center">
        {[["処理中", a?.running.length ?? 0], ["待機", a?.queued ?? 0], ["24h完了", done]].map(([l, v]) => (
          <div key={l as string}><p className="text-[9px] text-muted">{l}</p><p className={`num text-[13px] ${l === "処理中" && Number(v) > 0 ? "text-accent" : ""}`}>{v}</p></div>
        ))}
      </div>
      {running && a?.running[0] && (
        <span className="absolute -bottom-3 left-1/2 z-10 -translate-x-1/2 whitespace-nowrap rounded-full border border-accent/50 bg-[#062033] px-2 py-0.5 text-[10px] text-accent shadow-[0_0_12px_rgba(0,217,255,0.4)]">
          作業中：{kindLabel(a.running[0].kind)}
        </span>
      )}
    </button>
  );
}

function TeamBox({ id, reg, name, units, o, unitActive, busy }: { id: string; reg: Reg; name: string; units: Unit[]; o: Overview | null;
  unitActive: (u: Unit) => boolean; busy: boolean }) {
  const activeCount = units.filter(unitActive).length;
  return (
    <div ref={reg(id)} className="org-node w-full min-w-[250px] px-2.5 pb-2 pt-2" data-active={busy}>
      <div className="mb-1.5 flex items-center gap-2 px-0.5">
        <span className="size-1.5 rotate-45 border border-accent/80" aria-hidden />
        <span className="text-[11px] font-medium tracking-wide">{name}</span>
        <span className="num ml-auto text-[10px] text-muted">{activeCount}/{units.length}</span>
      </div>
      <ul className="grid gap-1">
        {units.map((u) => {
          const active = unitActive(u);
          const alert = !!o && !!u.alert?.(o);
          return (
            <li key={u.id} className={`flex items-center gap-2 rounded-md px-1.5 py-1 text-[12px] ${active ? "bg-accent/[0.08]" : ""}`}>
              <span className={`size-1.5 shrink-0 rounded-full ${active ? "bg-accent shadow-[0_0_8px_#00D9FF]" : alert ? "bg-warn" : "bg-muted/45"}`} aria-hidden />
              <span className="min-w-0 flex-1 truncate">{u.label}</span>
              <span className={`num shrink-0 text-[10px] ${active ? "text-accent" : alert ? "text-warn" : "text-muted"}`}>
                {active && u.kinds.length ? "処理中" : o ? u.value(o) : "—"}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function Infra({ id, reg, icon: Icon, title, line, active, ok }: { id: string; reg: Reg; icon: LucideIcon; title: string; line: string; active: boolean; ok: boolean }) {
  return (
    <div className="flex justify-center pl-10">
      <div ref={reg(id)} className="org-node flex w-full max-w-[340px] items-center gap-3 px-3 py-2" data-active={active}>
        <span className="hud text-[9px] text-muted">INFRA</span>
        <Icon className={`size-4 ${ok ? "text-accent" : "text-warn"}`} aria-hidden />
        <div className="min-w-0">
          <p className="text-[13px]">{title}</p>
          <p className="truncate text-[11px] text-muted" title={line}>{line}</p>
        </div>
      </div>
    </div>
  );
}

/** Phone layout: same organisation as a vertical tree (no horizontal scrolling). */
function MobileOrg({ c, o, agents, unitActive }: { c: ConsoleState; o: Overview; agents: Map<string, Agent>; unitActive: (u: Unit) => boolean }) {
  const noop: Reg = () => () => undefined;
  return (
    <div className="grid gap-3 md:hidden">
      <div className="org-node flex items-center gap-3 px-3 py-2" data-active={o.kpi.pending_approvals > 0}>
        <Sigil icon={Crown} active={false} />
        <div><p className="hud text-[10px] text-muted">OWNER</p><p className="text-sm">オーナー（あなた）</p>
          <p className="text-[11px] text-muted">承認待ち <span className="num text-text">{fmtNum(o.kpi.pending_approvals)}</span>件</p></div>
      </div>
      <div className="grid gap-3 border-l border-accent/30 pl-3">
        <DeptNode id="orchestrator" nodeId="m-ceo" a={agents.get("orchestrator")} c={c} reg={noop} title="AI統括" eyebrow="CEO · 集客統括" done={st(o, "refill_ideas")} />
        <TeamBox id="m-hq" reg={noop} name="統括室" units={HQ} o={o} unitActive={unitActive} busy={o.runtime.scheduler_alive} />
        <div className="grid gap-4 border-l border-accent/30 pl-3">
          {DEPTS.map((d) => (
            <div key={d} className="grid gap-2">
              <DeptNode id={d} nodeId={`m-${d}`} a={agents.get(d)} c={c} reg={noop} done={DEPT_KINDS[d].reduce((n, k) => n + st(o, k), 0)} />
              <div className="grid gap-2 pl-4">
                {TEAMS[d].map((t) => <TeamBox key={t.id} id={`m-${d}-${t.id}`} reg={noop} name={t.name} units={t.units} o={o} unitActive={unitActive} busy={false} />)}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
