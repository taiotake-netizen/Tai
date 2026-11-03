# 検証記録（2026-11-03、開発用クラウド環境）

実投稿は一度も行っていません。Threads API と OpenAI API への実通信もしていません（この環境にはキーが無く、`developers.facebook.com` への接続も許可されていないため）。外部APIの振る舞いはモック（`httpx.MockTransport`）で検証しました。

## 1. 自動テスト

| 対象 | コマンド | 結果 |
|---|---|---|
| エンジン 単体・結合 | `cd threads-automation && uv run pytest -q` | **43 passed** |
| エンジン lint | `uv run ruff check .` | 問題なし |
| 管理画面 型 | `npm run typecheck` | 問題なし |
| 管理画面 lint | `npm run lint` | 問題なし |
| 管理画面 単体 | `npm test` | **8 passed** |
| 管理画面 ビルド | `npm run build` | 成功 |
| ブラウザ（Playwright + Chromium、デモ構成） | `npm run e2e` | **27/27 passed**（2回連続） → `docs/e2e-results.json` |

### 指示書の「必須の検証」との対応

| 項目 | 検証したテスト |
|---|---|
| タスク状態遷移 | `test_cancel_semantics`、`test_full_loop` |
| 二重クリック・再送・並行実行 | `test_enqueue_idempotent_and_single_claim`、`test_ai_concurrency_limit`、`test_repeated_ticks_*`、`test_events_cursor_and_ingest_idempotent` |
| 予約時刻と日本時間の集計境界 | `test_daily_and_weekly_periods_in_jst` |
| 投稿結果不明時の復旧 | `test_dead_worker_during_publish_becomes_unknown_then_reconciled`、`test_live_publish_timeout_becomes_unknown_and_reconciles`（公開APIは1回だけ呼ばれることを確認） |
| ネタの重複選択・失敗時の状態 | `test_idea_reservation_is_exclusive_and_released_on_failure`、`test_idea_reuse_interval`、`test_ai_not_configured_keeps_post_unpublished` |
| 類似投稿の抑止 | `test_quality_rules`（同文・類似・テーマ/CTA連続） |
| イベント重複・順序逆転 | `test_events_cursor_and_ingest_idempotent`、`core.test.ts`（重複除去・seq順） |
| データ取得失敗・不足 | `test_failed_metrics_are_excluded_not_zero`、`test_insufficient_data_does_not_decide`、`test_live_publish_flow_with_mocked_api`（未提供指標はNULL） |
| 許可範囲外の改善変更の拒否 | `test_policy_envelope`（変更幅超過・固定項目・候補外の時刻・未知のキー） |
| 方針更新と次回生成への反映 | `test_policy_update_reaches_next_generation`、`test_experiment_adoption_updates_policy_within_step` |
| 方針の差し戻し | `test_auto_rollback_on_drop_and_manual_rollback`、ブラウザ（改善画面） |
| レポート重複生成・再生成 | `test_report_idempotent_and_regenerate`、`test_full_loop`（期間ごと1件） |
| AI未接続・予算到達 | `test_ai_not_configured_*`、`test_openai_budget_required_and_enforced`、`test_assistant_unavailable_when_no_ai` |
| 認証なしアクセス拒否 | `test_auth_required`、`test_production_requires_token`、e2e「unauthenticated API is rejected」 |
| 他ユーザーのデータアクセス拒否 | `test_account_scope_isolation`、e2e「other account blocked」、`server.test.ts`（署名改ざん） |
| デモと実データの分離 | `test_live_ideas_never_mix_with_test_ideas`、`test_dry_run_never_publishes_non_test_post`、セッションの接続先固定 |
| OpenAIの未対応パラメーター | `test_openai_drops_unsupported_param`（`reasoning` を外して再送、`temperature` は送らない） |

### 一連のフロー（`test_full_loop`）
ネタ選択 → 投稿生成 → チェック → 予約保存 → テスト用公開（dry-run） → テスト実績取得（24h/72h） → 分析 → 実験開始・判定 → 方針更新 → 次回生成へ反映 → 日次/週次レポート を、時計を進めて **18日分** 実行。公開43件以上・すべて `is_test=1`・外部IDは `dryrun-`。

## 2. ブラウザ確認（e2e 27項目）

デスクトップ1440px／モバイル390px、キーボード移動、エージェント選択（aria-pressed）、5種のドロワー、テスト公開がアクティビティに出ること、ネタ編集が再読み込み後も残ること、設定の更新競合（409）、切断→「接続待ち」→復帰、横スクロールなし、モバイルで3D縮小（高さ176px）、動きを減らす設定、WebGL無効時の代替表示、CSRF・未認証・別アカウント・パス操作の拒否、予期しないコンソールエラーなし。
スクリーンショット：`docs/screenshots/`。

## 3. 継続運転（D）

1. daemon（スケジューラー＋ワーカー）を停止（SIGTERM）。
2. 停止中に分析ジョブを投入。
3. 約180秒後、`/v1/health` が `scheduler_alive=false, worker_alive=false`、管理画面が「エンジン停止」「接続待ち」、担当カードが「未接続：ワーカーが停止しています」を表示（`docs/screenshots/daemon-stopped.png`）。
4. daemon を再起動 → 停止中に投入したジョブが **3秒後に完了**。

ブラウザを閉じた状態でもエンジンは動き続けます（管理画面はエンジンの処理に関与しない構成）。ただし Mac 上での launchd 常駐は、この環境では実施していません。

## 4. この検証で見つけて直した不具合

- 自動改善の重み計算で、配分を引く途中に合計が変わり変更幅の上限を超える → 事前に配分を計算するよう修正（`test_experiment_adoption_*`）。
- スケジューラーの毎回の実行で、既存の枠でも「枠を作成」イベントが出る／IDが消費される → 存在確認を先に行うよう修正（`test_repeated_ticks_*`）。
- デモ操作で作った投稿が、スケジュール外の枠として自動取消される → 手動扱い（origin=manual）に修正（`test_manual_posts_survive_schedule_cleanup`）。
- `.env` の行末コメントが値に含まれる → 読み込み時に除去。

## 5. 未検証

- 実際の Threads API（投稿・insights・トークン）との通信、公式仕様との照合
- 実際の OpenAI API との通信（`test-llm` はモックで成功、キー未設定時は「OPENAI_API_KEY が未設定です」で停止することを確認）、`gpt-5.4-mini` の実際の応答形式
- Mac の launchd による常駐、スリープ復帰後の挙動
- 実機（iPhone等）での3D描画性能
