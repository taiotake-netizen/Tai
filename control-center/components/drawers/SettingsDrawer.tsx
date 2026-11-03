"use client";

import { useState } from "react";
import type { ConsoleState } from "@/lib/client/useConsole";
import { ApiError } from "@/lib/client/api";
import type { Act } from "../Console";
import { Button, Confirm, Drawer, ErrorNote, Field, inputCls, Skeleton } from "../ui/primitives";
import { useData } from "./useData";

/* eslint-disable @typescript-eslint/no-explicit-any */
type S = any;

const LOCKABLE: [string, string][] = [["hook", "書き出し"], ["theme", "テーマ"], ["cta", "CTA"], ["appeal", "訴求"], ["length", "文章量"], ["structure", "構成"], ["post_time", "投稿時間"]];

const lines = (v: string) => v.split("\n").map((s) => s.trim()).filter(Boolean);
const num = (v: string) => (v.trim() === "" ? null : Number(v));

export function SettingsDrawer({ open, onClose, c, act }: { open: boolean; onClose: () => void; c: ConsoleState; act: Act }) {
  const { data, error, reload } = useData<{ settings: S; version: number }>(c.client, "settings", open, 0);
  const [draft, setDraft] = useState<S | null>(null);   // null = no local edits yet
  const s: S | null = draft ?? data?.settings ?? null;
  const [saveErr, setSaveErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [liveConfirm, setLiveConfirm] = useState<null | boolean>(null);
  const admin = c.session?.role === "admin";
  const set = (path: string, value: unknown) => setDraft((cur: S) => {
    const next = structuredClone(cur ?? data!.settings);
    const keys = path.split(".");
    let o = next;
    for (const k of keys.slice(0, -1)) o = o[k];
    o[keys[keys.length - 1]] = value;
    return next;
  });

  async function save() {
    if (!s || !data) return;
    setBusy(true);
    setSaveErr(null);
    const patch = { ...s };
    delete patch.live_publish_enabled;   // changed only through the dedicated confirmation below
    delete patch.autopilot_enabled;      // changed from the main screen
    try {
      await c.client!.patch("settings", { expected_version: data.version, patch });
      await act("設定の保存", async () => null, () => "設定を保存しました");
      setDraft(null);
      reload();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setSaveErr("他の操作で設定が更新されました。最新の内容を読み込み直してから、もう一度変更してください。");
      else if (e instanceof ApiError && e.status === 422) setSaveErr(`入力内容を確認してください：${formatDetails(e.details) || e.message}`);
      else setSaveErr(e instanceof ApiError ? e.message : "保存に失敗しました");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Drawer open={open} onClose={onClose} title="設定" wide>
      {error ? <ErrorNote>{error}</ErrorNote> : !s ? <Skeleton lines={10} /> : (
        <form className="space-y-6 text-sm" onSubmit={(e) => { e.preventDefault(); void save(); }}>
          <fieldset disabled={!admin} className="space-y-6">
            <Section title="投稿スケジュール">
              <div className="grid gap-3 sm:grid-cols-3">
                <Field label="1日の投稿数"><input type="number" min={0} max={10} className={inputCls} value={s.schedule.posts_per_day} onChange={(e) => set("schedule.posts_per_day", Number(e.target.value))} /></Field>
                <Field label="1日の上限（自動改善でも超えない）"><input type="number" min={0} max={20} className={inputCls} value={s.schedule.max_posts_per_day} onChange={(e) => set("schedule.max_posts_per_day", Number(e.target.value))} /></Field>
                <Field label="生成を始める時間（分前）"><input type="number" min={10} className={inputCls} value={s.schedule.generation_lead_minutes} onChange={(e) => set("schedule.generation_lead_minutes", Number(e.target.value))} /></Field>
                <Field label="投稿時刻の候補（HH:MM, 1行1つ）" hint="この中から投稿数ぶんを使います。自動改善は候補内でのみ入れ替えます">
                  <textarea className={`${inputCls} num min-h-24`} value={s.schedule.post_times.join("\n")} onChange={(e) => set("schedule.post_times", lines(e.target.value))} /></Field>
                <Field label="投稿可能な時間帯（開始）"><input type="time" className={inputCls} value={s.schedule.window_start} onChange={(e) => set("schedule.window_start", e.target.value)} /></Field>
                <Field label="投稿可能な時間帯（終了）"><input type="time" className={inputCls} value={s.schedule.window_end} onChange={(e) => set("schedule.window_end", e.target.value)} /></Field>
              </div>
              <Check label="投稿前に承認する（ONのときは承認待ちで止まります）" checked={s.require_approval} onChange={(v) => set("require_approval", v)} />
            </Section>

            <Section title="AI予算（未設定の間はAI処理を停止します）">
              <div className="grid gap-3 sm:grid-cols-3">
                <Field label="日次上限（USD）"><input inputMode="decimal" className={inputCls} value={s.budget.daily_usd ?? ""} onChange={(e) => set("budget.daily_usd", num(e.target.value))} /></Field>
                <Field label="月次上限（USD）"><input inputMode="decimal" className={inputCls} value={s.budget.monthly_usd ?? ""} onChange={(e) => set("budget.monthly_usd", num(e.target.value))} /></Field>
                <Field label="1回の最大出力トークン"><input type="number" className={inputCls} value={s.budget.max_output_tokens} onChange={(e) => set("budget.max_output_tokens", Number(e.target.value))} /></Field>
                <Field label="入力単価（USD / 100万トークン）" hint="OpenAIの料金ページの値を入力"><input inputMode="decimal" className={inputCls} value={s.budget.price_input_per_mtok_usd ?? ""} onChange={(e) => set("budget.price_input_per_mtok_usd", num(e.target.value))} /></Field>
                <Field label="出力単価（USD / 100万トークン）"><input inputMode="decimal" className={inputCls} value={s.budget.price_output_per_mtok_usd ?? ""} onChange={(e) => set("budget.price_output_per_mtok_usd", num(e.target.value))} /></Field>
              </div>
              <p className="text-xs text-muted">費用はトークン数（実測）×設定単価による推定です。請求額の確定値はOpenAIの管理画面で確認してください。購入済みクレジットは追加課金の許可を意味しません。</p>
            </Section>

            <Section title="事業情報（未入力の項目はAIに書かせません）">
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="サービス名"><input className={inputCls} value={s.business.service_name} onChange={(e) => set("business.service_name", e.target.value)} /></Field>
                <Field label="ターゲット"><input className={inputCls} value={s.business.target} onChange={(e) => set("business.target", e.target.value)} /></Field>
              </div>
              <Field label="商品・サービスの説明"><textarea className={`${inputCls} min-h-20`} value={s.business.offer_summary} onChange={(e) => set("business.offer_summary", e.target.value)} /></Field>
              <Field label="口調"><input className={inputCls} value={s.business.tone} onChange={(e) => set("business.tone", e.target.value)} /></Field>
              <Field label="承認済みの事実（1行1件。「事実 | 出典」の形式）" hint="数値・実績・体験談は、ここに登録した内容だけが投稿に使われます">
                <textarea className={`${inputCls} min-h-24`} value={s.business.approved_facts.map((f: S) => `${f.statement} | ${f.source}`).join("\n")}
                  onChange={(e) => set("business.approved_facts", lines(e.target.value).map((l, i) => { const [st, src] = l.split("|").map((x) => x.trim()); return { id: `f${i + 1}`, statement: st, source: src || "未記入" }; }))} /></Field>
              <Field label="CTA（1行1件。「キー | 文言 | URL(任意)」）" hint="キーは半角英小文字。URLのドメインは下の許可リストに含まれている必要があります">
                <textarea className={`${inputCls} min-h-24`} value={s.business.cta_options.map((o: S) => [o.key, o.text, o.url ?? ""].join(" | ").replace(/ \| $/, "")).join("\n")}
                  onChange={(e) => set("business.cta_options", lines(e.target.value).map((l) => { const [key, text, url] = l.split("|").map((x) => x.trim()); return { key, text: text ?? "", url: url || null }; }))} /></Field>
              <Field label="許可する誘導先ドメイン（1行1つ）"><textarea className={`${inputCls} min-h-16`} value={s.business.allowed_domains.join("\n")} onChange={(e) => set("business.allowed_domains", lines(e.target.value))} /></Field>
            </Section>

            <Section title="投稿内容">
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="最小文字数"><input type="number" className={inputCls} value={s.content.min_chars} onChange={(e) => set("content.min_chars", Number(e.target.value))} /></Field>
                <Field label="最大文字数（Threads上限500）"><input type="number" max={500} className={inputCls} value={s.content.max_chars} onChange={(e) => set("content.max_chars", Number(e.target.value))} /></Field>
                <Field label="テーマ（1行1つ）"><textarea className={`${inputCls} min-h-28`} value={s.content.themes.join("\n")} onChange={(e) => set("content.themes", lines(e.target.value))} /></Field>
                <Field label="禁止表現（1行1つ）"><textarea className={`${inputCls} min-h-28`} value={s.content.banned_phrases.join("\n")} onChange={(e) => set("content.banned_phrases", lines(e.target.value))} /></Field>
                <Field label="書き出しの型（1行1つ）"><textarea className={`${inputCls} min-h-24`} value={s.content.hook_styles.join("\n")} onChange={(e) => set("content.hook_styles", lines(e.target.value))} /></Field>
                <Field label="訴求（1行1つ）"><textarea className={`${inputCls} min-h-24`} value={s.content.appeals.join("\n")} onChange={(e) => set("content.appeals", lines(e.target.value))} /></Field>
              </div>
            </Section>

            <Section title="自動改善">
              <Check label="自動改善を有効にする" checked={s.improvement.enabled} onChange={(v) => set("improvement.enabled", v)} />
              <div className="grid gap-3 sm:grid-cols-3">
                <Field label="比較に必要な最低件数（群ごと）"><input type="number" className={inputCls} value={s.improvement.min_samples_per_arm} onChange={(e) => set("improvement.min_samples_per_arm", Number(e.target.value))} /></Field>
                <Field label="実験に回す割合（0.1〜0.5）"><input inputMode="decimal" className={inputCls} value={s.improvement.treatment_share} onChange={(e) => set("improvement.treatment_share", Number(e.target.value))} /></Field>
                <Field label="1回の最大変更幅（重み）"><input inputMode="decimal" className={inputCls} value={s.improvement.max_weight_step} onChange={(e) => set("improvement.max_weight_step", Number(e.target.value))} /></Field>
                <Field label="分析時刻"><input type="time" className={inputCls} value={s.improvement.analysis_time} onChange={(e) => set("improvement.analysis_time", e.target.value)} /></Field>
                <Field label="実験の最長日数"><input type="number" className={inputCls} value={s.improvement.experiment_max_days} onChange={(e) => set("improvement.experiment_max_days", Number(e.target.value))} /></Field>
                <Field label="悪化時の自動差し戻し（低下率）"><input inputMode="decimal" className={inputCls} value={s.improvement.rollback_drop_threshold} onChange={(e) => set("improvement.rollback_drop_threshold", Number(e.target.value))} /></Field>
              </div>
              <div>
                <p className="mb-1 text-muted">自動改善で変更しない項目（固定）</p>
                <div className="flex flex-wrap gap-3">{LOCKABLE.map(([k, l]) => (
                  <Check key={k} label={l} checked={s.locked.includes(k)} onChange={(v) => set("locked", v ? [...s.locked, k] : s.locked.filter((x: string) => x !== k))} />))}</div>
              </div>
            </Section>

            <Section title="ネタと類似チェック">
              <div className="grid gap-3 sm:grid-cols-3">
                <Field label="類似判定の対象期間（日）"><input type="number" className={inputCls} value={s.checks.similarity_window_days} onChange={(e) => set("checks.similarity_window_days", Number(e.target.value))} /></Field>
                <Field label="同じテーマの連続上限"><input type="number" className={inputCls} value={s.checks.theme_max_consecutive} onChange={(e) => set("checks.theme_max_consecutive", Number(e.target.value))} /></Field>
                <Field label="再生成の上限回数"><input type="number" min={0} max={5} className={inputCls} value={s.checks.max_regenerations} onChange={(e) => set("checks.max_regenerations", Number(e.target.value))} /></Field>
                <Field label="ネタの再利用間隔（日）"><input type="number" className={inputCls} value={s.ideas.reuse_interval_days} onChange={(e) => set("ideas.reuse_interval_days", Number(e.target.value))} /></Field>
                <Field label="新規ネタの配分（0〜0.8）"><input inputMode="decimal" className={inputCls} value={s.ideas.new_theme_share} onChange={(e) => set("ideas.new_theme_share", Number(e.target.value))} /></Field>
                <Field label="1日のAI補充上限"><input type="number" className={inputCls} value={s.ideas.refill_max_per_day} onChange={(e) => set("ideas.refill_max_per_day", Number(e.target.value))} /></Field>
              </div>
              <Check label="投稿前のAI審査を行う" checked={s.checks.ai_review_enabled} onChange={(v) => set("checks.ai_review_enabled", v)} />
            </Section>

            <Section title="レポート">
              <div className="grid gap-3 sm:grid-cols-3">
                <Field label="日次の作成時刻"><input type="time" className={inputCls} value={s.reports.daily_time} onChange={(e) => set("reports.daily_time", e.target.value)} /></Field>
                <Field label="週次の作成時刻（月曜）"><input type="time" className={inputCls} value={s.reports.weekly_time} onChange={(e) => set("reports.weekly_time", e.target.value)} /></Field>
              </div>
              <Check label="AIによる要約を付ける" checked={s.reports.ai_summary} onChange={(v) => set("reports.ai_summary", v)} />
            </Section>
          </fieldset>

          {saveErr && <ErrorNote>{saveErr}</ErrorNote>}
          {admin && (
            <div className="sticky bottom-0 -mx-5 flex gap-2 border-t border-line bg-[#07111f] px-5 py-3">
              <Button type="submit" variant="primary" busy={busy}>保存</Button>
              <Button type="button" onClick={() => { setDraft(null); reload(); setSaveErr(null); }}>最新を読み込む（変更を破棄）</Button>
            </div>
          )}

          <Section title="本番投稿">
            <p className="text-xs text-muted">本番投稿には、エンジン側の環境変数 PUBLISH_MODE=live と、この設定の両方が必要です。現在：
              {c.overview?.mode.publish_mode === "live" ? "PUBLISH_MODE=live" : "PUBLISH_MODE=dry_run（実投稿しません）"}／この設定 {s.live_publish_enabled ? "ON" : "OFF"}</p>
            {admin && c.overview?.mode.data === "live" && (
              s.live_publish_enabled
                ? <Button type="button" variant="danger" onClick={() => setLiveConfirm(false)}>本番投稿をOFFにする</Button>
                : <Button type="button" variant="danger" onClick={() => setLiveConfirm(true)}>本番投稿をONにする</Button>
            )}
            {c.overview?.mode.data !== "live" && <p className="text-xs text-muted">デモ／テストのアカウントでは本番投稿は有効にできません。</p>}
          </Section>
        </form>
      )}
      <Confirm open={liveConfirm !== null} danger requireText={liveConfirm ? "本番投稿を有効にする" : undefined}
        title={liveConfirm ? "本番投稿を有効にしますか？" : "本番投稿を無効にしますか？"} confirmLabel={liveConfirm ? "有効にする" : "無効にする"}
        body={liveConfirm ? "有効にすると、自動運用ON時に予定の投稿がThreadsへ実際に公開されます。対象アカウント・投稿予定・投稿数・予算・n8nとの重複がないことを確認してください。" : "以降の公開を止めます（公開済みの投稿は取り消されません）。"}
        onCancel={() => setLiveConfirm(null)}
        onConfirm={() => { const v = liveConfirm; setLiveConfirm(null); void act("本番投稿の切替", () => c.client!.patch("settings", { expected_version: data!.version, patch: { live_publish_enabled: v } })).then(() => reload()); }} />
    </Drawer>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="space-y-3 rounded-xl border border-line/60 p-4"><h3 className="text-sm font-medium">{title}</h3>{children}</section>;
}

function Check({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="inline-flex items-center gap-2 text-sm">
      <input type="checkbox" className="size-4 accent-[#00D9FF]" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span>{label}</span>
    </label>
  );
}

function formatDetails(d: unknown): string {
  if (!Array.isArray(d)) return "";
  return d.slice(0, 3).map((x: any) => `${(x.loc ?? []).join(".")}: ${x.msg ?? ""}`).join(" / ");
}
