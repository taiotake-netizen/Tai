const TZ = "Asia/Tokyo";

export function fmtTime(iso: string | null | undefined, withDate = true): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const opts: Intl.DateTimeFormatOptions = withDate
    ? { timeZone: TZ, month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }
    : { timeZone: TZ, hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false };
  return new Intl.DateTimeFormat("ja-JP", opts).format(d);
}

export function fmtRelative(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "—";
  const diff = (new Date(iso).getTime() - now) / 1000;
  const abs = Math.abs(diff);
  const unit = abs < 60 ? `${Math.round(abs)}秒` : abs < 3600 ? `${Math.round(abs / 60)}分` : abs < 86400
    ? `${Math.round(abs / 3600)}時間` : `${Math.round(abs / 86400)}日`;
  return diff >= 0 ? `${unit}後` : `${unit}前`;
}

export function fmtNum(n: number | null | undefined): string {
  return n === null || n === undefined ? "—" : new Intl.NumberFormat("ja-JP").format(n);
}

export function fmtPct(n: number | null | undefined, digits = 1): string {
  return n === null || n === undefined ? "—" : `${(n * 100).toFixed(digits)}%`;
}

export function fmtUsd(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  if (n === 0) return "$0";
  return `$${n.toFixed(n < 0.01 ? 4 : 2)}`;
}

export type Tone = "ok" | "warn" | "error" | "accent" | "muted";

export const POST_STATUS: Record<string, { label: string; tone: Tone }> = {
  planned: { label: "枠作成", tone: "muted" },
  generating: { label: "生成中", tone: "accent" },
  awaiting_approval: { label: "承認待ち", tone: "warn" },
  scheduled: { label: "予約済み", tone: "accent" },
  publishing: { label: "公開処理中", tone: "accent" },
  published: { label: "公開済み", tone: "ok" },
  unknown: { label: "結果不明", tone: "error" },
  failed: { label: "失敗", tone: "error" },
  skipped: { label: "スキップ", tone: "warn" },
  cancelled: { label: "取消", tone: "muted" },
};

export const JOB_STATUS: Record<string, { label: string; tone: Tone }> = {
  queued: { label: "待機", tone: "muted" },
  running: { label: "実行中", tone: "accent" },
  succeeded: { label: "完了", tone: "ok" },
  failed: { label: "失敗", tone: "error" },
  cancelled: { label: "取消完了", tone: "muted" },
  cancel_requested: { label: "取消要求中", tone: "warn" },
};

export const AGENT_STATE: Record<string, { label: string; tone: Tone }> = {
  running: { label: "処理中", tone: "accent" },
  waiting: { label: "予定あり", tone: "muted" },
  idle: { label: "待機", tone: "muted" },
  error: { label: "要確認", tone: "error" },
  unavailable: { label: "未接続", tone: "warn" },
};

export const KIND_LABEL: Record<string, string> = {
  generate_post: "投稿生成・チェック", publish_post: "投稿公開", collect_metrics: "実績取得", reconcile_post: "結果照会",
  analyze: "分析・自動改善", daily_report: "日次レポート", weekly_report: "週次レポート", refill_ideas: "ネタ補充",
  assistant: "AI補助", check_connection: "接続確認",
};
export const kindLabel = (k: string) => KIND_LABEL[k] ?? k;
