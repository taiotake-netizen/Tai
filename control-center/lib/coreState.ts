/**
 * Maps business state → visual state of the 3D core. Business state is never derived from the visual one.
 *
 * Priority (highest first):
 *   disconnected : engine unreachable, or scheduler/worker heartbeat stale
 *   error        : selected scope has an agent in "error", or a post with unknown outcome
 *   executing    : a write-side job is running (publish / reconcile / metrics / connection check)
 *   thinking     : an AI job is running (generation / analysis / report / idea refill / assistant)
 *   idle         : otherwise
 * "success" is NOT a state: it is a one-shot overlay triggered by a new success event (played once per event_id).
 */
import type { Agent, EventItem, Overview } from "./types";

export type CoreVisual = "idle" | "thinking" | "executing" | "error" | "disconnected";

const EXECUTING_KINDS = new Set(["publish_post", "reconcile_post", "collect_metrics", "check_connection"]);
const THINKING_KINDS = new Set(["generate_post", "analyze", "daily_report", "weekly_report", "refill_ideas", "assistant"]);

export function deriveCore(input: { reachable: boolean; overview: Overview | null; selected: string | null }): CoreVisual {
  const { reachable, overview, selected } = input;
  if (!reachable || !overview) return "disconnected";
  if (!overview.runtime.scheduler_alive || !overview.runtime.worker_alive) return "disconnected";
  const agents: Agent[] = selected ? overview.agents.filter((a) => a.id === selected) : overview.agents;
  if (agents.some((a) => a.state === "error")) return "error";
  if (!selected && overview.attention.some((x) => x.kind === "post" && x.status === "unknown")) return "error";
  const kinds = agents.flatMap((a) => a.running.map((r) => r.kind));
  if (kinds.some((k) => EXECUTING_KINDS.has(k))) return "executing";
  if (kinds.some((k) => THINKING_KINDS.has(k))) return "thinking";
  return "idle";
}

const SUCCESS_TYPES = new Set(["post.published", "report.generated", "post.ready", "experiment.ended", "assistant.completed",
  "metrics.collected", "policy.updated"]);

export function isCelebration(e: EventItem): boolean {
  return e.severity === "success" && SUCCESS_TYPES.has(e.event_type);
}

/** Returns the events that should trigger a success ripple, never replaying an id that was already played. */
export function newCelebrations(events: EventItem[], played: Set<string>): EventItem[] {
  return events.filter((e) => isCelebration(e) && !played.has(e.event_id));
}

export const CORE_LABEL: Record<CoreVisual, string> = {
  idle: "待機中",
  thinking: "思考中（AI処理）",
  executing: "実行中",
  error: "要確認",
  disconnected: "接続待ち",
};

/** Merge newly fetched events into the list: dedupe by event_id, keep seq order, cap length. */
export function mergeEvents(current: EventItem[], incoming: EventItem[], cap = 200): EventItem[] {
  const map = new Map(current.map((e) => [e.event_id, e]));
  for (const e of incoming) map.set(e.event_id, e);
  return [...map.values()].sort((a, b) => a.seq - b.seq).slice(-cap);
}
