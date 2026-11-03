export type Severity = "info" | "success" | "warning" | "error";
export type AgentState = "running" | "waiting" | "idle" | "error" | "unavailable";

export type Agent = {
  id: string; name: string; role: string; state: AgentState; connected: boolean; reason: string | null;
  tool: string | null; queued: number;
  running: { id: number; kind: string; post_id: number | null; started_at: string }[];
  last: { status: string; kind: string; last_error: string | null; finished_at: string } | null;
};

export type Overview = {
  account: { id: string; display_name: string; platform: string; data_scope: string; connection_status: string;
    connection_checked_at: string | null; connection_error: string | null };
  mode: { app_env: string; publish_mode: string; live_publishing: boolean; data: "demo" | "test" | "live" };
  autopilot_enabled: boolean; require_approval: boolean; improvement_enabled: boolean; settings_version: number;
  runtime: { scheduler_alive: boolean; scheduler_last_tick: string | null; worker_alive: boolean; worker_last_seen: string | null };
  llm: { available: boolean; provider: string; model: string | null; reason: string | null };
  next: { next_post: { id: number; slot_at: string; status: string } | null; next_analysis_at: string | null;
    next_report_at: string | null; next_metrics_at: string | null };
  kpi: {
    published_today: number;
    publish_attempts_today: { success: number; failed: number; unknown: number };
    success_rate_today: number | null;
    metrics_7d: { posts: number; views: number | null; likes: number | null; replies: number | null; reposts: number | null;
      er: number | null; last_observed_at: string | null };
    ideas_ready: number; pending_approvals: number;
  };
  policy: { version: number; source: string; reason: string; created_at: string };
  experiment: { id: number; variable: string; control_value: string; treatment_value: string; hypothesis: string; started_at: string } | null;
  budget: { today_usd: number; month_usd: number; daily_limit_usd: number | null; monthly_limit_usd: number | null;
    budget_configured: boolean; price_configured: boolean };
  agents: Agent[];
  attention: { kind: "post" | "job"; id: number; status: string; message: string | null; updated_at: string }[];
  job_stats_24h?: Record<string, { succeeded: number; failed: number; running: number; queued: number }>;
  activity_24h?: number[];
  generated_at: string;
};

export type EventItem = {
  seq: number; event_id: string; account_id: string; source_system: string; event_type: string; severity: Severity;
  occurred_at: string; received_at: string; job_id: number | null; post_id: number | null; message: string;
  payload: Record<string, unknown>;
};

export type Post = {
  id: number; slot_at: string; status: string; theme: string | null; hook_style: string | null; cta_key: string | null;
  text: string | null; published_at: string | null; permalink: string | null; external_post_id: string | null;
  last_error: string | null; is_test: number; origin: string; updated_at: string; experiment_arm: string | null;
  policy_version: number | null;
  check: { passed: boolean; issues: { code: string; message: string; severity: string }[] } | null;
  latest_metrics: { views: number | null; likes: number | null; replies: number | null; reposts: number | null;
    quotes: number | null; status: string; bucket_hours: number; observed_at: string } | null;
};

export type Job = { id: number; kind: string; label: string; status: string; run_at: string; attempts: number;
  max_attempts: number; last_error: string | null; post_id: number | null; created_at: string; finished_at: string | null };

export type Idea = { id: number; theme: string; pain: string; appeal: string; angle: string; notes: string; status: string;
  origin: string; use_count: number; last_used_at: string | null; parent_idea_id: number | null; updated_at: string; created_at: string };

export type SessionInfo = {
  user: string; mode: "live" | "demo"; role: "admin" | "viewer"; accounts: string[];
  engine: { status: number; health: { status: string; app_env: string; publish_mode: string; time: string } | null;
    error: { error?: { code: string; message: string } } | null };
};

export type Capabilities = { api_version: string; actions: Record<string, { enabled: boolean; reason: string | null }> };
