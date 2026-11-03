// Builds a single self-contained HTML preview of the console that runs on sample data in the browser.
// Prereq: `npm run build` (reuses the compiled Tailwind CSS). Usage: node scripts/build-standalone.mjs [out.html]
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const out = process.argv[2] ?? path.join(root, "standalone", "dist", "ai-control-center-app.html");
const tmp = path.join(root, "standalone", "dist", "bundle.js");
fs.mkdirSync(path.dirname(out), { recursive: true });
fs.mkdirSync(path.dirname(tmp), { recursive: true });

execFileSync("npx", ["esbuild", "standalone/main.tsx", "--bundle", "--minify", "--format=iife", "--target=es2020", "--jsx=automatic",
  "--loader:.json=json", "--alias:next/navigation=./standalone/next-navigation.ts", "--alias:next/dynamic=./standalone/next-dynamic.tsx",
  "--alias:@=.", "--define:process.env.NODE_ENV=\"production\"", `--outfile=${tmp}`, "--log-level=warning"], { cwd: root, stdio: "inherit" });

const cssDir = path.join(root, ".next", "static", "chunks");
const cssFile = fs.readdirSync(cssDir).find((f) => f.endsWith(".css"));
if (!cssFile) throw new Error("compiled CSS not found: run `npm run build` first");
const css = fs.readFileSync(path.join(cssDir, cssFile), "utf8");
const js = fs.readFileSync(tmp, "utf8").replaceAll("</script", "<\\/script");

const html = `<title>AI CONTROL CENTER</title>
<meta name="claude:viewport-fit-sides" content="cover">
<style>${css}
#root > div { padding-left: max(16px, env(safe-area-inset-left, 0px)) !important; padding-right: max(16px, env(safe-area-inset-right, 0px)) !important; }
.sample-note { font: 12px/1.5 "Noto Sans JP","Hiragino Sans",system-ui,sans-serif; color: #8CA6BD; text-align: center; padding: 6px max(16px, env(safe-area-inset-right, 0px)) 0 max(16px, env(safe-area-inset-left, 0px)); background: #050B14; }
</style>
<p class="sample-note">サンプルデータで動く管理画面です。操作はこのブラウザの中だけで再現され、Threadsへの投稿や外部への通信は行いません。</p>
<div id="root"></div>
<script>${js}</script>
`;
fs.writeFileSync(out, html);
fs.rmSync(tmp);
console.log(`wrote ${out} (${Math.round(html.length / 1024)} KB)`);
