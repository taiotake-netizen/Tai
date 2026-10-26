export type Dir = "up" | "down" | "flat";

export interface Indicator {
  id: number; event_id: number; code: string; name: string; unit: string;
  previous: number | null; previous_revised: number | null; consensus: number | null;
  consensus_source: string | null; actual: number | null; actual_source: string | null;
  actual_verified: boolean; notes: string | null;
}

export interface ReachRow { up?: number | null; down?: number | null; either?: number | null; both?: number | null }

export interface Forecast {
  id: number; event_id: number; version_no: number; label: string; created_at: string;
  as_of: string | null; as_of_label: string | null; source: string; model_name: string; model_version: string;
  market_snapshot: Record<string, unknown>; news_used: { title: string; url?: string | null; source: string; published_at?: string | null }[];
  indicator_forecasts: { code: string; point: number | null; upside_risk?: string; downside_risk?: string; rationale?: string }[];
  prob_up: number | null; prob_down: number | null; prob_flat: number | null; dominant_direction: Dir | null;
  importance: number | null; confidence: number | null;
  d1: number | null; d5: number | null; d15: number | null; d30: number | null; d60: number | null; headline_move: number | null;
  max_up_5m: number | null; max_down_5m: number | null; max_excursion_5m: number | null;
  max_excursion_5m_low: number | null; max_excursion_5m_high: number | null;
  range_5m: number | null; range_30m: number | null; range_60m: number | null;
  reach_probs: Record<string, ReachRow>;
  initial_direction: Dir | null; initial_move: number | null; reversal_prob: number | null; reversal_size: number | null;
  scenarios: { label: string; value?: string; indicator_code?: string; min?: number; max?: number; reaction_min?: number; reaction_max?: number; window?: string }[];
  extras: { label: string; value: string }[]; phase_analysis: Record<string, unknown>;
  rationale: string | null; change_summary: string | null; warnings: string[];
}

export interface Outcome {
  id: number; event_id: number; kind: string; verified: boolean; source: string; timeframe_min: number | null;
  base_price: number | null; d1: number | null; d5: number | null; d15: number | null; d30: number | null; d60: number | null;
  headline_move: number | null; high_5m: number | null; low_5m: number | null;
  max_up_5m: number | null; max_down_5m: number | null; max_excursion_5m: number | null;
  range_5m: number | null; range_30m: number | null; range_60m: number | null;
  direction_5m: Dir | null; observed_direction: Dir | null; initial_direction: Dir | null; initial_move: number | null;
  reversed: boolean | null; reversal_size: number | null; related_markets: Record<string, Record<string, number | null>>;
  observations: { label: string; value: string }[]; missing: string[]; notes: string | null; computed_at: string;
}

export interface Report {
  id: number; event_id: number; created_at: string; tentative: boolean; generated_by: string; summary: string;
  confirmed_facts: { text: string; verified: boolean; source: string }[];
  hypotheses: { text: string; basis: string; by?: string }[];
  reflections: string[]; improvements: string[]; checklist: Record<string, unknown>;
}

export interface EventSummary {
  id: number; slug: string; title: string; category: string; categories: string[]; release_at: string | null;
  release_time_confirmed: boolean; date_label: string | null; importance: number; status: string; status_ja: string;
  is_composite: boolean; parent_id: number | null; cluster: string | null; origin: string; notes: string | null;
  schedule_sources: { name: string; url: string }[];
  indicators: Indicator[]; forecast_count: number; latest_forecast: Forecast | null; outcome: Outcome | null;
  report: Report | null; conversation_report: Report | null;
}

export interface Evaluation {
  id: number; forecast_id: number; outcome_id: number; tentative: boolean;
  metrics: Record<string, any>; notes: string[]; created_at: string;
}

export interface EventDetail extends EventSummary {
  forecasts: Forecast[]; outcomes: Outcome[]; reports: Report[]; evaluations: Evaluation[];
  children: { id: number; title: string; release_at: string | null; status: string }[];
  parent?: { id: number; title: string; release_at: string | null };
  similar_events: EventSummary[];
}

export class ApiError extends Error {
  constructor(public status: number, public detail: unknown) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
}

export function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    const d = e.detail as any;
    if (d && typeof d === "object" && "detail" in d) {
      const inner = d.detail;
      if (inner && typeof inner === "object" && Array.isArray(inner.errors)) return inner.errors.join("\n");
      if (Array.isArray(inner)) return inner.map((x: any) => x.msg).join("\n");
      return String(inner);
    }
    return e.message;
  }
  return e instanceof Error ? e.message : String(e);
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { cache: "no-store", ...init,
    headers: init?.body instanceof FormData ? init?.headers : { "Content-Type": "application/json", ...(init?.headers || {}) } });
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try { detail = await res.json(); } catch { /* ignore */ }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}
