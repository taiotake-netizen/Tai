"use client";

/**
 * AI organisation chart. Every node reflects real engine state:
 *  - department nodes = the four agents from /overview (state, tool, queue)
 *  - member chips = job kinds handled by that agent (running now, 24h succeeded/failed)
 *  - external nodes = the model and the Threads connection actually configured
 * Connection lines carry moving light only while work flows through them.
 */
import { BarChart3, Bot, Crown, Megaphone, Send, Sparkles, type LucideIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ConsoleState } from "@/lib/client/useConsole";
import { AGENT_STATE, fmtNum, fmtTime, kindLabel } from "@/lib/format";
import type { Agent, EventItem } from "@/lib/types";
import { Badge } from "./ui/primitives";

const MEMBERS: Record<string, [string, string][]> = {
  orchestrator: [["scheduler", "スケジュール作成"], ["refill_ideas", "ネタ補充"]],
  content: [["generate_post", "投稿生成・品質チェック"], ["assistant", "AI補助"]],
  threads_ops: [["publish_post", "投稿公開"], ["reconcile_post", "結果照会"], ["collect_metrics", "実績取得"], ["check_connection", "接続確認"]],
  analytics: [["analyze", "分析・改善実験"], ["daily_report", "日次レポート"], ["weekly_report", "週次レポート"]],
};
const ICON: Record<string, LucideIcon> = { orchestrator: Megaphone, content: Sparkles, threads_ops: Send, analytics: BarChart3 };
const DEPTS = ["content", "threads_ops", "analytics"] as const;

function eventOwner(e: EventItem): string {
  const t = e.event_type;
  if (t.startsWith("report") || t.startsWith("experiment") || t.startsWith("policy")) return "集客分析";
  if (t.startsWith("post.published") || t.startsWith("metrics") || t.startsWith("connection") || t === "post.unknown" || t === "post.failed" || t === "post.reconciled") return "Threads運用";
  if (t.startsWith("post") || t.startsWith("assistant")) return "コンテンツ制作";
  const k = String(e.payload?.kind ?? "");
  if (["generate_post", "assistant"].includes(k)) return "コンテンツ制作";
  if (["publish_post", "collect_metrics", "reconcile_post", "check_connection"].includes(k)) return "Threads運用";
  if (["analyze", "daily_report", "weekly_report"].includes(k)) return "集客分析";
  return "集客統括";
}

type Edge = { id: string; d: string; active: boolean; dashed?: boolean };

export function OrgChart({ c }: { c: ConsoleState }) {
  const o = c.overview;
  const box = useRef<HTMLDivElement>(null);
  // registry of node elements, filled by callback refs and read only inside the layout effect
  const [nodes] = useState(() => new Map<string, HTMLElement>());
  const [edges, setEdges] = useState<Edge[]>([]);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [reduced, setReduced] = useState(false);

  const agents = useMemo(() => new Map((o?.agents ?? []).map((a) => [a.id, a])), [o]);
  const busy = (id: string) => (agents.get(id)?.running.length ?? 0) > 0;

  const reg = (id: string) => (el: HTMLElement | null) => { if (el) nodes.set(id, el); else nodes.delete(id); };

  const activeKey = useMemo(() => (o?.agents ?? []).map((a) => `${a.id}:${a.running.length}`).join("|"), [o]);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onMq = () => setReduced(mq.matches);
    const el = box.current;
    if (!el) return;
    const compute = () => {
      onMq();
      const base = el.getBoundingClientRect();
      const r = (id: string) => {
        const n = nodes.get(id);
        if (!n) return null;
        const b = n.getBoundingClientRect();
        return { x: b.left - base.left, y: b.top - base.top, w: b.width, h: b.height };
      };
      const down = (a: string, b: string, active: boolean): Edge | null => {
        const p = r(a), q = r(b);
        if (!p || !q) return null;
        const x1 = p.x + p.w / 2, y1 = p.y + p.h, x2 = q.x + q.w / 2, y2 = q.y;
        const ym = (y1 + y2) / 2;
        return { id: `${a}-${b}`, d: `M${x1},${y1} C${x1},${ym} ${x2},${ym} ${x2},${y2}`, active };
      };
      const side = (a: string, b: string, active: boolean, dashed = false): Edge | null => {
        const p = r(a), q = r(b);
        if (!p || !q) return null;
        const leftToRight = q.x > p.x;
        const x1 = leftToRight ? p.x + p.w : p.x, y1 = p.y + p.h / 2;
        const x2 = leftToRight ? q.x : q.x + q.w, y2 = q.y + q.h / 2;
        const xm = (x1 + x2) / 2;
        return { id: `${a}-${b}`, d: `M${x1},${y1} C${xm},${y1} ${xm},${y2} ${x2},${y2}`, active, dashed };
      };
      const memberEdges = (dept: string) => MEMBERS[dept].map(([k]) => {
        const p = r(dept), q = r(`m-${k}`);
        if (!p || !q) return null;
        const x1 = p.x + 18, y1 = p.y + p.h, x2 = q.x, y2 = q.y + q.h / 2;
        return { id: `${dept}-${k}`, d: `M${x1},${y1} L${x1},${y2} L${x2},${y2}`, active: busy(dept) && (agents.get(dept)?.running.some((x) => x.kind === k) ?? false) } as Edge;
      });
      const list = [
        down("owner", "orchestrator", (o?.kpi.pending_approvals ?? 0) > 0),
        ...DEPTS.map((d) => down("orchestrator", d, busy(d))),
        side("orchestrator", "m-scheduler", busy("orchestrator") || !!o?.runtime.scheduler_alive),
        side("orchestrator", "policy", busy("analytics")),
        ...DEPTS.flatMap((d) => memberEdges(d)),
      ].filter((e): e is Edge => !!e);
      setSize({ w: el.scrollWidth, h: el.scrollHeight });
      setEdges(list);
    };
    const ro = new ResizeObserver(() => compute());
    ro.observe(el);
    const raf = requestAnimationFrame(compute);
    mq.addEventListener("change", onMq);
    return () => { ro.disconnect(); cancelAnimationFrame(raf); mq.removeEventListener("change", onMq); };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- recompute when activity or layout-affecting data changes
  }, [activeKey, o?.kpi.pending_approvals, o?.runtime.scheduler_alive]);

  const stats = useMemo(() => o?.job_stats_24h ?? {}, [o]);
  const ticker = c.events.slice(-14).reverse();

  return (
    <section className="panel overflow-hidden p-4" aria-labelledby="org-title">
      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2">
        <h2 id="org-title" className="panel-title">AI組織図</h2>
        <span className="text-[11px] text-muted">カードを選ぶと中央のコアがその担当の状態を表示します</span>
        <span className="ml-auto flex items-center gap-3 text-[11px] text-muted">
          <span className="flex items-center gap-1.5"><span className="inline-block h-px w-6 bg-accent shadow-[0_0_6px_#00D9FF]" />処理が流れている経路</span>
          <span className="flex items-center gap-1.5"><span className="size-1.5 rounded-full bg-muted/50" />24h＝過去24時間の完了数</span>
        </span>
      </div>

      <MobileOrg c={c} agents={agents} stats={stats} />
      <div className="scroll-thin -mx-1 hidden overflow-x-auto px-1 pb-2 md:block">
        <div ref={box} className="relative mx-auto min-w-[1060px] max-w-[1500px]">
          <svg className="pointer-events-none absolute inset-0" width={size.w} height={size.h} aria-hidden>
            <defs>
              <filter id="org-glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2.4" /></filter>
            </defs>
            {edges.map((e) => (
              <g key={e.id}>
                <path d={e.d} fill="none" stroke={e.active ? "rgb(0 217 255 / 0.55)" : "rgb(59 130 246 / 0.28)"} strokeWidth={e.active ? 1.6 : 1}
                  strokeDasharray={e.dashed ? "4 5" : undefined} />
                {e.active && <path d={e.d} fill="none" stroke="rgb(0 217 255 / 0.5)" strokeWidth={4} filter="url(#org-glow)" />}
                {!reduced && (e.active ? [0, 0.8, 1.6] : [0]).map((delay) => (
                  <circle key={delay} r={e.active ? 2.6 : 1.6} fill={e.active ? "#bff6ff" : "rgb(120 170 255 / 0.55)"}
                    filter={e.active ? "url(#org-glow)" : undefined}>
                    <animateMotion dur={e.active ? "2.4s" : "7s"} begin={`${delay}s`} repeatCount="indefinite" path={e.d} />
                  </circle>
                ))}
              </g>
            ))}
          </svg>

          {/* row 1: owner */}
          <div className="relative flex justify-center">
            <div ref={reg("owner")} className="org-node flex items-center gap-3 px-4 py-2.5" data-active={(o?.kpi.pending_approvals ?? 0) > 0}>
              <Sigil icon={Crown} active={false} />
              <div>
                <p className="hud text-[10px] text-muted">OWNER · 最終決定</p>
                <p className="text-sm font-medium">オーナー（あなた）</p>
                <p className="text-[11px] text-muted">投稿の承認待ち <span className="num text-text">{fmtNum(o?.kpi.pending_approvals)}</span>件</p>
              </div>
            </div>
          </div>

          {/* row 2: orchestrator (CEO), its tools, policy */}
          <div className="relative mt-9 grid grid-cols-[1fr_auto_1fr] items-center gap-6">
            <div className="flex justify-end">
              <div className="grid gap-2">
                {MEMBERS.orchestrator.map(([k, label]) => (
                  <Member key={k} id={`m-${k}`} reg={reg} label={label}
                    running={k === "scheduler" ? !!o?.runtime.scheduler_alive : (agents.get("orchestrator")?.running.some((r) => r.kind === k) ?? false)}
                    runningLabel={k === "scheduler" ? "稼働" : "処理中"} stat={stats[k]} />
                ))}
              </div>
            </div>
            <DeptNode id="orchestrator" a={agents.get("orchestrator")} c={c} reg={reg} big title="AI統括" eyebrow="CEO · 集客統括" />
            <div ref={reg("policy")} className="org-node w-[250px] px-3 py-2.5" data-active={busy("analytics")}>
              <p className="hud text-[10px] text-muted">POLICY · 運用方針</p>
              <p className="text-sm">v{o?.policy.version ?? "—"} <span className="text-xs text-muted">{o?.policy.source === "auto" ? "自動改善" : o?.policy.source === "rollback" ? "差し戻し" : o?.policy.source === "manual" ? "手動" : "初期"}</span></p>
              <p className="truncate text-[11px] text-muted" title={o?.experiment?.hypothesis}>
                {o?.experiment ? `実験中：${o.experiment.control_value} → ${o.experiment.treatment_value}` : "実験なし"}
              </p>
            </div>
          </div>

          {/* row 3: departments and their units */}
          <div className="relative mt-10 grid grid-cols-3 gap-6">
            {DEPTS.map((d) => (
              <div key={d} className="min-w-0">
                <DeptNode id={d} a={agents.get(d)} c={c} reg={reg} />
                <div className="mt-4 grid gap-2 pl-8">
                  {MEMBERS[d].map(([k, label]) => (
                    <Member key={k} id={`m-${k}`} reg={reg} label={label}
                      running={agents.get(d)?.running.some((r) => r.kind === k) ?? false} stat={stats[k]} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* event ticker */}
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
        {active && <circle cx="22" cy="22" r="20.5" fill="none" stroke={color} strokeWidth="1.2" strokeDasharray="3 6" className="sigil-ring" />}
      </svg>
      <Icon className="relative size-[18px]" style={{ color }} />
    </span>
  );
}

function DeptNode({ id, a, c, reg, big, title, eyebrow }: { id: string; a: Agent | undefined; c: ConsoleState; reg: (id: string) => (el: HTMLElement | null) => void;
  big?: boolean; title?: string; eyebrow?: string }) {
  const st = a ? AGENT_STATE[a.state] : null;
  const running = (a?.running.length ?? 0) > 0;
  const Icon = ICON[id] ?? Bot;
  const selected = c.selected === id;
  return (
    <button ref={reg(id)} onClick={() => c.setSelected(selected ? null : id)} aria-pressed={selected}
      className={`org-node w-full text-left ${big ? "min-w-[300px] px-4 py-3" : "px-3 py-2.5"}`}
      data-active={running} data-selected={selected} data-state={a?.state}>
      <div className="flex items-center gap-3">
        <Sigil icon={Icon} active={running} state={a?.state} />
        <div className="min-w-0 flex-1">
          {eyebrow ? <p className="hud text-[10px] text-muted">{eyebrow}</p> : <p className="truncate text-[10px] text-muted">{a?.role ?? ""}</p>}
          <p className={`${big ? "text-base" : "text-sm"} truncate font-medium`}>{title ?? a?.name ?? "—"}</p>
          <p className="truncate text-[11px] text-muted">{a?.tool ?? "—"}・待機 <span className="num">{a?.queued ?? 0}</span></p>
        </div>
        {st && <Badge tone={st.tone} spin={a?.state === "running"}>{st.label}</Badge>}
      </div>
      {running && a?.running[0] && (
        <span className="absolute -bottom-3 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-full border border-accent/50 bg-[#062033] px-2 py-0.5 text-[10px] text-accent shadow-[0_0_12px_rgba(0,217,255,0.4)]">
          作業中：{kindLabel(a.running[0].kind)}
        </span>
      )}
    </button>
  );
}

function Member({ id, reg, label, running, runningLabel = "処理中", stat }: { id: string; reg: (id: string) => (el: HTMLElement | null) => void; label: string;
  running: boolean; runningLabel?: string; stat?: { succeeded: number; failed: number; queued: number } }) {
  return (
    <div ref={reg(id)} className="org-node flex items-center gap-2 px-2.5 py-1.5 text-[12px]" data-active={running}>
      <span className={`size-1.5 shrink-0 rounded-full ${running ? "bg-accent shadow-[0_0_8px_#00D9FF]" : stat?.failed ? "bg-error" : "bg-muted/50"}`} aria-hidden />
      <span className="min-w-0 flex-1 truncate">{label}</span>
      <span className="num shrink-0 text-[10px] text-muted">
        {running ? <span className="text-accent">{runningLabel}</span> : <>24h {stat?.succeeded ?? 0}{stat?.failed ? <span className="text-error"> ✕{stat.failed}</span> : null}</>}
      </span>
    </div>
  );
}

/** Phone layout: the same organisation as a vertical tree (no horizontal scrolling). */
function MobileOrg({ c, agents, stats }: { c: ConsoleState; agents: Map<string, Agent>; stats: NonNullable<ConsoleState["overview"]>["job_stats_24h"] }) {
  const o = c.overview;
  const noop = () => () => undefined;
  return (
    <div className="grid gap-3 md:hidden">
      <div className="org-node flex items-center gap-3 px-3 py-2" data-active={(o?.kpi.pending_approvals ?? 0) > 0}>
        <Sigil icon={Crown} active={false} />
        <div><p className="hud text-[10px] text-muted">OWNER</p><p className="text-sm">オーナー（あなた）</p>
          <p className="text-[11px] text-muted">承認待ち <span className="num text-text">{fmtNum(o?.kpi.pending_approvals)}</span>件</p></div>
      </div>
      <div className="grid gap-3 border-l border-accent/30 pl-3">
        <DeptNode id="orchestrator" a={agents.get("orchestrator")} c={c} reg={noop} title="AI統括" eyebrow="CEO · 集客統括" />
        <div className="grid gap-3 border-l border-accent/30 pl-3">
          {DEPTS.map((d) => (
            <div key={d} className="grid gap-2">
              <DeptNode id={d} a={agents.get(d)} c={c} reg={noop} />
              <div className="grid gap-1.5 pl-4">
                {MEMBERS[d].map(([k, label]) => (
                  <Member key={k} id={`mm-${k}`} reg={noop} label={label}
                    running={agents.get(d)?.running.some((r) => r.kind === k) ?? false} stat={stats?.[k]} />
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
