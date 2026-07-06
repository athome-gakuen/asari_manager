import os
import json
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
ATTENDANCE_CHANNEL_ID = int(os.getenv("ATTENDANCE_CHANNEL_ID", STARTUP_CHANNEL_ID))
JST = timezone(timedelta(hours=9))
ATTENDANCE_FILE = Path(__file__).with_name("attendance.json")

BASE_DIR = Path(__file__).resolve().parent
BOTS_FILE = BASE_DIR / "bots.yml"


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
            "weekly_announcements": {},
        }

    try:
        with ATTENDANCE_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (json.JSONDecodeError, OSError):
        data = {}

    data.setdefault("attendance", {})
    data.setdefault("daily_posts", {})
    data.setdefault("weekly_announcements", {})
    return data


def save_attendance_data(data: dict) -> None:
    tmp_path = ATTENDANCE_FILE.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    tmp_path.replace(ATTENDANCE_FILE)


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


class AttendanceView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="登校",
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
                "Botは登校記録の対象外です。",
                ephemeral=True,
            )
            return

        target_date = today_jst().isoformat()
        user_id = str(user.id)
        data = load_attendance_data()
        day_data = data["attendance"].setdefault(target_date, {})

        if user_id in day_data:
            await interaction.response.send_message(
                f"{target_date} の登校は記録済みです。",
                ephemeral=True,
            )
            return

        day_data[user_id] = {
            "name": user.display_name,
            "attended_at": now_jst().isoformat(),
        }
        save_attendance_data(data)

        await interaction.response.send_message(
            f"{user.display_name} さんの登校を記録しました。",
            ephemeral=True,
        )


class AsariManager(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        guild = discord.Object(id=SERVER_ID)
        self.add_view(AttendanceView())
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
        f"おはようございます。{target_date} の登校確認です。\n"
        "登校した人は下の「登校」ボタンを押してください。",
        view=AttendanceView(),
    )

    data = load_attendance_data()
    data["daily_posts"][target_date] = message.id
    save_attendance_data(data)


@post_daily_attendance_button.before_loop
async def before_post_daily_attendance_button():
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

    await interaction.followup.send(f"`{bot_name}` のデプロイを開始します。")

    ok, output = run_command(
        ["git", "fetch", "origin"],
        cwd=target["path"],
    )
    if not ok:
        await interaction.followup.send(
            f"`{bot_name}` の `git fetch` に失敗しました。\n```text\n{output[-1500:]}\n```"
        )
        return

    ok, output = run_command(
        ["git", "reset", "--hard", "origin/main"],
        cwd=target["path"],
    )
    if not ok:
        await interaction.followup.send(
            f"`{bot_name}` の `git reset` に失敗しました。\n```text\n{output[-1500:]}\n```"
        )
        return

    ok, output = run_command(
        [f"{target['path']}/.venv/bin/pip", "install", "-r", "requirements.txt"],
        cwd=target["path"],
    )
    if not ok:
        await interaction.followup.send(
            f"`{bot_name}` のライブラリ更新に失敗しました。\n```text\n{output[-1500:]}\n```"
        )
        return

    ok, output = run_command(
        ["sudo", "systemctl", "restart", target["service"]],
    )
    if not ok:
        await interaction.followup.send(
            f"`{bot_name}` の再起動に失敗しました。\n```text\n{output[-1500:]}\n```"
        )
        return

    ok, output = run_command(
        ["sudo", "systemctl", "is-active", target["service"]],
    )

    if ok and output.strip() == "active":
        await interaction.followup.send(
            f"`{bot_name}` のデプロイが完了しました。状態: `active`"
        )
    else:
        await interaction.followup.send(
            f"`{bot_name}` は再起動しましたが、状態確認に失敗しました。\n```text\n{output[-1500:]}\n```"
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
