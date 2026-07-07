import os
import json
import asyncio
import subprocess
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
import discord
import yaml
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
STARTUP_CHANNEL_ID = int(os.getenv("STARTUP_CHANNEL_ID"))
SERVER_ID = int(os.getenv("SERVER_ID"))

DEVELOPER_ROLE_ID = int(os.getenv("DEVELOPER_ROLE_ID"))
ATTENDANCE_CHANNEL_ID = int(os.getenv("ATTENDANCE_CHANNEL_ID"))
JST = timezone(timedelta(hours=9))
ATTENDANCE_FILE = Path(__file__).with_name("attendance.json")
EVENTS_FILE = Path(__file__).with_name("events.json")

BASE_DIR = Path(__file__).resolve().parent
BOTS_FILE = BASE_DIR / "bots.yml"
SYSTEMCTL = "/bin/systemctl"
JOURNALCTL = "/bin/journalctl"
ASARI_MANAGER_SERVICE = "asari_manager.service"


def load_bots() -> dict:
    if not BOTS_FILE.exists():
        return {}

    try:
        with BOTS_FILE.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file)
    except (OSError, yaml.YAMLError):
        return {}

    if not isinstance(data, dict):
        return {}

    bots = data.get("bots", {})

    if not isinstance(bots, dict):
        return {}

    return bots


def today_jst() -> date:
    return datetime.now(JST).date()


def now_jst() -> datetime:
    return datetime.now(JST)


def load_attendance_data() -> dict:
    if not ATTENDANCE_FILE.exists():
        return {
            "attendance": {},
            "daily_posts": {},
            "daily_reports": {},
            "weekly_announcements": {},
        }

    try:
        with ATTENDANCE_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (json.JSONDecodeError, OSError):
        data = {}

    data.setdefault("attendance", {})
    data.setdefault("daily_posts", {})
    data.setdefault("daily_reports", {})
    data.setdefault("weekly_announcements", {})
    return data


def save_attendance_data(data: dict) -> None:
    tmp_path = ATTENDANCE_FILE.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    tmp_path.replace(ATTENDANCE_FILE)


def load_events_data() -> dict:
    if not EVENTS_FILE.exists():
        return {
            "next_id": 1,
            "events": {},
        }

    try:
        with EVENTS_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (json.JSONDecodeError, OSError):
        data = {}

    data.setdefault("next_id", 1)
    data.setdefault("events", {})
    return data


def save_events_data(data: dict) -> None:
    tmp_path = EVENTS_FILE.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    tmp_path.replace(EVENTS_FILE)


def parse_event_datetime(value: str) -> datetime | None:
    for fmt in ("%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=JST)
        except ValueError:
            continue
    return None


def format_event_datetime(value: str) -> str:
    try:
        target = datetime.fromisoformat(value).astimezone(JST)
    except (TypeError, ValueError):
        return "日時不明"
    return target.strftime("%Y年%m月%d日 %H時%M分")


def find_event_by_message_id(data: dict, message_id: int) -> tuple[str | None, dict | None]:
    for event_id, event in data["events"].items():
        if str(event.get("message_id")) == str(message_id):
            return event_id, event
    return None, None


def build_event_embed(event_id: str, event: dict) -> discord.Embed:
    participants = event.get("participants", {})
    sorted_participants = sorted(
        participants.items(),
        key=lambda item: item[1].get("joined_at", ""),
    )
    if sorted_participants:
        participant_lines = [
            f"- <@{user_id}>"
            for user_id, _ in sorted_participants
        ]
        participant_body = "\n".join(participant_lines)
    else:
        participant_body = "まだ参加希望者はいません。"

    capacity = int(event.get("capacity", 0))
    embed = discord.Embed(
        title=str(event.get("title", "現地イベント")),
        color=discord.Color.green(),
    )
    embed.add_field(
        name="参加者一覧",
        value=participant_body,
        inline=False,
    )
    embed.add_field(
        name="企画者",
        value=str(event.get("organizer", "未設定")),
        inline=False,
    )
    embed.add_field(
        name="開始日時",
        value=f"{format_event_datetime(event.get('start_at', ''))}から",
        inline=False,
    )
    embed.add_field(
        name="終了予定",
        value=f"{format_event_datetime(event.get('end_at', ''))}まで",
        inline=False,
    )
    embed.add_field(
        name="場所",
        value=str(event.get("location", "未設定")),
        inline=False,
    )
    location_url = str(event.get("location_url", "")).strip()
    if location_url:
        embed.add_field(
            name="場所リンク",
            value=location_url,
            inline=False,
        )
    embed.add_field(
        name="予算",
        value=str(event.get("budget", "未設定")),
        inline=False,
    )
    embed.add_field(
        name="定員",
        value=f"{len(sorted_participants)} / {capacity} 人",
        inline=False,
    )
    embed.add_field(
        name="募集締切",
        value=f"{format_event_datetime(event.get('signup_deadline', ''))}まで",
        inline=False,
    )

    note = str(event.get("note", "")).strip()
    if note:
        embed.add_field(name="備考", value=note, inline=False)

    embed.set_footer(text=f"イベント No.{event_id}")
    return embed


def week_range(target: date) -> tuple[date, date]:
    start = target - timedelta(days=target.weekday())
    end = start + timedelta(days=6)
    return start, end


def iso_week_key(target: date) -> str:
    year, week, _ = target.isocalendar()
    return f"{year}-W{week:02d}"


def build_weekly_ranking(target: date) -> tuple[str, list[tuple[str, int]]]:
    data = load_attendance_data()
    start, end = week_range(target)
    counts: dict[str, dict[str, object]] = {}

    current = start
    while current <= end:
        day_data = data["attendance"].get(current.isoformat(), {})
        for user_id, record in day_data.items():
            user = counts.setdefault(
                user_id,
                {
                    "name": record.get("name", f"User {user_id}"),
                    "count": 0,
                },
            )
            user["count"] = int(user["count"]) + 1
        current += timedelta(days=1)

    ranking = sorted(
        ((str(user["name"]), int(user["count"])) for user in counts.values()),
        key=lambda item: (-item[1], item[0].casefold()),
    )
    period = f"{start.isoformat()} 〜 {end.isoformat()}"
    return period, ranking


def build_daily_attendance_report(target: date) -> tuple[str, list[tuple[str, str]]]:
    data = load_attendance_data()
    target_date = target.isoformat()
    day_data = data["attendance"].get(target_date, {})

    attendees: list[tuple[str, str]] = []
    for user_id, record in day_data.items():
        name = record.get("name", f"User {user_id}")
        attended_at = record.get("attended_at", "")

        try:
            attended_time = datetime.fromisoformat(attended_at).astimezone(JST).strftime("%H:%M")
        except (TypeError, ValueError):
            attended_time = "時刻不明"

        attendees.append((str(name), attended_time))

    attendees.sort(key=lambda item: (item[1], item[0].casefold()))
    return target_date, attendees


def build_previous_attendance_summary(target: date) -> str:
    report_date, attendees = build_daily_attendance_report(target)
    top_attendees = attendees[:5]

    if not top_attendees:
        return f"昨日（{report_date}）は登校した人はいませんでした。"

    lines = [
        f"{index}. {name} さん（{attended_time}）"
        for index, (name, attended_time) in enumerate(top_attendees, start=1)
    ]
    return (
        f"昨日（{report_date}）は以下の方が初星学園へ登校していました。\n"
        f"{chr(10).join(lines)}\n"
        "引き続きプロデュース頑張ってください。"
    )


class AttendanceView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="初星学園へ登校",
        style=discord.ButtonStyle.primary,
        custom_id="asari_manager:attendance:check_in",
    )
    async def check_in(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        user = interaction.user
        if user.bot:
            await interaction.response.send_message(
                "Botは初星学園への登校記録の対象外です。",
                ephemeral=True,
            )
            return

        target_date = today_jst().isoformat()
        user_id = str(user.id)
        data = load_attendance_data()
        day_data = data["attendance"].setdefault(target_date, {})

        if user_id in day_data:
            await interaction.response.send_message(
                f"{target_date} の初星学園への登校は記録済みです。",
                ephemeral=True,
            )
            return

        day_data[user_id] = {
            "name": user.display_name,
            "attended_at": now_jst().isoformat(),
        }
        save_attendance_data(data)

        await interaction.response.send_message(
            f"{user.display_name} さんの初星学園への登校を記録しました。",
            ephemeral=True,
        )


class EventParticipationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="参加する",
        style=discord.ButtonStyle.success,
        custom_id="asari_manager:event:join",
    )
    async def join_event(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await handle_event_participation(interaction, join=True)

    @discord.ui.button(
        label="参加キャンセル",
        style=discord.ButtonStyle.danger,
        custom_id="asari_manager:event:cancel",
    )
    async def cancel_event(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await handle_event_participation(interaction, join=False)


async def handle_event_participation(
    interaction: discord.Interaction,
    join: bool,
) -> None:
    user = interaction.user
    if user.bot:
        await interaction.response.send_message(
            "Botはイベント参加希望の対象外です。",
            ephemeral=True,
        )
        return

    if interaction.message is None:
        await interaction.response.send_message(
            "イベントメッセージを確認できませんでした。",
            ephemeral=True,
        )
        return

    data = load_events_data()
    event_id, event = find_event_by_message_id(data, interaction.message.id)
    if event_id is None or event is None:
        await interaction.response.send_message(
            "このイベント情報が見つかりませんでした。",
            ephemeral=True,
        )
        return

    try:
        deadline = datetime.fromisoformat(str(event.get("signup_deadline"))).astimezone(JST)
    except (TypeError, ValueError):
        deadline = None

    if join and deadline is not None and now_jst() > deadline:
        await interaction.response.send_message(
            "このイベントの参加募集は締め切られています。",
            ephemeral=True,
        )
        return

    participants = event.setdefault("participants", {})
    user_id = str(user.id)

    if join:
        if user_id in participants:
            await interaction.response.send_message(
                "このイベントには参加希望済みです。",
                ephemeral=True,
            )
            return

        capacity = int(event.get("capacity", 0))
        if capacity > 0 and len(participants) >= capacity:
            await interaction.response.send_message(
                "このイベントは定員に達しています。",
                ephemeral=True,
            )
            return

        participants[user_id] = {
            "name": user.display_name,
            "joined_at": now_jst().isoformat(),
        }
        message = "参加希望を受け付けました。"
    else:
        if user_id not in participants:
            await interaction.response.send_message(
                "このイベントにはまだ参加希望していません。",
                ephemeral=True,
            )
            return

        participants.pop(user_id)
        message = "参加希望をキャンセルしました。"

    save_events_data(data)
    await interaction.message.edit(
        embed=build_event_embed(event_id, event),
        view=EventParticipationView(),
    )
    await interaction.response.send_message(message, ephemeral=True)


class AsariManager(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        guild = discord.Object(id=SERVER_ID)
        self.add_view(AttendanceView())
        self.add_view(EventParticipationView())
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        post_daily_attendance_button.start()
        announce_weekly_attendance_ranking.start()


client = AsariManager()


async def get_attendance_channel():
    channel = client.get_channel(ATTENDANCE_CHANNEL_ID)
    if channel is None:
        try:
            channel = await client.fetch_channel(ATTENDANCE_CHANNEL_ID)
        except discord.DiscordException:
            return None

    if hasattr(channel, "send"):
        return channel

    return None


@tasks.loop(time=time(hour=8, minute=0, tzinfo=JST))
async def post_daily_attendance_button():
    target_date = today_jst().isoformat()
    data = load_attendance_data()
    if target_date in data["daily_posts"]:
        return

    channel = await get_attendance_channel()
    if channel is None:
        print(f"Attendance channel not found: {ATTENDANCE_CHANNEL_ID}")
        return

    message = await channel.send(
        "おはようございます。今日もプロデュース頑張ってくださいね。\n\n"
        f"{build_previous_attendance_summary(today_jst() - timedelta(days=1))}",
        view=AttendanceView(),
    )

    data = load_attendance_data()
    data["daily_posts"][target_date] = message.id
    save_attendance_data(data)


@post_daily_attendance_button.before_loop
async def before_post_daily_attendance_button():
    await client.wait_until_ready()


@tasks.loop(time=time(hour=10, minute=0, tzinfo=JST))
async def announce_daily_attendance_report():
    target = today_jst()
    target_date = target.isoformat()
    data = load_attendance_data()
    if target_date in data["daily_reports"]:
        return

    channel = await get_attendance_channel()
    if channel is None:
        print(f"Attendance channel not found: {ATTENDANCE_CHANNEL_ID}")
        return

    report_date, attendees = build_daily_attendance_report(target)
    if attendees:
        lines = [
            f"- {name}: {attended_time}"
            for name, attended_time in attendees
        ]
        body = "\n".join(lines)
    else:
        body = "今日10時時点の登校記録はありません。"

    await channel.send(
        f"{report_date} の登校状況をお知らせします。\n"
        f"{body}"
    )

    data = load_attendance_data()
    data["daily_reports"][target_date] = now_jst().isoformat()
    save_attendance_data(data)


@announce_daily_attendance_report.before_loop
async def before_announce_daily_attendance_report():
    await client.wait_until_ready()


@tasks.loop(time=time(hour=20, minute=0, tzinfo=JST))
async def announce_weekly_attendance_ranking():
    target = today_jst()
    if target.weekday() != 6:
        return

    week_key = iso_week_key(target)
    data = load_attendance_data()
    if week_key in data["weekly_announcements"]:
        return

    channel = await get_attendance_channel()
    if channel is None:
        print(f"Attendance channel not found: {ATTENDANCE_CHANNEL_ID}")
        return

    period, ranking = build_weekly_ranking(target)
    if ranking:
        lines = [
            f"{index}. {name}: {count}日"
            for index, (name, count) in enumerate(ranking, start=1)
        ]
        body = "\n".join(lines)
    else:
        body = "今週の登校記録はありませんでした。"

    await channel.send(
        f"今週の登校ランキングを発表します。\n"
        f"集計期間: {period}\n\n"
        f"{body}"
    )

    data = load_attendance_data()
    data["weekly_announcements"][week_key] = now_jst().isoformat()
    save_attendance_data(data)


@announce_weekly_attendance_ranking.before_loop
async def before_announce_weekly_attendance_ranking():
    await client.wait_until_ready()


def has_developer_role(interaction: discord.Interaction) -> bool:
    user = interaction.user

    if not isinstance(user, discord.Member):
        return False

    return any(role.id == DEVELOPER_ROLE_ID for role in user.roles)


def run_command(command: list[str], cwd: str | None = None) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=180,
            check=False,
        )

        output = result.stdout.strip()

        if result.returncode == 0:
            return True, output

        return False, output

    except subprocess.TimeoutExpired:
        return False, "コマンドがタイムアウトしました。"


def trim_output(output: str, limit: int = 1500) -> str:
    if len(output) <= limit:
        return output
    return output[-limit:]


def trim_output_head(output: str, limit: int = 1500) -> str:
    if len(output) <= limit:
        return output
    return output[:limit] + "\n..."


def code_block(output: str, limit: int = 1500) -> str:
    safe_output = trim_output(output or "出力はありません。", limit).replace("```", "'''")
    return f"```text\n{safe_output}\n```"


def parse_systemctl_show(output: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def get_bot_service_status(service: str, include_logs: bool = False) -> dict[str, object]:
    show_ok, show_output = run_command(
        [
            "sudo",
            "-n",
            SYSTEMCTL,
            "show",
            service,
            "-p",
            "ActiveState",
            "-p",
            "SubState",
            "-p",
            "Result",
            "-p",
            "ExecMainStatus",
            "-p",
            "NRestarts",
            "--no-pager",
        ],
    )
    values = parse_systemctl_show(show_output)
    active_state = values.get("ActiveState", "unknown")
    sub_state = values.get("SubState", "unknown")
    result = values.get("Result", "unknown")
    exec_main_status = values.get("ExecMainStatus", "unknown")
    restart_count = values.get("NRestarts", "unknown")
    is_running = show_ok and active_state == "active" and sub_state == "running" and result in ("success", "")

    status_ok, status_output = run_command(
        ["sudo", "-n", SYSTEMCTL, "status", service, "--no-pager"],
    )

    logs_output = ""
    if include_logs:
        _, logs_output = run_command(
            ["sudo", "-n", JOURNALCTL, "-u", service, "-n", "40", "--no-pager"],
        )

    return {
        "is_running": is_running,
        "active_state": active_state,
        "sub_state": sub_state,
        "result": result,
        "exec_main_status": exec_main_status,
        "restart_count": restart_count,
        "show_ok": show_ok,
        "show_output": show_output,
        "status_ok": status_ok,
        "status_output": status_output,
        "logs_output": logs_output,
    }


def format_status_line(bot_name: str, status: dict[str, object]) -> str:
    marker = "OK" if status["is_running"] else "NG"
    return (
        f"{marker} `{bot_name}`: "
        f"{status['active_state']} / {status['sub_state']} "
        f"(result={status['result']}, code={status['exec_main_status']}, restarts={status['restart_count']})"
    )


def format_status_detail(bot_name: str, status: dict[str, object]) -> str:
    status_output = trim_output_head(str(status["status_output"]), 700)
    logs_output = trim_output(str(status.get("logs_output") or ""), 700)
    lines = [
        format_status_line(bot_name, status),
        "",
        "状態:",
        status_output,
    ]
    if logs_output:
        lines.extend(["", "直近ログ:", logs_output])
    return "\n".join(lines)


@client.event
async def on_ready():
    print(f"Logged in as {client.user}")

    channel = client.get_channel(STARTUP_CHANNEL_ID)
    if channel is not None:
        await channel.send("起動しました")


async def bot_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    bots = load_bots()
    bot_names = sorted(bots.keys())

    matched = [
        name for name in bot_names
        if current.lower() in name.lower()
    ]

    return [
        app_commands.Choice(name=name, value=name)
        for name in matched[:25]
    ]


@client.tree.command(name="deploy", description="指定したBotを更新して再起動します")
@app_commands.describe(bot="デプロイするBotを選択してください")
@app_commands.autocomplete(bot=bot_autocomplete)
async def deploy(
    interaction: discord.Interaction,
    bot: str,
):
    await interaction.response.defer(thinking=True)

    if not has_developer_role(interaction):
        await interaction.followup.send(
            "このコマンドは developer ロールを持っている人だけ実行できます。",
            ephemeral=True,
        )
        return

    bots = load_bots()

    if bot not in bots:
        await interaction.followup.send(
            f"`{bot}` は登録されていないBotです。",
            ephemeral=True,
        )
        return

    bot_name = bot
    target = bots[bot_name]

    if "path" not in target or "service" not in target:
        await interaction.followup.send(
            f"`{bot_name}` の設定が不正です。`path` と `service` を確認してください。",
            ephemeral=True,
        )
        return

    await interaction.followup.send(f"{bot_name} さんのレッスンを行います。")

    ok, output = run_command(
        ["git", "fetch", "origin"],
        cwd=target["path"],
    )
    if not ok:
        await interaction.followup.send(
            f"{bot_name} さんのレッスン中に `git fetch` で失敗しました。\n{code_block(output)}"
        )
        return

    ok, output = run_command(
        ["git", "reset", "--hard", "origin/main"],
        cwd=target["path"],
    )
    if not ok:
        await interaction.followup.send(
            f"{bot_name} さんのレッスン中に `git reset` で失敗しました。\n{code_block(output)}"
        )
        return

    ok, output = run_command(
        [f"{target['path']}/.venv/bin/pip", "install", "-r", "requirements.txt"],
        cwd=target["path"],
    )
    if not ok:
        await interaction.followup.send(
            f"{bot_name} さんのライブラリ更新に失敗しました。\n{code_block(output)}"
        )
        return

    ok, output = run_command(
        ["sudo", "-n", SYSTEMCTL, "restart", target["service"]],
    )
    if not ok:
        await interaction.followup.send(
            f"{bot_name} さんの再起動に失敗しました。\n{code_block(output)}"
        )
        return

    await asyncio.sleep(8)
    status = get_bot_service_status(target["service"], include_logs=True)

    if status["is_running"]:
        await interaction.followup.send(
            f"{bot_name} さんのレッスンが終わりました。\n状態：`active / running`"
        )
    else:
        await interaction.followup.send(
            f"{bot_name} さんのレッスンが終わりました。\n"
            "状態：起動に失敗している可能性があります。\n"
            f"{code_block(format_status_detail(bot_name, status), 1800)}"
        )


@client.tree.command(name="reboot", description="asari_managerを更新して再起動します")
async def reboot(
    interaction: discord.Interaction,
):
    await interaction.response.defer(thinking=True)

    if not has_developer_role(interaction):
        await interaction.followup.send(
            "このコマンドは developer ロールを持っている人だけ実行できます。",
            ephemeral=True,
        )
        return

    await interaction.followup.send("あさり先生の再起動準備を行います。")

    base_dir = str(BASE_DIR)
    ok, output = run_command(
        ["git", "fetch", "origin"],
        cwd=base_dir,
    )
    if not ok:
        await interaction.followup.send(
            f"あさり先生の `git fetch` に失敗しました。\n{code_block(output)}"
        )
        return

    ok, output = run_command(
        ["git", "reset", "--hard", "origin/main"],
        cwd=base_dir,
    )
    if not ok:
        await interaction.followup.send(
            f"あさり先生の `git reset` に失敗しました。\n{code_block(output)}"
        )
        return

    ok, output = run_command(
        [f"{base_dir}/.venv/bin/pip", "install", "-r", "requirements.txt"],
        cwd=base_dir,
    )
    if not ok:
        await interaction.followup.send(
            f"あさり先生のライブラリ更新に失敗しました。\n{code_block(output)}"
        )
        return

    await interaction.followup.send(
        "あさり先生の更新が終わりました。これから再起動します。"
    )

    ok, output = run_command(
        ["sudo", "-n", SYSTEMCTL, "restart", ASARI_MANAGER_SERVICE],
    )
    if not ok:
        await interaction.followup.send(
            f"あさり先生の再起動に失敗しました。\n{code_block(output)}"
        )


@client.tree.command(name="event", description="現地イベントの参加募集を作成します")
@app_commands.describe(
    title="イベント名",
    organizer="企画者",
    location="開催場所",
    budget="予算",
    capacity="定員",
    start_at="開始日時 例: 2026-07-20 20:00",
    end_at="終了予定 例: 2026-07-20 22:00",
    signup_deadline="募集締切 例: 2026-07-18 23:59",
    location_url="場所のリンク",
    note="備考",
)
async def event(
    interaction: discord.Interaction,
    title: str,
    organizer: str,
    location: str,
    budget: str,
    capacity: int,
    start_at: str,
    end_at: str,
    signup_deadline: str,
    location_url: str | None = None,
    note: str | None = None,
):
    await interaction.response.defer(thinking=True)

    if not has_developer_role(interaction):
        await interaction.followup.send(
            "このコマンドは developer ロールを持っている人だけ実行できます。",
            ephemeral=True,
        )
        return

    if capacity <= 0:
        await interaction.followup.send(
            "定員は1人以上で指定してください。",
            ephemeral=True,
        )
        return

    parsed_start_at = parse_event_datetime(start_at)
    parsed_end_at = parse_event_datetime(end_at)
    parsed_signup_deadline = parse_event_datetime(signup_deadline)
    if parsed_start_at is None or parsed_end_at is None or parsed_signup_deadline is None:
        await interaction.followup.send(
            "日時は `2026-07-20 20:00` または `2026/07/20 20:00` の形式で入力してください。",
            ephemeral=True,
        )
        return

    if parsed_end_at <= parsed_start_at:
        await interaction.followup.send(
            "終了予定は開始日時より後にしてください。",
            ephemeral=True,
        )
        return

    if parsed_signup_deadline > parsed_start_at:
        await interaction.followup.send(
            "募集締切は開始日時以前にしてください。",
            ephemeral=True,
        )
        return

    data = load_events_data()
    event_id = str(data["next_id"])
    data["next_id"] = int(data["next_id"]) + 1
    event_data = {
        "title": title,
        "organizer": organizer,
        "location": location,
        "location_url": location_url or "",
        "budget": budget,
        "capacity": capacity,
        "start_at": parsed_start_at.isoformat(),
        "end_at": parsed_end_at.isoformat(),
        "signup_deadline": parsed_signup_deadline.isoformat(),
        "note": note or "",
        "creator_id": str(interaction.user.id),
        "created_at": now_jst().isoformat(),
        "message_id": None,
        "participants": {},
    }
    data["events"][event_id] = event_data
    save_events_data(data)

    message = await interaction.followup.send(
        "現地イベントのお知らせです。",
        embed=build_event_embed(event_id, event_data),
        view=EventParticipationView(),
        wait=True,
    )

    data = load_events_data()
    data["events"][event_id]["message_id"] = message.id
    save_events_data(data)


@client.tree.command(name="checkbot", description="Botのsystemdステータスを確認します")
@app_commands.describe(bot="確認するBotを選択してください。未指定の場合は全Botを確認します")
@app_commands.autocomplete(bot=bot_autocomplete)
async def checkbot(
    interaction: discord.Interaction,
    bot: str | None = None,
):
    await interaction.response.defer(thinking=True)

    if not has_developer_role(interaction):
        await interaction.followup.send(
            "このコマンドは developer ロールを持っている人だけ実行できます。",
            ephemeral=True,
        )
        return

    bots = load_bots()
    if bot is not None and bot not in bots:
        await interaction.followup.send(
            f"`{bot}` は登録されていないBotです。",
            ephemeral=True,
        )
        return

    if bot is None:
        lines = []
        for bot_name, target in sorted(bots.items()):
            if "service" not in target:
                lines.append(f"NG `{bot_name}`: service が設定されていません")
                continue
            status = get_bot_service_status(target["service"])
            lines.append(format_status_line(bot_name, status))

        await interaction.followup.send("Botの状態です。\n" + "\n".join(lines))
        return

    target = bots[bot]
    if "service" not in target:
        await interaction.followup.send(
            f"`{bot}` の設定が不正です。`service` を確認してください。",
            ephemeral=True,
        )
        return

    status = get_bot_service_status(target["service"], include_logs=True)
    await interaction.followup.send(
        f"{bot} さんの状態です。\n{code_block(format_status_detail(bot, status), 1800)}"
    )


@client.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
):
    print(f"App command error: {error}")

    if interaction.response.is_done():
        await interaction.followup.send(
            f"コマンド実行中にエラーが発生しました。\n```text\n{str(error)[-1500:]}\n```",
            ephemeral=True,
        )
    else:
        await interaction.response.send_message(
            f"コマンド実行中にエラーが発生しました。\n```text\n{str(error)[-1500:]}\n```",
            ephemeral=True,
        )

client.run(TOKEN)
