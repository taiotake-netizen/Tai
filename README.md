# Tai — Threads自動運用システム ＋ AI CONTROL CENTER

副業サロンのThreads集客を「企画 → 投稿 → 実績取得 → 分析 → 方針更新 → 次回投稿」で自動で回す仕組みと、その中央管理画面です。
Codexで作っている既存の `かっこいいシステム構築` とは**別物として新規に**作っています（コード・DB・ポートを共有しません）。

| ディレクトリ | 役割 | 技術 |
|---|---|---|
| `threads-automation/` | **正本**。投稿生成・品質チェック・予約・公開・実績取得・自動改善・ネタ管理・レポート・スケジューラー／ワーカー・API | Python 3.11+ / FastAPI / SQLite（WAL） / uv |
| `control-center/` | 認証・表示・設定編集・操作（BFF経由でエンジンAPIを呼ぶだけ。スケジューラーは持たない） | Next.js 16 / React 19 / Tailwind 4 / React Three Fiber |
| `docs/` | 連携仕様・運用手順・検証記録 | — |
| `deploy/` | 常時稼働用の launchd（Mac）／systemd（Linux）テンプレート | — |

詳しくは [`docs/CONTROL_CENTER_INTEGRATION.md`](docs/CONTROL_CENTER_INTEGRATION.md)（連携・責任分担・API契約）、
[`docs/OPERATIONS.md`](docs/OPERATIONS.md)（継続運転・バックアップ・復旧・本番切替／停止／差し戻し）、
[`docs/VERIFICATION.md`](docs/VERIFICATION.md)（実行した検証と結果）を参照してください。
機械可読なAPI仕様は [`threads-automation/docs/openapi.json`](threads-automation/docs/openapi.json) です。

---

## 1. ローカル起動（デモ：外部API・実投稿なし）

必要なもの：Python 3.11+ と [uv](https://docs.astral.sh/uv/)、Node.js 20+。

```bash
# エンジン（デモ用DB・モックAI・dry-run公開）
cd threads-automation
uv sync
export APP_ENV=demo THREADS_OPS_API_TOKEN=demo-local-token-change-me
uv run python -m threads_ops seed-demo          # デモデータ作成（すべて架空・テスト扱い）
uv run python -m threads_ops api --port 8788 &  # API
uv run python -m threads_ops run &              # スケジューラー＋ワーカー

# 管理画面
cd ../control-center
npm ci
cat > .env.local <<'ENV'
CC_DEMO_ENABLED=true
DEMO_THREADS_OPS_URL=http://127.0.0.1:8788
DEMO_THREADS_OPS_API_TOKEN=demo-local-token-change-me
ENV
npm run build && npm run start                   # http://localhost:3000 →「デモで確認する」
```

デモ画面上部の「デモ操作」で、生成開始／テスト公開／公開失敗／結果不明／実績取得／分析／レポート再生成／切断を再現できます。
デモは**デモ用エンジンにしか接続しません**。実データとは混ざりません。

## 2. 実データ接続（本番投稿はまだOFFのまま）

```bash
cd threads-automation
cp .env.example .env      # 値を記入（OPENAI_API_KEY、THREADS_OPS_API_TOKEN など）。.env はGitに入りません
uv run python -m threads_ops check-env            # 設定の有無だけ表示（値は表示しない）
uv run python -m threads_ops test-llm             # 投稿なしの最小生成テスト（出力上限256トークン）
uv run python -m threads_ops init-account --id main --name "メイン" \
    --threads-user-id <ThreadsのユーザーID> --token-env THREADS_ACCESS_TOKEN
uv run python -m threads_ops api --port 8787 &
uv run python -m threads_ops run &

cd ../control-center
npm run hash-password      # 表示されたハッシュを CC_USERS に入れる
# .env.local に CC_SESSION_SECRET / CC_USERS / THREADS_OPS_URL / THREADS_OPS_API_TOKEN を設定
npm run build && npm run start
```

初期状態は **自動運用OFF・本番投稿OFF・投稿前承認ON・AI予算未設定（＝AI処理停止）** です。
管理画面の「設定」で事業情報・承認済みの事実・予算（日次／月次・単価）を入れ、「自動運用を開始」すると、
本番投稿OFFの間は**テスト投稿（実際には投稿しない）**として一連の流れが動きます。

## 3. 必要な環境変数（名前のみ）

- エンジン：`APP_ENV` `THREADS_OPS_DB` `THREADS_OPS_API_TOKEN` `LLM_PROVIDER` `OPENAI_API_KEY` `OPENAI_MODEL` `OPENAI_REASONING_EFFORT` `OPENAI_TIMEOUT_S` `AI_MAX_CONCURRENCY` `PUBLISH_MODE` `THREADS_ACCESS_TOKEN`（名前は変更可） `THREADS_API_BASE` `WORKER_ID` → [`threads-automation/.env.example`](threads-automation/.env.example)
- 管理画面：`CC_SESSION_SECRET` `CC_USERS` `THREADS_OPS_URL` `THREADS_OPS_API_TOKEN` `CC_DEMO_ENABLED` `DEMO_THREADS_OPS_URL` `DEMO_THREADS_OPS_API_TOKEN` `CC_ALLOWED_UPSTREAM_HOSTS` → [`control-center/.env.example`](control-center/.env.example)

## 4. スケジューラー・ワーカー

`python -m threads_ops run` が1プロセスでスケジューラー（30秒ごと）とワーカーを動かします。ブラウザや管理画面を閉じても動き続けます。
別々に動かす場合は `run --no-worker` / `run --no-scheduler`。複数起動しても、ジョブは一意キーとリース（DBロック）で二重実行されません。
常時稼働は `deploy/launchd/*.plist`（Mac）または `deploy/systemd/*.service`（Linux）を使います（手順は OPERATIONS.md）。

## 5. 実投稿なしのテスト

```bash
cd threads-automation && uv run pytest -q && uv run ruff check .
cd control-center && npm run typecheck && npm run lint && npm test && npm run build
# ブラウザ確認（デモ構成を起動した状態で）
cd control-center && npm run e2e
```

## 6. デプロイ先ごとの設定

| 置き場所 | エンジン | 管理画面 | 注意 |
|---|---|---|---|
| 自分のMac（推奨・初期） | launchd で `run` と `api` | launchd で `npm run start` | Macがスリープすると止まります（OPERATIONS.md の「スリープ対策」） |
| Linuxサーバー／VPS | systemd | systemd ＋ リバースプロキシ（HTTPS必須） | `.env` は権限600。APIは 127.0.0.1 に限定 |
| Vercel等のサーバーレス | **不可**（常駐プロセスとSQLiteが必要） | 可（エンジンへの到達経路と `CC_ALLOWED_UPSTREAM_HOSTS` が必要） | 新たな有料契約は行っていません |

## 7. 現在の制約・未実装

- Threads API の仕様（エンドポイント・500文字制限・24時間250投稿・指標名）は**実装時点の知識に基づいており、この環境から公式ドキュメントへ接続できなかったため未照合**です。本番前に照合してください（OPERATIONS.md チェックリスト）。
- 実際のThreadsアカウント・OpenAI APIへの接続は**この開発環境では未実施**です（キーがこの環境に無いため）。モックと擬似応答で検証済み。
- Threadsのアクセストークン自動更新は未実装（60日ごとに手動更新。期限切れは接続確認で検知して画面に表示）。
- 既存n8nとの切替は手順書のみ（停止操作は行っていません）。
- Instagram／X／TikTok、DM・コメント返信、流入・入会計測は対象外（拡張点：`accounts.platform` と `threads_api.py` の差し替え）。
- 統計判定は簡易（Welchのt値＋最低件数＋最小上昇率）。画面上は「傾向」「暫定」と表示し、確定的な効果としては扱いません。
