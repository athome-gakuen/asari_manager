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
- `/event_edit` で作成済みイベントの内容を変更
- `/event_cancel` でイベントを取り消して募集投稿を削除
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

### イベント管理

イベントの作成、変更、取り消しには `DEVELOPER_ROLE_ID` で指定した developer ロールが必要です。通常はイベント企画チャンネルでコマンドを実行してください。

イベントを作成するとイベント番号が自動で割り当てられ、募集投稿の最下部に `イベント No.12` のように表示されます。イベントを変更または取り消すときは、この番号を指定します。

#### `/event` — イベントを作成する

コマンドを実行したチャンネルに、現地イベントの参加募集を投稿します。そのため、`/event` はイベント企画チャンネルで実行してください。

| 項目 | 必須 | 内容 |
| --- | --- | --- |
| `title` | はい | イベント名 |
| `organizer` | はい | 企画者名 |
| `location` | はい | 開催場所 |
| `budget` | はい | 予算。例: `3000円程度` |
| `capacity` | はい | 定員。1人以上を指定 |
| `start_at` | はい | 開始日時 |
| `end_at` | はい | 終了予定日時 |
| `signup_deadline` | はい | 参加募集の締切日時 |
| `location_url` | いいえ | 地図や店舗ページなどのリンク |
| `note` | いいえ | 持ち物などの補足情報 |

日時は日本時間として、次のいずれかの形式で入力します。

```text
2026-07-20 20:00
2026/07/20 20:00
```

終了予定は開始日時より後、募集締切は開始日時以前にする必要があります。

入力例:

```text
/event
title: 打ち上げ
organizer: あさり
location: ○○駅前 △△店
budget: 3000円程度
capacity: 10
start_at: 2026-07-20 20:00
end_at: 2026-07-20 22:00
signup_deadline: 2026-07-18 23:59
location_url: https://example.com/shop
note: 現地集合
```

作成された募集投稿には次のボタンが付きます。

- `参加する`: 操作したユーザーを参加希望者一覧に追加します。
- `参加キャンセル`: 操作したユーザーを参加希望者一覧から削除します。イベント自体は取り消しません。

参加者一覧はボタン操作ごとに自動更新されます。同じユーザーの重複登録はできません。募集締切後または定員到達後は、新しく参加できません。参加済みユーザーの参加キャンセルは引き続き可能です。

#### `/event_edit` — イベントを変更する

作成済みイベントの内容を変更します。`event_id` を選び、変更したい項目だけ入力してください。入力しなかった項目と参加者一覧はそのまま保持されます。

| 項目 | 必須 | 内容 |
| --- | --- | --- |
| `event_id` | はい | 変更するイベント番号 |
| `title` | いいえ | 新しいイベント名 |
| `organizer` | いいえ | 新しい企画者名 |
| `location` | いいえ | 新しい開催場所 |
| `budget` | いいえ | 新しい予算 |
| `capacity` | いいえ | 新しい定員 |
| `start_at` | いいえ | 新しい開始日時 |
| `end_at` | いいえ | 新しい終了予定日時 |
| `signup_deadline` | いいえ | 新しい募集締切日時 |
| `location_url` | いいえ | 新しい場所リンク |
| `note` | いいえ | 新しい備考 |
| `message_channel` | いいえ | 古いイベントの投稿先をBotが判別できない場合だけ指定 |

`event_id` の入力欄には、取り消されていないイベントが新しい順に候補表示されます。候補に出ない場合でも、募集投稿の下部にあるイベント番号を直接入力できます。

場所リンクまたは備考を削除したい場合は、変更する項目に `-`、`なし`、`削除` のいずれかを入力します。

日時を1項目だけ変更することもできますが、変更後も次の関係を満たす必要があります。

```text
募集締切 <= 開始日時 < 終了予定
```

定員は現在の参加希望者数より少ない人数には変更できません。

開始時刻と終了時刻を変更する例:

```text
/event_edit
event_id: 12
start_at: 2026-07-20 19:30
end_at: 2026-07-20 21:30
```

備考だけを削除する例:

```text
/event_edit
event_id: 12
note: -
```

変更に成功すると元の募集投稿が更新され、同じイベント企画チャンネルに次の情報を含む更新通知が投稿されます。

- イベント番号とイベント名
- 変更した項目
- 更新したユーザー
- 更新後の募集投稿へのリンク

#### `/event_cancel` — イベントを取り消す

イベントを取り消し、イベント企画チャンネルにある元の募集投稿を削除します。

| 項目 | 必須 | 内容 |
| --- | --- | --- |
| `event_id` | はい | 取り消すイベント番号 |
| `reason` | いいえ | 取り消し理由 |
| `message_channel` | いいえ | 古いイベントの投稿先をBotが判別できない場合だけ指定 |

入力例:

```text
/event_cancel
event_id: 12
reason: 会場を確保できなかったため
```

実行に成功すると、次の処理が行われます。

1. 元のイベント募集メッセージを削除します。
2. `events.json` のイベントを取り消し済みとして保持します。
3. 同じイベント企画チャンネルへ、イベント番号、イベント名、理由、削除したユーザーを通知します。

募集投稿の削除は元に戻せません。イベント投稿が見つからない場合やBotに削除権限がない場合は取り消し処理を中止し、`events.json` の状態も変更しません。

#### 既存イベントを変更・削除する場合

現在の形式で作成したイベントは投稿先チャンネルが自動保存されるため、通常は `message_channel` の指定は不要です。

機能追加前に作成した古いイベントなど、`events.json` に投稿先チャンネルが保存されていないイベントは、次のどちらかの方法で操作してください。

- 元の募集投稿があるイベント企画チャンネルでコマンドを実行する。
- `message_channel` にイベント企画チャンネルを指定する。

#### イベント操作でエラーが出る場合

- `イベント No.X が見つかりませんでした`: 募集投稿下部の番号と入力した `event_id` が一致しているか確認してください。
- `イベント投稿が見つかりませんでした`: 元投稿が残っているか確認し、イベント企画チャンネルで再実行するか `message_channel` を指定してください。
- `developer ロールを持っている人だけ実行できます`: 操作ユーザーに `DEVELOPER_ROLE_ID` のロールが付いているか確認してください。
- 日時のエラー: 入力形式と、募集締切・開始日時・終了予定の前後関係を確認してください。
- 通知だけ失敗した場合: イベントの更新または削除は完了しています。Botがイベント企画チャンネルへ投稿できるか確認してください。

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
- `events.json`: イベント情報、参加者一覧、イベント番号、投稿先チャンネル、更新・取り消し状態

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
