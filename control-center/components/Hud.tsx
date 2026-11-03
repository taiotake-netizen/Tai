"use client";

import { useEffect, useState } from "react";
import type { ConsoleState } from "@/lib/client/useConsole";
import { CORE_LABEL } from "@/lib/coreState";
import { fmtNum, fmtTime } from "@/lib/format";

function useJstClock(): string {
  const [t, setT] = useState<string>("--:--:--");
  useEffect(() => {
    const f = new Intl.DateTimeFormat("ja-JP", { timeZone: "Asia/Tokyo", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
    const id = setInterval(() => setT(f.format(new Date())), 1000);
    const first = setTimeout(() => setT(f.format(new Date())), 0);
    return () => { clearInterval(id); clearTimeout(first); };
  }, []);
  return t;
}

function Sparkline({ values }: { values: number[] }) {
  const w = 132, h = 30, max = Math.max(1, ...values);
  const pts = values.map((v, i) => [(i / Math.max(1, values.length - 1)) * w, h - 3 - (v / max) * (h - 8)]);
  const line = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const last = pts[pts.length - 1];
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`過去24時間の完了処理 合計${values.reduce((a, b) => a + b, 0)}件`}>
      <defs>
        <linearGradient id="spark-fill" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#00D9FF" stopOpacity="0.35" />
          <stop offset="1" stopColor="#00D9FF" stopOpacity="0" />
        </linearGradient>
      </defs>
      {[0.33, 0.66].map((k) => <line key={k} x1="0" x2={w} y1={h * k} y2={h * k} stroke="rgb(140 166 189 / 0.12)" />)}
      <path d={`${line} L${w},${h} L0,${h} Z`} fill="url(#spark-fill)" />
      <path d={line} fill="none" stroke="#00D9FF" strokeWidth="1.4" />
      {last && <circle cx={last[0]} cy={last[1]} r="2.6" fill="#BFF6FF" />}
    </svg>
  );
}

/** Live strip under the header: clock + live counters + 24h activity, all from engine state. */
export function HudStrip({ c }: { c: ConsoleState }) {
  const clock = useJstClock();
  const o = c.overview;
  const agentsBusy = o?.agents.filter((a) => a.running.length).length ?? 0;
  const queued = o?.agents.reduce((n, a) => n + a.queued, 0) ?? 0;
  const activity = o?.activity_24h ?? [];
  const total24 = activity.reduce((a, b) => a + b, 0);
  const chips: [string, string, boolean?][] = [
    ["稼働中の担当", o ? `${agentsBusy} / ${o.agents.length}` : "—", agentsBusy > 0],
    ["待機ジョブ", fmtNum(o ? queued : null)],
    ["本日の投稿", fmtNum(o?.kpi.published_today)],
    ["次の投稿", fmtTime(o?.next.next_post?.slot_at)],
    ["方針", o ? `v${o.policy.version}` : "—"],
  ];
  return (
    <div className="panel mb-3 flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-2.5">
      <div className="flex items-center gap-2.5">
        <span className={c.reachable ? "live-dot" : "size-2 rounded-full bg-muted"} aria-hidden />
        <span className="hud text-[11px] font-semibold text-[#ff8fa3]">{c.reachable ? "LIVE" : "OFFLINE"}</span>
        <span className="num text-xl tracking-wider text-text" aria-label={`日本時間 ${clock}`}>{clock}</span>
        <span className="hud text-[10px] text-muted">JST</span>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {chips.map(([label, value, hot]) => (
          <div key={label} className={`rounded-lg border px-2.5 py-1 ${hot ? "border-accent/50 bg-accent/[0.07]" : "border-line bg-white/[0.02]"}`}>
            <p className="text-[10px] leading-none text-muted">{label}</p>
            <p className={`num mt-1 text-sm leading-none ${hot ? "text-accent" : ""}`}>{value}</p>
          </div>
        ))}
      </div>
      <div className="ml-auto flex items-center gap-3">
        <div className="text-right">
          <p className="text-[10px] leading-none text-muted">24時間の完了処理</p>
          <p className="num mt-1 text-sm leading-none">{fmtNum(o ? total24 : null)}<span className="text-[10px] text-muted"> 件</span></p>
        </div>
        {activity.length > 0 && <Sparkline values={activity} />}
      </div>
    </div>
  );
}

/** HUD overlay drawn over the 3D core: rotating reticle rings and real readouts in the corners. */
export function CoreHud({ c }: { c: ConsoleState }) {
  const o = c.overview;
  const queued = o?.agents.reduce((n, a) => n + a.queued, 0);
  const running = o?.agents.reduce((n, a) => n + a.running.length, 0);
  const tone = c.core === "error" ? "#F59E0B" : c.core === "disconnected" ? "#8CA6BD" : "#00D9FF";
  const ticks = Array.from({ length: 72 }, (_, i) => i);
  return (
    <div className="pointer-events-none absolute inset-0" aria-hidden>
      <div className="absolute left-1/2 top-1/2 aspect-square h-[112%] max-h-[520px] -translate-x-1/2 -translate-y-1/2">
      <svg className="h-full w-full" viewBox="-200 -200 400 400">
        <g className="hud-spin" opacity="0.85" style={{ transformOrigin: "0px 0px" }}>
          <circle r="182" fill="none" stroke={tone} strokeOpacity="0.28" />
          {ticks.map((i) => {
            const a = (i / 72) * Math.PI * 2, long = i % 6 === 0;
            return <line key={i} x1={Math.cos(a) * 182} y1={Math.sin(a) * 182} x2={Math.cos(a) * (long ? 172 : 177)} y2={Math.sin(a) * (long ? 172 : 177)}
              stroke={tone} strokeOpacity={long ? 0.55 : 0.25} strokeWidth={long ? 1.2 : 0.8} />;
          })}
        </g>
        <g className="hud-spin-rev" opacity="0.9" style={{ transformOrigin: "0px 0px" }}>
          <circle r="162" fill="none" stroke={tone} strokeOpacity="0.22" strokeDasharray="2 10" />
          <path d="M -162 0 A 162 162 0 0 1 -114.5 -114.5" fill="none" stroke={tone} strokeWidth="2" strokeOpacity="0.6" />
          <path d="M 162 0 A 162 162 0 0 1 114.5 114.5" fill="none" stroke={tone} strokeWidth="2" strokeOpacity="0.6" />
        </g>
      </svg>
      </div>
      <dl className="hud absolute bottom-3 left-4 grid grid-cols-[auto_auto] gap-x-3 gap-y-0.5 text-[10px] text-muted">
        <dt>QUEUE</dt><dd className="num text-text">{fmtNum(queued)}</dd>
        <dt>ACTIVE</dt><dd className="num text-text">{fmtNum(running)}</dd>
      </dl>
      <dl className="hud absolute bottom-3 right-4 grid grid-cols-[auto_auto] gap-x-3 gap-y-0.5 text-right text-[10px] text-muted">
        <dt>STATE</dt><dd className="text-text normal-case tracking-normal">{CORE_LABEL[c.core]}</dd>
        <dt>MODE</dt><dd className="text-text normal-case tracking-normal">{o ? (o.mode.live_publishing ? "本番投稿" : "テスト") : "—"}</dd>
      </dl>
      <div className="hud absolute right-4 top-4 text-right text-[10px] text-muted">
        <p>POLICY <span className="num text-text">{o ? `v${o.policy.version}` : "—"}</span></p>
        <p className="normal-case tracking-normal">{o?.experiment ? `実験中 ${o.experiment.control_value}→${o.experiment.treatment_value}` : "実験なし"}</p>
      </div>
    </div>
  );
}
