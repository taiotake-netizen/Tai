/**
 * Browser-only sample backend for the standalone preview of AI CONTROL CENTER.
 * It answers the same /api/* calls the real BFF answers, from a snapshot of the demo engine,
 * and simulates jobs/events so the console and the 3D core behave like the running system.
 * Nothing leaves the browser: no Threads, no OpenAI, no network.
 */
import snapshotRaw from "./snapshot.json";

type J = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$/;
const SNAP_AT = Date.parse((snapshotRaw as J).overview.generated_at);
// move the sample forward by whole days so it looks recent while day/week boundaries stay at 00:00 JST
const SHIFT = Math.floor((Date.now() - SNAP_AT) / 86_400_000) * 86_400_000;

function shift(v: unknown): unknown {
  if (typeof v === "string" && ISO.test(v)) return new Date(Date.parse(v) + SHIFT).toISOString();
  if (Array.isArray(v)) return v.map(shift);
  if (v && typeof v === "object") return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, shift(x)]));
  return v;
}

const snap = shift(snapshotRaw) as J;
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
const now = () => new Date().toISOString();

// ------------------------------------------------------------------ mutable state
const overview: J = clone(snap.overview);
const settings: J = clone(snap.settings);
const policy: J = clone(snap.policy);
const experiments: J = clone(snap.experiments);
const reports: J = clone(snap.reports);
const ideas: J[] = clone(snap["ideas?limit=100"].items);
const runs: J[] = clone(snap["assistant/runs"].items);
const jobs: J[] = clone(snap["jobs?limit=40"].items);
const events: J[] = clone(snap["events?after_seq=0&limit=100"].items);
let seq = Math.max(0, ...events.map((e) => e.seq));
let offlineUntil = 0;
let nextId = 90000;

function emit(event_type: string, message: string, severity = "info", extra: J = {}) {
  seq += 1;
  events.push({ seq, event_id: `sample-${seq}-${Math.random().toString(36).slice(2, 8)}`, account_id: "demo",
    source_system: "threads-ops", event_type, severity, occurred_at: now(), received_at: now(), job_id: null,
    post_id: null, message, payload: {}, ...extra });
}

function agent(id: string) { return overview.agents.find((a: J) => a.id === id); }

/** Run a fake job: agent shows "running" for `ms`, then success/failure events. */
function simulate(agentId: string, kind: string, label: string, ms: number, done: () => void) {
  const id = nextId++;
  const a = agent(agentId);
  a.running = [...a.running, { id, kind, post_id: null, started_at: now() }];
  a.state = "running";
  jobs.unshift({ id, kind, label, status: "running", run_at: now(), attempts: 1, max_attempts: 3, last_error: null,
    post_id: null, created_at: now(), finished_at: null, payload: {}, result: null });
  emit("job.started", `${label}を開始`, "info", { job_id: id });
  setTimeout(() => {
    a.running = a.running.filter((r: J) => r.id !== id);
    a.state = a.running.length ? "running" : "idle";
    const j = jobs.find((x) => x.id === id);
    if (j) { j.status = "succeeded"; j.finished_at = now(); }
    done();
  }, ms);
}

function publishFlow(fail?: "error" | "unknown") {
  simulate("content", "generate_post", "投稿生成・チェック", 4500, () => {
    emit("post.ready", "投稿を予約しました", "success");
    simulate("threads_ops", "publish_post", "投稿公開", 3500, () => {
      if (fail === "error") {
        emit("post.failed", "公開に失敗しました: （テスト）公開APIがエラーを返しました", "error");
        agent("threads_ops").state = "error";
        agent("threads_ops").last = { status: "failed", kind: "publish_post", last_error: "（テスト）公開APIがエラーを返しました", finished_at: now() };
        setTimeout(() => { agent("threads_ops").state = "idle"; }, 15000);
      } else if (fail === "unknown") {
        emit("post.unknown", "公開結果が不明です（自動照会します）", "error");
        overview.attention.unshift({ kind: "post", id: 1238, status: "unknown", message: "（テスト）公開結果が不明です", updated_at: now() });
        setTimeout(() => {
          overview.attention = overview.attention.filter((x: J) => x.status !== "unknown");
          emit("post.reconciled", "照会の結果、公開されていませんでした（テスト）", "warning");
        }, 12000);
      } else {
        overview.kpi.published_today += 1;
        overview.kpi.publish_attempts_today.success += 1;
        emit("post.published", "テスト公開（実際には投稿していません）", "success");
      }
    });
  });
}

// ambient activity so the console feels alive
setInterval(() => {
  if (Date.now() < offlineUntil || !overview.autopilot_enabled) return;
  if (overview.agents.some((a: J) => a.running.length)) return;
  const r = Math.random();
  if (r < 0.4) simulate("threads_ops", "collect_metrics", "実績取得", 3000, () => emit("metrics.collected", "実績を取得（24時間後）", "success"));
  else if (r < 0.6) simulate("orchestrator", "refill_ideas", "ネタ補充", 3500, () => emit("idea.created", "ネタを追加: 続けるコツ／小さく始める習慣"));
}, 22000);

// ------------------------------------------------------------------ router
const ok = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const err = (status: number, code: string, message: string) => ok({ error: { code, message } }, status);

async function handle(method: string, path: string, query: URLSearchParams, body: J): Promise<Response> {
  if (path === "/api/session") {
    return ok({ user: "demo", mode: "demo", role: "admin", accounts: ["demo"],
      engine: { status: 200, health: { status: "ok", app_env: "demo", publish_mode: "dry_run", time: now() }, error: null } });
  }
  if (path.startsWith("/api/auth/")) return ok({ ok: true });
  const m = path.match(/^\/api\/cc\/demo\/(.+)$/);
  if (!m) return err(404, "not_found", "対象が見つかりません");
  const sub = m[1];
  if (Date.now() < offlineUntil && sub !== "demo/scenario") return err(503, "demo_disconnected", "（サンプル）接続断を再現中です");

  if (method === "GET") {
    switch (sub) {
      case "overview": {
        overview.runtime = { scheduler_alive: true, worker_alive: true, scheduler_last_tick: now(), worker_last_seen: now() };
        overview.generated_at = now();
        overview.experiment = experiments.items.find((e: J) => e.status === "running") ?? null;
        return ok(overview);
      }
      case "capabilities": return ok(snap.capabilities);
      case "jobs": {
        const st = query.get("status");
        return ok({ items: jobs.filter((j) => !st || j.status === st).slice(0, 40), next_before_id: null });
      }
      case "posts": return ok(snap[`posts?view=${query.get("view") ?? "upcoming"}&limit=30`] ?? { items: [] });
      case "events": {
        const after = Number(query.get("after_seq") ?? 0);
        const items = after === 0 ? events.slice(-60) : events.filter((e) => e.seq > after).slice(0, 100);
        return ok({ items, cursor: items.length ? items[items.length - 1].seq : after, latest_seq: seq, has_more: false });
      }
      case "ideas": {
        const st = query.get("status"), q = query.get("q");
        const items = ideas.filter((i) => (!st || i.status === st) && (!q || [i.theme, i.pain, i.angle, i.notes].join(" ").includes(q)));
        const counts: J = {};
        ideas.forEach((i) => { counts[i.status] = (counts[i.status] ?? 0) + 1; });
        return ok({ items, total: items.length, counts, limit: 100, offset: 0 });
      }
      case "policy": return ok(policy);
      case "experiments": return ok(experiments);
      case "reports": {
        const k = query.get("kind");
        return ok({ items: reports.items.filter((r: J) => !k || r.kind === k) });
      }
      case "settings": return ok(settings);
      case "assistant/runs": return ok({ items: runs });
      case "usage": return ok(snap.usage);
    }
    if (/^ideas\/\d+$/.test(sub)) {
      const id = Number(sub.split("/")[1]);
      const base = snap[sub] ?? { posts: [], children: [], history: [] };
      const cur = ideas.find((i) => i.id === id);
      return cur ? ok({ ...base, ...cur }) : err(404, "not_found", "対象が見つかりません");
    }
    if (snap[sub]) return ok(snap[sub]);
    return err(404, "not_found", "対象が見つかりません");
  }

  // ---- writes
  if (sub === "demo/scenario") {
    const name = body.name as string;
    if (name === "disconnect") { offlineUntil = Date.now() + 15000; return ok({ ok: true, message: "15秒間、接続断を再現します" }); }
    if (name === "reconnect") { offlineUntil = 0; return ok({ ok: true, message: "接続を復帰しました" }); }
    if (name === "generate_now") { simulate("content", "generate_post", "投稿生成・チェック", 5000, () => emit("post.ready", "投稿を予約しました", "success")); return ok({ ok: true, message: "投稿の生成を開始しました" }); }
    if (name === "publish_now") { publishFlow(); return ok({ ok: true, message: "生成後、テスト公開します" }); }
    if (name === "fail_publish") { publishFlow("error"); return ok({ ok: true, message: "公開失敗を再現します" }); }
    if (name === "unknown_publish") { publishFlow("unknown"); return ok({ ok: true, message: "結果不明を再現します" }); }
    if (name === "advance_metrics") { simulate("threads_ops", "collect_metrics", "実績取得", 3000, () => emit("metrics.collected", "実績を取得（24時間後）", "success")); return ok({ ok: true, message: "実績取得を前倒ししました" }); }
    if (name === "run_analysis") { simulate("analytics", "analyze", "分析・自動改善", 5000, () => emit("experiment.started", "改善実験を継続中: 書き出し 問いかけ → 結論先出し（データ収集中）")); return ok({ ok: true, message: "分析を開始しました" }); }
    if (name === "run_reports") { simulate("analytics", "daily_report", "日次レポート", 4000, () => emit("report.generated", "日次レポートを作成（v2）", "success")); return ok({ ok: true, message: "日次レポートを再生成します" }); }
    return err(409, "conflict", "unknown scenario");
  }
  if (sub === "control/autopilot") {
    overview.autopilot_enabled = !!body.enabled;
    emit("control.toggled", `自動運用を${body.enabled ? "ON" : "OFF"}にしました`);
    return ok({ enabled: !!body.enabled, settings_version: ++settings.version });
  }
  if (sub === "control/improvement") {
    overview.improvement_enabled = !!body.enabled;
    emit("control.toggled", `自動改善を${body.enabled ? "ON" : "OFF"}にしました`);
    return ok({ enabled: !!body.enabled, settings_version: ++settings.version });
  }
  if (sub === "control/stop") {
    overview.autopilot_enabled = false;
    const n = jobs.filter((j) => j.status === "queued").length;
    jobs.forEach((j) => { if (j.status === "queued") j.status = "cancelled"; });
    emit("control.toggled", "自動運用をOFFにしました");
    return ok(body.mode === "cancel_queued" ? { mode: body.mode, jobs_cancelled: n, cancel_requested: 0, not_cancellable: [], posts_cancelled: 0 } : { mode: body.mode });
  }
  if (/^jobs\/\d+\/cancel$/.test(sub)) {
    const j = jobs.find((x) => x.id === Number(sub.split("/")[1]));
    if (j && j.status === "queued") { j.status = "cancelled"; emit("job.cancel_cancelled", "待機中のジョブを取り消しました", "warning"); return ok({ result: "cancelled", message: "待機中のジョブを取り消しました" }); }
    return err(409, "conflict", "このジョブは取り消せません");
  }
  if (/^jobs\/\d+\/retry$/.test(sub)) {
    const j = jobs.find((x) => x.id === Number(sub.split("/")[1]));
    if (j) { j.status = "queued"; j.last_error = null; }
    return ok({ result: "queued" });
  }
  if (sub === "settings") {
    if (body.expected_version !== settings.version) return err(409, "conflict", `settings were updated by someone else (current version ${settings.version})`);
    const merge = (a: J, b: J): J => { const o = { ...a }; for (const [k, v] of Object.entries(b)) o[k] = v && typeof v === "object" && !Array.isArray(v) && typeof a[k] === "object" ? merge(a[k], v as J) : v; return o; };
    settings.settings = merge(settings.settings, body.patch ?? {});
    settings.version += 1;
    overview.require_approval = settings.settings.require_approval;
    emit("settings.updated", "設定を更新しました");
    return ok({ version: settings.version, settings: settings.settings });
  }
  if (sub === "policy/rollback") {
    const target = policy.versions.find((v: J) => v.version === body.version);
    if (!target) return err(404, "not_found", "対象が見つかりません");
    const v = Math.max(...policy.versions.map((x: J) => x.version)) + 1;
    policy.versions.forEach((x: J) => { x.is_active = 0; });
    const nv = { ...clone(target), version: v, parent_version: policy.active.version, source: "rollback", reason: `手動でv${body.version}へ差し戻し`, is_active: 1, created_at: now(), created_by: "demo" };
    policy.versions.unshift(nv);
    policy.active = nv;
    overview.policy = { version: v, source: "rollback", reason: nv.reason, created_at: now() };
    emit("policy.updated", `運用方針 v${v} を有効化（${nv.reason}）`, "success");
    return ok({ new_version: v });
  }
  if (sub === "experiments/stop") {
    const e = experiments.items.find((x: J) => x.status === "running");
    if (!e) return err(409, "conflict", "実行中の実験はありません");
    e.status = "stopped"; e.ended_at = now();
    emit("experiment.ended", `改善実験#${e.id}を終了（停止）`);
    return ok({ stopped: e.id });
  }
  if (sub === "reports/regenerate") {
    simulate("analytics", "daily_report", "日次レポート", 3500, () => emit("report.generated", "レポートを再生成しました", "success"));
    return ok({ job_id: nextId, status: "queued" });
  }
  if (sub === "ideas") {
    const id = nextId++;
    const it = { id, account_id: "demo", ...body, origin: "manual", status: body.status ?? "ready", use_count: 0, last_used_at: null,
      parent_idea_id: null, created_at: now(), updated_at: now() };
    ideas.unshift(it);
    emit("idea.created", `ネタを追加: ${body.theme}／${body.angle || body.pain || ""}`);
    return ok(it);
  }
  if (/^ideas\/\d+$/.test(sub)) {
    const it = ideas.find((i) => i.id === Number(sub.split("/")[1]));
    if (!it) return err(404, "not_found", "対象が見つかりません");
    if (body.expected_updated_at && body.expected_updated_at !== it.updated_at) return err(409, "conflict", "このネタは他の操作で更新されています");
    Object.assign(it, { theme: body.theme, pain: body.pain, appeal: body.appeal, angle: body.angle, notes: body.notes, updated_at: now() });
    return ok(it);
  }
  if (/^ideas\/\d+\/status$/.test(sub)) {
    const it = ideas.find((i) => i.id === Number(sub.split("/")[1]));
    if (!it) return err(404, "not_found", "対象が見つかりません");
    it.status = body.status === "ready" && it.use_count > 0 ? "used" : body.status;
    it.updated_at = now();
    return ok(it);
  }
  if (sub === "assistant/runs") {
    const id = nextId++;
    const run: J = { id, account_id: "demo", kind: body.kind, status: "running", error: null, created_by: "demo", created_at: now(),
      updated_at: now(), input: body, output: null, draft_post_id: null };
    runs.unshift(run);
    const sample = runs.find((r) => r.kind === body.kind && r.output);
    simulate(body.kind === "improvement" ? "analytics" : "content", "assistant", "AI補助", 3000, () => {
      run.status = "succeeded";
      run.output = sample ? clone(sample.output) : { summary: "（サンプル）運用は安定しています。" };
      run.draft_post_id = sample?.draft_post_id ?? null;
      emit("assistant.completed", "AI補助の結果が届きました", "success");
    });
    return ok(run);
  }
  if (/^posts\/\d+\/(approve|cancel|resolve)$/.test(sub)) {
    emit("post.updated", "（サンプル）投稿の操作を受け付けました", "info");
    return ok({ result: "ok", message: "（サンプル）受け付けました" });
  }
  if (/^posts\/\d+\/text$/.test(sub)) return ok({ check: { passed: true, issues: [] } });
  if (sub === "connection/check") return err(409, "conflict", "デモ/テストアカウントはThreadsに接続しません");
  return err(404, "not_found", "対象が見つかりません");
}

export function installMockServer() {
  const real = window.fetch.bind(window);
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, location.href);
    if (!url.pathname.startsWith("/api/")) return real(input, init);
    const method = (init?.method ?? "GET").toUpperCase();
    let body: J = {};
    try { body = init?.body ? JSON.parse(String(init.body)) : {}; } catch { body = {}; }
    await new Promise((r) => setTimeout(r, 80 + Math.random() * 120)); // feel like a network
    return handle(method, url.pathname, url.searchParams, body);
  };
}
