# Endpoint Challenges Plugin - GCE Auto-Cleanup

このプラグインは、GCEインスタンスの自動クリーンアップ機能を提供します。

## クリーンアップ方法

### 1. リクエスト時の自動クリーンアップ

ユーザーがエンドポイントチャレンジを起動する際、自動的に古いインスタンスがクリーンアップされます。

### 2. CLI コマンドによる手動実行

```bash
# クリーンアップを手動実行
flask endpoint-challenges cleanup
```

このコマンドは、cron等で定期実行することができます:

```bash
# 例: 30分ごとに実行
*/30 * * * * cd /path/to/CTFd && /path/to/venv/bin/flask endpoint-challenges cleanup >> /var/log/ctfd-cleanup.log 2>&1
```

### 3. アプリケーション内での自動スケジューリング (推奨)

環境変数を設定することで、CTFdアプリケーション起動時に自動的にバックグラウンドでクリーンアップが実行されます。

## 環境変数

### 必須

- `GCP_PROJECT`: GCPプロジェクトID
- `GCP_ZONE`: GCEインスタンスのゾーン (例: `us-central1-a`)

### オプション

- `GCE_TTL_HOURS`: インスタンスの有効期限（時間）。この時間を超えたインスタンスは削除対象となります。
  - デフォルト: `3` (3時間)
  - 例: `GCE_TTL_HOURS=6`

- `GCE_AUTO_CLEANUP_ENABLED`: 自動クリーンアップの有効化
  - デフォルト: `false`
  - 有効にする場合: `true`, `1`, `yes` のいずれか
  - 例: `GCE_AUTO_CLEANUP_ENABLED=true`

- `GCE_CLEANUP_INTERVAL_MINUTES`: 自動クリーンアップの実行間隔（分）
  - デフォルト: `30` (30分)
  - 例: `GCE_CLEANUP_INTERVAL_MINUTES=15`

- `GCP_MACHINE_TYPE`: GCEインスタンスのマシンタイプ
  - デフォルト: `e2-micro`
  - 例: `GCP_MACHINE_TYPE=e2-small`

## 設定例

### Docker Compose での設定例

```yaml
version: '3'
services:
  ctfd:
    image: ctfd/ctfd:latest
    environment:
      # GCP設定
      - GCP_PROJECT=my-gcp-project
      - GCP_ZONE=us-central1-a
      - GCP_MACHINE_TYPE=e2-micro
      
      # クリーンアップ設定
      - GCE_TTL_HOURS=3
      - GCE_AUTO_CLEANUP_ENABLED=true
      - GCE_CLEANUP_INTERVAL_MINUTES=30
      
      # GCP認証（サービスアカウントキー）
      - GOOGLE_APPLICATION_CREDENTIALS=/app/gcp-key.json
    volumes:
      - ./gcp-key.json:/app/gcp-key.json:ro
```

### 環境変数ファイル (.env) での設定例

```bash
# GCP設定
GCP_PROJECT=my-gcp-project
GCP_ZONE=us-central1-a
GCP_MACHINE_TYPE=e2-micro

# クリーンアップ設定
GCE_TTL_HOURS=3
GCE_AUTO_CLEANUP_ENABLED=true
GCE_CLEANUP_INTERVAL_MINUTES=30

# GCP認証
GOOGLE_APPLICATION_CREDENTIALS=/path/to/gcp-key.json
```

### システムサービスでの設定例

```bash
# /etc/systemd/system/ctfd.service
[Unit]
Description=CTFd Service
After=network.target

[Service]
Type=simple
User=ctfd
WorkingDirectory=/opt/CTFd
Environment="GCP_PROJECT=my-gcp-project"
Environment="GCP_ZONE=us-central1-a"
Environment="GCE_TTL_HOURS=3"
Environment="GCE_AUTO_CLEANUP_ENABLED=true"
Environment="GCE_CLEANUP_INTERVAL_MINUTES=30"
Environment="GOOGLE_APPLICATION_CREDENTIALS=/opt/CTFd/gcp-key.json"
ExecStart=/opt/CTFd/venv/bin/gunicorn --bind 0.0.0.0:8000 'CTFd:create_app()'
Restart=always

[Install]
WantedBy=multi-user.target
```

## 依存パッケージ

自動スケジューリング機能を使用する場合、APSchedulerが必要です:

```bash
pip install apscheduler
```

または `requirements.txt` に追加:

```
apscheduler>=3.10.0
```

APSchedulerがインストールされていない場合、自動スケジューリングは無効化されますが、CLI コマンドは引き続き使用できます。

## クリーンアップの仕組み

1. **TTLベース**: インスタンスの作成時刻から `GCE_TTL_HOURS` で設定した時間を超えたインスタンスを削除対象とします
2. **ラベルフィルタリング**: `labels.app = ctfd-endpoint` のラベルを持つインスタンスのみが対象となります
3. **安全な削除**: 削除処理は個別に行われ、一部が失敗しても他のインスタンスの削除を継続します

## トラブルシューティング

### クリーンアップが実行されない

- 環境変数 `GCE_AUTO_CLEANUP_ENABLED=true` が設定されているか確認
- APSchedulerがインストールされているか確認: `pip list | grep APScheduler`
- ログを確認: アプリケーション起動時に "GCE auto-cleanup scheduled" メッセージが出力されるはず

### 権限エラー

GCPサービスアカウントに以下の権限が必要です:
- `compute.instances.list`
- `compute.instances.delete`
- `compute.instances.get`

推奨ロール: `Compute Instance Admin (v1)` または `Compute Admin`

### CLI コマンドが見つからない

```bash
# 利用可能なコマンドを確認
flask --help

# endpoint-challenges コマンドグループが表示されるはず
flask endpoint-challenges --help
```

## 推奨設定

### 少数ユーザー環境
```bash
GCE_TTL_HOURS=2
GCE_AUTO_CLEANUP_ENABLED=true
GCE_CLEANUP_INTERVAL_MINUTES=15
```

### 中規模環境
```bash
GCE_TTL_HOURS=3
GCE_AUTO_CLEANUP_ENABLED=true
GCE_CLEANUP_INTERVAL_MINUTES=30
```

### cronとの併用（冗長性確保）
アプリケーション内スケジューリングとcronの両方を設定することで、より確実なクリーンアップが可能です:

```bash
# アプリケーション内: 30分ごと
GCE_AUTO_CLEANUP_ENABLED=true
GCE_CLEANUP_INTERVAL_MINUTES=30

# cron: 1時間ごと（バックアップ）
0 * * * * cd /opt/CTFd && /opt/CTFd/venv/bin/flask endpoint-challenges cleanup
```
