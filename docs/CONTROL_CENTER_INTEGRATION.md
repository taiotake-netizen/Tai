# CONTROL CENTER ⇄ Threads運用エンジン 連携仕様

## 1. 構成と責任分担

```
[ブラウザ] ──Cookie(署名付きセッション)──▶ [control-center (Next.js)]
                                              │  BFF: /api/cc/{account}/{path}
                                              │  ・ログイン必須 ・アカウント範囲チェック ・許可リスト ・CSRF
                                              ▼  Bearer トークン + X-Account-Scope + X-Actor（サーバー間のみ）
                                   [threads-automation API (FastAPI) 127.0.0.1:8787]
                                              │  同じSQLite（WAL）
                                   [threads-automation daemon: scheduler + worker] ──▶ Threads API / OpenAI API
```

| 責任 | 正本 |
|---|---|
| 投稿枠の作成、生成、品質チェック、予約、公開、結果照会、実績取得 | threads-automation（daemon） |
| 自動改善（実験・方針バージョン・差し戻し）、ネタ選択・補充・派生、日次／週次レポート | threads-automation（daemon） |
| 設定・方針・ネタ・レポート・イベント・監査ログの保存 | threads-automation（SQLite） |
| ログイン、利用者ごとのアカウント範囲、表示、設定編集、操作の受付 | control-center |
| 3D演出の状態（business state → visual state の変換） | control-center（`lib/coreState.ts`） |

- 管理画面が停止してもエンジンは動き続けます（ブラウザのタイマーやHTTP応答後のメモリ処理に依存しない）。
- スケジューラーと改善処理はエンジンにのみ存在し、管理画面には重複実装していません。
- ブラウザにはエンジンのURL・トークンもOpenAI/Threadsの認証情報も渡しません。

## 2. API契約（v1）

- **バージョン**：`/v1/...`、`api_version`（現在 `2026-11-01`）を `/v1/health` と `capabilities` で返します。破壊的変更は `/v2` で行います。
- **認証**：`Authorization: Bearer <THREADS_OPS_API_TOKEN>`。`APP_ENV=production` でトークン未設定なら起動を拒否します。`/v1/health` のみ認証不要（業務データは含みません）。
- **権限**：`X-Account-Scope: main,sub`（`*` は全件）。範囲外のアカウントは存在を明かさず 404。`X-Actor` は監査ログに記録。閲覧専用ユーザーの書き込みは BFF が 403 で拒否。
- **ID**：内部ID（整数）`job_id`/`post_id`/`idea_id`/`report_id`、`account_id`（文字列）、`event_id`（UUID文字列）、外部ID `external_post_id`/`external_container_id`（Threads）。`system_id` は `source_system`（既定 `threads-ops`）。
- **日時**：すべてUTCのISO-8601（`2026-11-03T17:59:08.123456Z`）。画面ではAsia/Tokyoで表示。「本日」・日次・週次はAsia/Tokyoの境界で集計。
- **エラー形式**：`{"error": {"code": "...", "message": "日本語の説明", "details": ...}}`。主なコード：`unauthorized`(401) `not_found`(404) `conflict`(409) `validation_error`/`policy_violation`(422) `ai_*`(503) `demo_disconnected`(503)。
- **ページング**：`limit`/`offset`（投稿・ネタ）、`before_id`（ジョブ）、`after_seq`（イベント差分取得）。
- **タイムアウト**：BFF→エンジン 読み取り8秒、書き込み20秒。エンジン→OpenAI 60秒、→Threads 30秒。
- **再試行**：読み取りはBFFが最大3回（指数バックオフ）。**書き込みは自動再試行しません**。BFFが書き込み応答を受け取れなかった場合は `write_outcome_unknown`(504) を返し、画面は状態を再取得します。
- **冪等性**：ジョブは `idempotency_key` の一意制約で重複しません（例 `publish:{post_id}:{slot}`、`report:daily:{account}:{period_start}`）。イベント取り込み（`POST /events/ingest`）は `event_id` で重複を無視。
- **設定の更新競合**：`PATCH /settings` は `expected_version` 必須。古い版なら 409。ネタ・投稿本文の編集は `expected_updated_at` で同様に検出。
- **操作の可否**：`GET /v1/accounts/{id}/capabilities` が `{action: {enabled, reason}}` を返し、画面は無効な操作を無効表示にします（例：`publish.live`、`assistant.*`、`post.delete_published` は常に無効）。

### 主なエンドポイント

| 能力 | メソッドとパス（`/v1/accounts/{account_id}` 以下） |
|---|---|
| ヘルス | `GET /v1/health` |
| 運用状態・KPI・担当・要対応 | `GET overview` |
| 操作可否 | `GET capabilities` |
| タスク | `GET jobs` / `POST jobs/{id}/cancel` / `POST jobs/{id}/retry` |
| 投稿予定・履歴 | `GET posts?view=upcoming|history|attention` / `GET posts/{id}` / `POST posts/{id}/approve|cancel|resolve` / `PATCH posts/{id}/text` |
| イベント | `GET events?after_seq=` / `POST events/ingest` |
| ネタ | `GET/POST ideas` / `GET/PUT ideas/{id}` / `POST ideas/{id}/status` |
| 方針・改善実験 | `GET policy` / `POST policy/rollback` / `GET experiments` / `POST experiments/stop` |
| レポート | `GET reports` / `GET reports/{id}` / `POST reports/regenerate` |
| 設定 | `GET settings` / `PATCH settings` |
| 制御 | `POST control/autopilot` / `POST control/improvement` / `POST control/stop` / `POST connection/check` |
| 利用量・監査 | `GET usage` / `GET audit` |
| AI補助 | `GET/POST assistant/runs` |

完全な定義は `threads-automation/docs/openapi.json`（`python -m threads_ops export-openapi` で再生成）。

## 3. 状態と遷移

**投稿（posts.status）**
```
planned → generating → awaiting_approval → scheduled → publishing → published
                    ↘ scheduled（承認不要時）            ↘ unknown → (照会) → published | failed
任意の未公開状態 → cancelled（取消） / skipped（品質不合格・時刻超過・自動運用OFF・本番無効）
publishing の失敗 → failed（自動再投稿はしない）
```
**ジョブ（jobs.status）**：`queued → running → succeeded | failed | cancelled`、実行中の取消は `cancel_requested`（受付）→ 区切りで `cancelled`（完了）。公開処理中は取消不可（理由を返す）。ワーカー停止はリース期限で検出し、公開ジョブだけは再実行せず `unknown` → 照会。

**「停止」の意味**
- `pause_schedule`（予約停止）：自動運用OFF。新しい枠を作らず、予約済みも公開しません。公開済みには影響しません。
- `cancel_queued`（停止＋取消）：上記＋待機ジョブ取消＋未公開の予定を取消＋実行中ジョブへ取消要求。取消できなかったものは理由付きで返します。
- 公開済み投稿の取り消しは対象外（Threadsアプリで削除）。

## 4. イベント

`events(seq, event_id, account_id, source_system, event_type, severity, occurred_at, received_at, job_id, post_id, message, payload)`

- `seq` は単調増加のカーソル。画面は `after_seq` で差分取得し、再接続時は取り逃し分をまとめて取得（`has_more` が false になるまで）。
- 画面側は `event_id` で重複除去し `seq` 順に並べるため、重複・順序逆転があっても表示は安定します。
- 状態の正本はイベントではなくテーブル（posts/jobs）です。古いイベントで新しい状態を上書きすることはありません。
- 成功演出（3Dの波紋）は、新着の成功イベントについて `event_id` ごとに一度だけ再生（`sessionStorage` に記録）。初回読み込みの履歴では再生しません。

## 5. 3D演出の状態定義

優先順位：`disconnected`（エンジン不達・スケジューラー/ワーカーの心拍が180秒途絶）＞ `error`（担当が要確認・結果不明の投稿あり）＞ `executing`（公開・照会・実績取得・接続確認が実行中）＞ `thinking`（生成・分析・レポート・ネタ補充・AI補助が実行中）＞ `idle`。
`success` は状態ではなく一時演出。担当カードを選ぶと、その担当の状態だけで演出します。

## 6. データの分離

- デモ：`APP_ENV=demo` のエンジン（別DB・モックAI・dry-run固定）にだけ接続。セッションの `m=demo` で接続先が決まり、実データ側には到達できません。
- テスト：本番投稿が無効な間に作られた投稿は `is_test=1`。分析・レポート・ネタ選択は、実アカウントでは `is_test=0` のデータだけを使います。
- API未設定時に自動でデモへ切り替えることはありません（「未接続」と表示）。

## 7. 拡張点（今回は未実装）

- 他SNS：`accounts.platform`、`threads_api.py` と同じ形のクライアント、`publishing.py` の分岐。
- 外部システムのイベント：`POST events/ingest`（冪等）。
