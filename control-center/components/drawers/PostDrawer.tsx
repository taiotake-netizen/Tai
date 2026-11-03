"use client";

import { ExternalLink } from "lucide-react";
import { useState } from "react";
import type { ConsoleState } from "@/lib/client/useConsole";
import { fmtNum, fmtTime, JOB_STATUS, POST_STATUS } from "@/lib/format";
import type { Post } from "@/lib/types";
import type { Act } from "../Console";
import { Badge, Button, Confirm, Drawer, ErrorNote, Field, inputCls, Skeleton } from "../ui/primitives";
import { useData } from "./useData";

type PostDetail = Post & {
  attempts: { id: number; kind: string; outcome: string; detail: string | null; created_at: string }[];
  metrics: { bucket_hours: number; status: string; views: number | null; likes: number | null; replies: number | null;
    reposts: number | null; quotes: number | null; observed_at: string; error: string | null }[];
  jobs: { id: number; kind: string; status: string; run_at: string; attempts: number; last_error: string | null }[];
  appeal: string | null; length_target: string | null; structure: string | null; idea_id: number | null;
};

export function PostDrawer({ postId, onClose, c, act }: { postId: number | null; onClose: () => void; c: ConsoleState; act: Act }) {
  const { data: p, error, reload } = useData<PostDetail>(c.client, postId ? `posts/${postId}` : null, postId !== null, c.version);
  const [edit, setEdit] = useState<string | null>(null);
  const [publishAt, setPublishAt] = useState("");
  const [resolve, setResolve] = useState<null | "published" | "not_published">(null);
  const admin = c.session?.role === "admin";
  const st = p ? POST_STATUS[p.status] ?? { label: p.status, tone: "muted" as const } : null;
  const doAct = async (label: string, fn: () => Promise<unknown>) => { if (await act(label, fn)) reload(); };

  return (
    <Drawer open={postId !== null} onClose={() => { setEdit(null); onClose(); }} title={`投稿 #${postId ?? ""}`}>
      {error ? <ErrorNote>{error}</ErrorNote> : !p || p.id !== postId ? <Skeleton lines={6} /> : (
        <div className="space-y-5 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            {st && <Badge tone={st.tone}>{st.label}</Badge>}
            {p.is_test ? <Badge tone="muted">テスト（実際には投稿しない）</Badge> : <Badge tone="accent">本番</Badge>}
            <span className="num text-xs text-muted">予定 {fmtTime(p.slot_at)}{p.published_at && ` ／ 公開 ${fmtTime(p.published_at)}`}</span>
            {p.permalink && <a className="inline-flex items-center gap-1 text-xs text-accent hover:underline" href={p.permalink} target="_blank" rel="noreferrer noopener">Threadsで開く<ExternalLink className="size-3" aria-hidden /></a>}
          </div>
          {p.last_error && <ErrorNote>{p.last_error}</ErrorNote>}
          {edit === null ? (
            <p className="whitespace-pre-wrap break-words rounded-lg border border-line bg-bg/60 p-3 leading-relaxed">{p.text ?? "（未生成）"}</p>
          ) : (
            <Field label={`本文（${edit.length}文字）`}><textarea className={`${inputCls} min-h-48`} value={edit} onChange={(e) => setEdit(e.target.value)} /></Field>
          )}
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
            <dt className="text-muted">テーマ</dt><dd>{p.theme ?? "—"}</dd>
            <dt className="text-muted">書き出し</dt><dd>{p.hook_style ?? "—"}</dd>
            <dt className="text-muted">訴求</dt><dd>{p.appeal ?? "—"}</dd>
            <dt className="text-muted">CTA</dt><dd>{p.cta_key ?? "—"}</dd>
            <dt className="text-muted">文字量／構成</dt><dd>{p.length_target ?? "—"}／{p.structure ?? "—"}</dd>
            <dt className="text-muted">方針</dt><dd>{p.policy_version ? `v${p.policy_version}` : "—"}{p.experiment_arm && `（実験 ${p.experiment_arm === "treatment" ? "試行群" : "対照群"}）`}</dd>
            <dt className="text-muted">ネタ</dt><dd>{p.idea_id ? `#${p.idea_id}` : "—"}</dd>
            <dt className="text-muted">外部ID</dt><dd className="num break-all">{p.external_post_id ?? "—"}</dd>
          </dl>
          {p.check && (
            <div>
              <h3 className="panel-title mb-1">投稿前チェック</h3>
              {p.check.issues.length === 0 ? <Badge tone="ok">問題なし</Badge> : (
                <ul className="space-y-1">{p.check.issues.map((i, k) => (
                  <li key={k} className="flex items-start gap-2"><Badge tone={i.severity === "error" ? "error" : "warn"}>{i.severity === "error" ? "不合格" : "注意"}</Badge><span>{i.message}</span></li>
                ))}</ul>
              )}
            </div>
          )}
          {admin && (
            <div className="flex flex-wrap gap-2">
              {p.status === "awaiting_approval" && edit === null && (
                <>
                  {p.origin !== "schedule" && (
                    <Field label="公開日時（日本時間）"><input type="datetime-local" className={inputCls} value={publishAt} onChange={(e) => setPublishAt(e.target.value)} /></Field>
                  )}
                  <Button variant="primary" disabled={!p.check?.passed || (p.origin !== "schedule" && !publishAt)} onClick={() => void doAct("承認",
                    () => c.client!.post(`posts/${p.id}/approve`, publishAt ? { publish_at: new Date(`${publishAt}:00+09:00`).toISOString() } : {}))}>承認して予約</Button>
                  <Button onClick={() => setEdit(p.text ?? "")}>本文を編集</Button>
                </>
              )}
              {edit !== null && (
                <>
                  <Button variant="primary" onClick={async () => {
                    if (await act("本文の保存", () => c.client!.patch(`posts/${p.id}/text`, { text: edit, expected_updated_at: p.updated_at }),
                      (r) => ((r as { check: { passed: boolean } }).check.passed ? "保存しました（チェック合格）" : "保存しました（チェック不合格のため承認できません）"))) { setEdit(null); reload(); }
                  }}>保存して再チェック</Button>
                  <Button onClick={() => setEdit(null)}>編集をやめる</Button>
                </>
              )}
              {["planned", "generating", "awaiting_approval", "scheduled"].includes(p.status) && edit === null && (
                <Button variant="danger" onClick={() => void doAct("投稿予定の取消", () => c.client!.post(`posts/${p.id}/cancel`))}>投稿予定を取り消す</Button>
              )}
              {p.status === "unknown" && (
                <>
                  <Button onClick={() => setResolve("published")}>公開されていた</Button>
                  <Button onClick={() => setResolve("not_published")}>公開されていなかった</Button>
                </>
              )}
            </div>
          )}
          {p.status === "published" && <p className="text-xs text-muted">公開済みの投稿は管理画面から取り消せません（削除が必要な場合はThreadsアプリで行ってください）。</p>}
          <div>
            <h3 className="panel-title mb-1">実績</h3>
            {!p.metrics.length ? <p className="text-xs text-muted">まだ取得していません</p> : (
              <table className="w-full text-xs">
                <thead className="text-muted"><tr><th className="text-left font-normal">時点</th><th className="text-right font-normal">閲覧</th><th className="text-right font-normal">いいね</th><th className="text-right font-normal">返信</th><th className="text-right font-normal">再投稿</th><th className="text-right font-normal">取得</th></tr></thead>
                <tbody className="num">{p.metrics.map((m) => (
                  <tr key={m.bucket_hours} className="border-t border-line/50">
                    <td>{m.bucket_hours}h</td>
                    {m.status === "ok" ? <><td className="text-right">{fmtNum(m.views)}</td><td className="text-right">{fmtNum(m.likes)}</td><td className="text-right">{fmtNum(m.replies)}</td><td className="text-right">{fmtNum(m.reposts)}</td></>
                      : <td colSpan={4} className="text-right text-warn">{m.status === "failed" ? `取得失敗：${m.error ?? ""}` : "未提供"}</td>}
                    <td className="text-right text-muted">{fmtTime(m.observed_at)}</td>
                  </tr>))}
                </tbody>
              </table>
            )}
          </div>
          <div>
            <h3 className="panel-title mb-1">処理履歴</h3>
            <ul className="space-y-1 text-xs">
              {p.jobs.map((j) => <li key={`j${j.id}`} className="flex gap-2"><Badge tone={(JOB_STATUS[j.status] ?? { tone: "muted" }).tone}>{(JOB_STATUS[j.status] ?? { label: j.status }).label}</Badge><span>{j.kind}</span><span className="num text-muted">{fmtTime(j.run_at)}</span>{j.last_error && <span className="truncate text-error">{j.last_error}</span>}</li>)}
              {p.attempts.map((a) => <li key={`a${a.id}`} className="flex gap-2 text-muted"><span className="num">{fmtTime(a.created_at)}</span><span>{a.kind}</span><span>{a.outcome}</span></li>)}
            </ul>
          </div>
        </div>
      )}
      <Confirm open={!!resolve} title="公開結果を確定しますか？" confirmLabel="確定" onCancel={() => setResolve(null)}
        body={resolve === "published" ? "Threadsアプリで投稿があることを確認した場合のみ選んでください。公開済みとして実績取得を開始します。" : "Threadsに投稿がないことを確認した場合のみ選んでください。失敗として記録し、ネタは未使用に戻します（自動で再投稿はしません）。"}
        onConfirm={() => { const o = resolve; setResolve(null); if (p && o) void doAct("結果の確定", () => c.client!.post(`posts/${p.id}/resolve`, { outcome: o })); }} />
    </Drawer>
  );
}
