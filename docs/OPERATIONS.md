# 運用手順（継続運転・再起動・バックアップ・復旧・本番切替・停止・差し戻し）

## 1. 常時稼働

### Mac（launchd）
```bash
REPO=$(pwd)   # このリポジトリのルート
mkdir -p threads-automation/data control-center/data
for f in deploy/launchd/*.plist; do
  sed "s#__REPO__#$REPO#g" "$f" > ~/Library/LaunchAgents/$(basename "$f")
  launchctl load -w ~/Library/LaunchAgents/$(basename "$f")
done
launchctl list | grep com.tai      # 3つ（daemon / api / control-center）が表示されること
```
- `KeepAlive` によりプロセスが落ちても10秒後に自動で再起動します。ログは各 `data/*.log`。
- **スリープ対策**：Macがスリープ中は処理が止まります。「システム設定 → バッテリー（電源アダプタ）→ ディスプレイがオフのときに自動でスリープさせない」をONにするか、`caffeinate -s` を併用してください。スリープから復帰すると、時刻を過ぎた投稿は**後から投稿せずスキップ**します（`missed_grace_minutes`、既定20分）。
- 停止：`launchctl unload -w ~/Library/LaunchAgents/com.tai.threads-ops.daemon.plist`

### Linux（systemd）
`deploy/systemd/*.service` を `/etc/systemd/system/` に置き、`systemctl enable --now threads-ops-daemon threads-ops-api control-center`。

## 2. 状態確認
```bash
cd threads-automation
uv run python -m threads_ops status       # スケジューラー/ワーカーの心拍、AIの可否
uv run python -m threads_ops check-env    # 環境変数の有無（値は表示しない）
```
管理画面のヘッダーが「エンジン停止」なら、スケジューラーかワーカーの心拍が180秒以上ありません。

## 3. 再起動と障害時の動き

| 状況 | 動き | 対応 |
|---|---|---|
| ワーカーが処理中に停止 | リース（5分）切れで検出。生成・分析・レポート・実績取得は再実行。**公開処理は再実行せず「結果不明」→自動照会** | 不要（照会で解決しない場合は画面で「公開されていた／いなかった」を選ぶ） |
| Threadsへの公開がタイムアウト | 「結果不明」。直近の投稿一覧と本文を照合（3回まで） | 解決しなければ画面で確定 |
| 実績取得の失敗 | 30分×回数で再試行（最大4回）。失敗は0として扱わず「取得失敗」と記録 | 不要 |
| AI予算到達・未設定 | AIジョブを停止（課金しない）。予定の投稿は時刻超過でスキップ | 設定で予算を見直す |
| OpenAIの障害 | 生成は10分後に再試行（予定時刻を過ぎるならスキップ）。レポートは集計だけで作成 | 不要 |
| Threadsトークン期限切れ | 接続確認（6時間ごと）で「トークン期限切れ」表示。公開は失敗として記録 | 新しいトークンを `.env` に設定して daemon を再起動 |

複数のワーカーを起動しても、ジョブの取得はDBの書き込みロック内で行うため二重実行されません。

## 4. バックアップと復旧
```bash
cd threads-automation
uv run python -m threads_ops backup backups/threads_ops-$(date +%Y%m%d).db   # 稼働中でも安全（SQLite backup API）
```
- 推奨：毎日1回（cron/launchd）。`backups/` はGit管理外です。
- 復旧：daemon と api を止める → `data/threads_ops.db` をバックアップで置き換える（`-wal`/`-shm` ファイルは削除）→ 起動。
- 復旧後、バックアップ時点より後に公開された投稿はDBにありません。Threadsアプリで確認し、必要なら手動で記録してください。

## 5. 本番開始前チェックリスト（ユーザー承認が必要）

1. [ ] 対象アカウント：`init-account` の `--threads-user-id` が正しい／管理画面「接続確認」が「接続済み」
2. [ ] Threads API仕様を公式ドキュメントで照合（エンドポイント、500文字、24時間の投稿上限、insightsの指標名、権限 `threads_basic`,`threads_content_publish`,`threads_manage_insights`）
3. [ ] 事業情報・承認済みの事実・CTA・許可ドメイン・禁止表現を入力
4. [ ] 投稿予定：投稿数／時刻候補／投稿可能時間帯／投稿前承認の要否
5. [ ] モデル：`OPENAI_MODEL`、`test-llm` が成功
6. [ ] 予算：日次・月次の上限、単価（OpenAI料金ページの値）。自動チャージの有無をOpenAI側で確認
7. [ ] テスト運用：本番投稿OFFのまま自動運用ONで1〜2日、テスト投稿・レポートを確認
8. [ ] **n8nとの重複防止**（下記）
9. [ ] 停止方法を確認（下記）

## 6. 本番切替手順

1. **n8n を止める前に**、n8n の次回投稿時刻を確認し、それと重ならない時刻を新システムの開始時刻にする。
2. n8n の Threads 投稿ワークフローを「Inactive」にする（**ユーザーが実施**。こちらでは停止していません）。n8n側で投稿予定が残っていないことを確認。
3. エンジンの `.env` で `PUBLISH_MODE=live` にして daemon と api を再起動。
4. 管理画面「設定 → 本番投稿」で「本番投稿をONにする」（確認文の入力が必要）。
5. 最初の1件は「投稿前承認ON」のまま、承認して公開されることを確認。問題なければ承認の要否を決める。
6. 公開後、24時間後の実績取得と翌朝の日次レポートを確認。

## 7. 停止手順

| やりたいこと | 操作 |
|---|---|
| 今後の投稿を止める（予約停止） | 管理画面「予約停止」 |
| 待機中の処理もすべて取り消す | 管理画面「停止＋取消」 |
| 本番投稿だけ止めてテスト運用に戻す | 設定「本番投稿をOFFにする」 または `PUBLISH_MODE=dry_run` で再起動 |
| エンジンごと止める | `launchctl unload -w ~/Library/LaunchAgents/com.tai.threads-ops.daemon.plist` |
| n8nへ戻す | 上記で本番投稿OFF → n8nのワークフローを Active に |

公開済みの投稿はどの操作でも取り消されません（必要ならThreadsアプリで削除）。

## 8. 差し戻し

- **運用方針**：管理画面「改善 → 変更履歴 → この版に戻す」。自動改善で悪化した場合は自動でも差し戻されます（設定の低下率・件数）。
- **自動改善を止める**：管理画面「自動改善を停止」。方針は現状のまま固定されます。
- **コード**：`git log` で前のコミットを確認し、`git checkout <commit>` → daemon/api/管理画面を再起動。DBマイグレーションは前方互換で追加のみです。

## 9. トークン更新（Threads 長期トークン、約60日）
新しいトークンを取得し `.env` の `THREADS_ACCESS_TOKEN` を更新 → daemon と api を再起動 → 管理画面で「接続確認」。
