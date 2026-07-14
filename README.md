# asari_manager

Discord 上から各 Bot のデプロイ、起動状態確認、出席管理、現地イベントの参加募集を行う管理 Bot です。

## 主な機能

- `/deploy` で指定した Bot を更新して再起動
- `/checkbot` で各 Bot の systemd 状態を確認
- `/reboot` で asari_manager 自身を更新して再起動
- 毎朝 8 時に「初星学園へ登校する」ボタンを投稿
- 前日の登校者上位 5 名を翌朝の投稿に表示
- 毎週日曜 20 時に登校ランキングを投稿
- `/event` で現地イベントの参加募集を作成
- イベント募集の「参加する」「参加キャンセル」ボタンで参加者一覧を自動更新

## セットアップ

依存関係をインストールします。

```bash
pip install -r requirements.txt
```

`.env.example` を参考に `.env` を作成してください。

```env
DISCORD_TOKEN=
SERVER_ID=
STARTUP_CHANNEL_ID=
ATTENDANCE_CHANNEL_ID=

DEVELOPER_ROLE_ID=
```

各項目の意味は以下です。

- `DISCORD_TOKEN`: asari_manager の Discord Bot トークン
- `SERVER_ID`: slash command を登録する Discord サーバー ID
- `STARTUP_CHANNEL_ID`: asari_manager 起動時に通知を送るチャンネル ID
- `ATTENDANCE_CHANNEL_ID`: 登校ボタンやランキングを投稿するチャンネル ID
- `DEVELOPER_ROLE_ID`: 管理系コマンドを実行できるロール ID

## Bot 設定

`bots.yml` に管理対象 Bot を登録します。

```yaml
bots:
  saki:
    path: /home/st/discord/saki
    service: saki.service
```

- `path`: 対象 Bot のリポジトリパス
- `service`: systemd service 名

## コマンド

### `/deploy`

指定した Bot をデプロイして再起動します。

実行内容:

1. `git fetch origin`
2. `git reset --hard origin/main`
3. `.venv/bin/pip install -r requirements.txt`
4. `systemctl restart`
5. `systemctl show/status` と `journalctl` で起動状態を確認

起動できていれば `active / running` と表示します。起動に失敗している可能性がある場合は、状態と直近ログを Discord に投稿します。

実行には `DEVELOPER_ROLE_ID` のロールが必要です。

### `/checkbot`

Bot の systemd 状態を確認します。

- Bot 名を指定した場合: 対象 Bot の詳細状態と直近ログを表示
- Bot 名を省略した場合: 登録済み Bot 全体の簡易状態を一覧表示

実行には `DEVELOPER_ROLE_ID` のロールが必要です。

### `/reboot`

asari_manager 自身を更新して再起動します。

実行内容:

1. `git fetch origin`
2. `git reset --hard origin/main`
3. `.venv/bin/pip install -r requirements.txt`
4. `systemctl restart asari_manager.service`

自分自身を再起動するため、Discord には「これから再起動します」まで投稿します。再起動後は起動通知チャンネルに起動メッセージが送られます。

実行には `DEVELOPER_ROLE_ID` のロールが必要です。

### `/event`

現地イベントの参加募集を作成します。

入力項目:

- `title`: イベント名
- `organizer`: 企画者
- `location`: 開催場所
- `budget`: 予算
- `capacity`: 定員
- `start_at`: 開始日時
- `end_at`: 終了予定
- `signup_deadline`: 募集締切
- `location_url`: 場所のリンク、省略可
- `note`: 備考、省略可

日時は以下の形式で入力します。

```text
2026-07-20 20:00
2026/07/20 20:00
```

作成されたイベント投稿には以下のボタンが付きます。

- `参加する`: 参加希望者に追加
- `参加キャンセル`: 参加希望を取り消し

参加者一覧はボタン操作ごとに自動更新されます。募集締切後は新規参加できません。定員に達した場合も新規参加できません。

実行には `DEVELOPER_ROLE_ID` のロールが必要です。

## 登校機能

毎朝 8 時に `ATTENDANCE_CHANNEL_ID` へ以下の内容を投稿します。

- 朝のメッセージ
- 前日の登校者上位 5 名
- `初星学園へ登校する` ボタン

ユーザーがボタンを押すと、その日の登校者として記録され、本人だけに以下の起動リンクが表示されます。

- iPhone版（App Store）
- Android版（Google Play）
- PC版（DMM GAMES）

同じユーザーが同じ日に複数回押しても、記録は 1 回だけです。記録済みの場合も起動リンクは再表示されます。

毎週日曜 20 時には、その週の登校ランキングを投稿します。

## 保存ファイル

Bot は以下の JSON ファイルにデータを保存します。

- `attendance.json`: 登校記録、投稿済み日付、週間ランキング投稿履歴
- `events.json`: イベント情報、参加者一覧、イベント番号

これらのファイルは自動生成されます。

## sudoers 設定

`/deploy`、`/checkbot`、`/reboot` を Discord から実行するには、Bot 実行ユーザーが password なしで `systemctl` と `journalctl` を実行できる必要があります。

例:

```sudoers
st ALL=NOPASSWD: /bin/systemctl restart saki.service
st ALL=NOPASSWD: /bin/systemctl is-active saki.service
st ALL=NOPASSWD: /bin/systemctl show saki.service *
st ALL=NOPASSWD: /bin/systemctl status saki.service --no-pager
st ALL=NOPASSWD: /bin/journalctl -u saki.service -n 40 --no-pager

st ALL=NOPASSWD: /bin/systemctl restart asari_manager.service
```

環境によって `systemctl` や `journalctl` のパスが異なる場合があります。サーバーで以下を確認し、コード側の `SYSTEMCTL` / `JOURNALCTL` と sudoers のパスを合わせてください。

```bash
which systemctl
which journalctl
```

## 起動

```bash
python main.py
```

systemd で運用する場合は、`asari_manager.service` を作成して常駐させてください。
