// Browser checks against a running demo stack (engine in APP_ENV=demo + `next start` with CC_DEMO_ENABLED=true).
// Usage: BASE_URL=http://localhost:3000 OUT_DIR=./test-results node scripts/e2e.mjs
// Never touches real Threads/OpenAI: the demo engine uses the dry-run publisher and the mock LLM.
import fs from "node:fs";
import { createRequire } from "node:module";

// uses the globally installed Playwright (or a local one if present)
const { chromium } = createRequire(import.meta.url)("playwright");

const BASE = process.env.BASE_URL ?? "http://localhost:3000";
const OUT = process.env.OUT_DIR ?? "test-results";
fs.mkdirSync(OUT, { recursive: true });
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok, detail }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? ` — ${detail}` : ""}`); };

async function login(page) {
  await page.goto(`${BASE}/login`);
  await page.getByRole("button", { name: "デモで確認する" }).click();
  await page.waitForURL(`${BASE}/`);
  await page.getByText("AI CONTROL CENTER").first().waitFor();
  await page.locator("[aria-label^='AIコアの状態']").waitFor();
  await page.waitForTimeout(2500);
}

async function noHorizontalScroll(page) {
  return page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
}

const browser = await chromium.launch({ args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
try {
  // ---------------------------------------------------------------- API protection
  {
    const ctx = await browser.newContext();
    const r1 = await ctx.request.get(`${BASE}/api/cc/demo/overview`);
    check("unauthenticated API is rejected", r1.status() === 401, `status ${r1.status()}`);
    const r2 = await ctx.request.post(`${BASE}/api/auth/login`, { data: { mode: "demo" } });
    check("login without same-origin headers is rejected (CSRF)", r2.status() === 403, `status ${r2.status()}`);
    await ctx.close();
  }

  // ---------------------------------------------------------------- desktop
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 960 }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));
  await login(page);
  check("dashboard renders with demo badge", await page.getByText("デモデータ").first().isVisible());
  check("3D canvas mounted", (await page.locator("canvas").count()) > 0);
  check("agent card + org chart node present", (await page.getByRole("button", { pressed: false }).filter({ hasText: "コンテンツ制作" }).count()) === 2);
  check("org chart rendered", await page.getByRole("heading", { name: "AI組織図" }).isVisible()
    && (await page.locator("section[aria-labelledby='org-title'] svg path").count()) > 4);
  check("desktop: no horizontal scroll", await noHorizontalScroll(page));
  await page.screenshot({ path: `${OUT}/desktop.png`, fullPage: true });

  // cross-account access through the BFF must fail
  const other = await page.request.get(`${BASE}/api/cc/main/overview`);
  check("other account blocked for demo session", other.status() === 404, `status ${other.status()}`);
  const badPath = await page.request.get(`${BASE}/api/cc/demo/../../v1/health`);
  check("path traversal blocked", badPath.status() === 404 || badPath.status() === 401, `status ${badPath.status()}`);
  const writeNoHeader = await page.request.post(`${BASE}/api/cc/demo/control/autopilot`, { data: { enabled: false } });
  check("write without CSRF header rejected", writeNoHeader.status() === 403, `status ${writeNoHeader.status()}`);

  // keyboard: tab reaches nav buttons with visible focus
  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  const focused = await page.evaluate(() => document.activeElement?.tagName);
  check("keyboard focus moves to interactive elements", focused === "BUTTON" || focused === "A" || focused === "SELECT", String(focused));

  // agent selection drives the core label
  await page.getByRole("button").filter({ hasText: "集客分析" }).first().click();
  const pressed = await page.getByRole("button", { pressed: true }).count();
  check("selection syncs agent card and org chart node", pressed === 2);
  check("core shows selected department", (await page.getByText("集客分析", { exact: true }).first().isVisible()));
  await page.getByRole("button", { name: "全体表示に戻す" }).click();

  // demo scenario: generate + publish → success events appear in activity, core reacts
  await page.getByRole("button", { name: "今すぐテスト公開" }).click();
  await page.getByText(/テスト公開|生成後/).first().waitFor({ timeout: 10000 });
  let sawPublish = false;
  for (let i = 0; i < 30 && !sawPublish; i++) {
    await page.waitForTimeout(2000);
    sawPublish = await page.getByText("テスト公開（実際には投稿していません）").first().isVisible().catch(() => false);
  }
  check("dry-run publish visible in activity feed", sawPublish);
  await page.screenshot({ path: `${OUT}/desktop-after-publish.png` });

  // drawers open and render real data
  for (const [label, expectText] of [["ネタ", "ネタ管理"], ["改善", "運用方針と改善実験"], ["レポート", "レポート"], ["AI補助", "AI補助"], ["設定", "設定"]]) {
    await page.getByRole("navigation", { name: "詳細メニュー" }).getByRole("button", { name: label }).click();
    const dlg = page.getByRole("dialog");
    await dlg.waitFor();
    const ok = await dlg.getByRole("heading", { name: expectText }).isVisible();
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${OUT}/drawer-${label}.png` });
    check(`drawer ${label} opens`, ok);
    await page.keyboard.press("Escape");
    await dlg.waitFor({ state: "hidden" });
  }

  // edit an idea → persists after reload
  await page.getByRole("navigation", { name: "詳細メニュー" }).getByRole("button", { name: "ネタ" }).click();
  await page.getByRole("dialog").locator("ul li button").first().click();
  await page.getByRole("button", { name: "編集" }).click();
  const stamp = `E2E切り口${Date.now() % 100000}`;
  await page.getByLabel("切り口").fill(stamp);
  await page.getByRole("button", { name: "保存" }).click();
  await page.getByText(stamp).first().waitFor({ timeout: 8000 });
  await page.keyboard.press("Escape");
  await page.reload();
  await page.locator("[aria-label^='AIコアの状態']").waitFor();
  await page.getByRole("navigation", { name: "詳細メニュー" }).getByRole("button", { name: "ネタ" }).click();
  await page.getByRole("dialog").getByLabel("検索").fill(stamp);
  await page.getByRole("dialog").getByRole("button", { name: "絞り込む" }).click();
  const persisted = await page.getByRole("dialog").getByText(stamp).first().isVisible({ timeout: 8000 }).catch(() => false);
  check("idea edit persists across reload", persisted);
  await page.keyboard.press("Escape");

  // settings conflict handling: stale version → 409 surfaced
  const sres = await page.evaluate(async () => {
    const s = await fetch("/api/cc/demo/settings").then((r) => r.json());
    const h = { "content-type": "application/json", "x-cc-request": "1" };
    const a = await fetch("/api/cc/demo/settings", { method: "PATCH", headers: h, body: JSON.stringify({ expected_version: s.version, patch: { reports: { ai_summary: true } } }) });
    const b = await fetch("/api/cc/demo/settings", { method: "PATCH", headers: h, body: JSON.stringify({ expected_version: s.version, patch: { reports: { ai_summary: true } } }) });
    return [a.status, b.status];
  });
  check("settings update conflict detected", sres[0] === 200 && sres[1] === 409, sres.join(","));

  // disconnect scenario → core shows 接続待ち, then recovers
  await page.getByRole("button", { name: "切断を再現" }).click();
  let disc = false;
  for (let i = 0; i < 12 && !disc; i++) {
    await page.waitForTimeout(1500);
    disc = (await page.locator("[aria-label='AIコアの状態: 接続待ち']").count()) > 0;
  }
  check("disconnected state shown", disc);
  await page.screenshot({ path: `${OUT}/desktop-disconnected.png` });
  await page.evaluate(() => fetch("/api/cc/demo/demo/scenario", { method: "POST", headers: { "content-type": "application/json", "x-cc-request": "1" }, body: JSON.stringify({ name: "reconnect" }) }));
  let back = false;
  for (let i = 0; i < 12 && !back; i++) {
    await page.waitForTimeout(1500);
    back = (await page.locator("[aria-label='AIコアの状態: 接続待ち']").count()) === 0;
  }
  check("recovers after reconnect", back);

  const relevant = errors.filter((e) => !/Failed to load resource: the server responded with a status of (503|409|404)/.test(e));
  check("no unexpected console errors (desktop)", relevant.length === 0, relevant.slice(0, 3).join(" | "));
  await ctx.close();

  // ---------------------------------------------------------------- mobile
  const mctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1, isMobile: true, hasTouch: true });
  const m = await mctx.newPage();
  await login(m);
  check("mobile: no horizontal scroll", await noHorizontalScroll(m));
  const coreBox = await m.locator("[aria-label^='AIコアの状態']").boundingBox();
  check("mobile: 3D core is compact", !!coreBox && coreBox.height <= 200, `h=${coreBox?.height}`);
  await m.screenshot({ path: `${OUT}/mobile.png`, fullPage: true });
  await mctx.close();

  // ---------------------------------------------------------------- reduced motion
  const rctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: "reduce" });
  const r = await rctx.newPage();
  await login(r);
  check("reduced motion: page works", await r.getByText("直近のアクティビティ").isVisible());
  await rctx.close();

  // ---------------------------------------------------------------- no WebGL
  const wctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  await wctx.addInitScript(() => {
    const orig = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (type, ...rest) {
      if (String(type).startsWith("webgl")) return null;
      return orig.call(this, type, ...rest);
    };
  });
  const w = await wctx.newPage();
  const werr = [];
  w.on("pageerror", (e) => werr.push(String(e)));
  await login(w);
  check("no WebGL: fallback shown", await w.getByText("この端末では3D表示を省略しています").isVisible());
  check("no WebGL: console still usable", await w.getByText("投稿予定・履歴").isVisible() && werr.length === 0, werr.join(" | "));
  await w.screenshot({ path: `${OUT}/no-webgl.png` });
  await wctx.close();
} finally {
  await browser.close();
  fs.writeFileSync(`${OUT}/e2e-results.json`, JSON.stringify(results, null, 2));
  const failed = results.filter((r) => !r.ok);
  console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
  process.exitCode = failed.length ? 1 : 0;
}
