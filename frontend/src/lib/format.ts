import type { Dir } from "./api";

const JST = "Asia/Tokyo";

export function fmtJst(iso: string | null | undefined, withYear = true): string {
  if (!iso) return "日時不明";
  const d = new Date(iso);
  const opts: Intl.DateTimeFormatOptions = {
    timeZone: JST, month: "numeric", day: "numeric", weekday: "short", hour: "2-digit", minute: "2-digit", hour12: false,
  };
  if (withYear) opts.year = "numeric";
  return d.toLocaleString("ja-JP", opts);
}

export function usd(v: number | null | undefined, signed = true): string {
  if (v === null || v === undefined) return "—";
  const s = Math.abs(v) >= 1000 ? v.toLocaleString("ja-JP", { maximumFractionDigits: 2 }) : (Math.round(v * 10) / 10).toString();
  return (signed && v > 0 ? "+" : "") + s;
}

export function pct(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : `${Math.round(v * 10) / 10}%`;
}

export const DIR_JA: Record<string, string> = { up: "上昇", down: "下落", flat: "横ばい" };

export function dirJa(d: Dir | string | null | undefined): string {
  return d ? DIR_JA[d] ?? d : "—";
}

export function dirClass(d: Dir | string | null | undefined): string {
  return d === "up" ? "text-up" : d === "down" ? "text-down" : "text-flat";
}

export function signClass(v: number | null | undefined): string {
  if (v === null || v === undefined) return "text-muted";
  return v > 0 ? "text-up" : v < 0 ? "text-down" : "text-flat";
}

export const CATEGORY_JA: Record<string, string> = {
  FOMC: "FOMC", FOMC_MINUTES: "FOMC議事要旨", FED_SPEECH: "FRB高官発言", CPI: "CPI", NFP: "雇用統計",
  GDP: "GDP", PCE: "PCE", ADP: "ADP", ISM: "ISM", RETAIL_SALES: "小売売上高", JOLTS: "JOLTS",
  JOBLESS_CLAIMS: "新規失業保険申請", ECI: "雇用コスト指数", DURABLE_GOODS: "耐久財受注",
  NEW_HOME_SALES: "新築住宅販売", CONSUMER_CONFIDENCE: "消費者信頼感", OTHER: "その他",
};

export const SOURCE_JA: Record<string, string> = {
  chatgpt_conversation: "ChatGPT会話記録", manual: "手入力", baseline_stat: "統計ベースライン", external: "外部モデル", llm: "LLM",
};
