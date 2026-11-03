"use client";

import dynamic from "next/dynamic";
import { Component, useEffect, useState, type ReactNode } from "react";
import { CORE_LABEL, type CoreVisual } from "@/lib/coreState";
import type { Quality } from "./Core3D";

const Core3D = dynamic(() => import("./Core3D"), { ssr: false, loading: () => <Fallback visual="idle" note="3Dを読み込み中" /> });

function webglAvailable(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

function pickQuality(): Quality {
  const cores = navigator.hardwareConcurrency ?? 4;
  const small = window.matchMedia("(max-width: 767px)").matches;
  const mem = (navigator as Navigator & { deviceMemory?: number }).deviceMemory ?? 8;
  if (small || cores <= 4 || mem <= 4) return small ? "low" : "mid";
  return cores >= 8 ? "high" : "mid";
}

class Boundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch() { /* 3D failure must never break the console */ }
  render() { return this.state.failed ? this.props.fallback : this.props.children; }
}

const TONE: Record<CoreVisual, string> = {
  idle: "from-[#00D9FF]/35", thinking: "from-[#7dd3fc]/45", executing: "from-[#00D9FF]/50",
  error: "from-amber-500/35", disconnected: "from-slate-500/20",
};

export function Fallback({ visual, note }: { visual: CoreVisual; note?: string }) {
  return (
    <div className="absolute inset-0 grid place-items-center" aria-hidden>
      <div className={`h-40 w-40 rounded-full bg-radial ${TONE[visual]} to-transparent to-70% blur-[1px] sm:h-56 sm:w-56`} />
      {note && <span className="absolute bottom-3 text-xs text-[var(--muted)]">{note}</span>}
    </div>
  );
}

export function CoreStage({ visual, pulseKey, compact }: { visual: CoreVisual; pulseKey: string | null; compact?: boolean }) {
  const [env, setEnv] = useState<{ webgl: boolean; quality: Quality; reduced: boolean } | null>(null);
  const [hidden, setHidden] = useState(false);
  const [lost, setLost] = useState(0);
  const [gaveUp, setGaveUp] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setEnv({ webgl: webglAvailable(), quality: pickQuality(), reduced: mq.matches });
    update();
    mq.addEventListener("change", update);
    const onVis = () => setHidden(document.hidden);
    document.addEventListener("visibilitychange", onVis);
    return () => { mq.removeEventListener("change", update); document.removeEventListener("visibilitychange", onVis); };
  }, []);

  const label = CORE_LABEL[visual];
  return (
    <div className={`relative w-full overflow-hidden ${compact ? "h-44" : "h-[300px] md:h-[360px] xl:h-[420px]"}`}
      role="img" aria-label={`AIコアの状態: ${label}`}>
      {!env ? <Fallback visual={visual} /> : !env.webgl || gaveUp ? (
        <Fallback visual={visual} note={gaveUp ? "3D表示を停止しました（管理機能は利用できます）" : "この端末では3D表示を省略しています"} />
      ) : (
        <Boundary fallback={<Fallback visual={visual} note="3D表示でエラーが発生しました" />}>
          <Core3D key={lost} visual={visual} pulseKey={pulseKey} quality={compact && env.quality === "high" ? "mid" : env.quality}
            reducedMotion={env.reduced} paused={hidden}
            onContextLost={() => { if (lost >= 2) setGaveUp(true); else setTimeout(() => setLost((n) => n + 1), 800); }} />
        </Boundary>
      )}
    </div>
  );
}
