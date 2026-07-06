import os
import subprocess
import discord
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
STARTUP_CHANNEL_ID = int(os.getenv("STARTUP_CHANNEL_ID"))
SERVER_ID = int(os.getenv("SERVER_ID"))

DEVELOPER_ROLE_ID = int(os.getenv("DEVELOPER_ROLE_ID"))

BOTS = {
    "saki": {
        "path": "/home/st/discord/saki",
        "service": "saki.service",
    },
    "hiro": {
        "path": "/home/st/discord/hiro",
        "service": "hiro.service",
    },
}


class AsariManager(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        guild = discord.Object(id=SERVER_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)


client = AsariManager()


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


@client.tree.command(name="deploy", description="指定したBotを更新して再起動します")
@app_commands.describe(bot="デプロイするBotを選択してください")
@app_commands.choices(
    bot=[
        app_commands.Choice(name="saki", value="saki"),
        app_commands.Choice(name="hiro", value="hiro"),
    ]
)
async def deploy(
    interaction: discord.Interaction,
    bot: app_commands.Choice[str],
):
    await interaction.response.defer(thinking=True)

    if not has_developer_role(interaction):
        await interaction.followup.send(
            "このコマンドは developer ロールを持っている人だけ実行できます。",
            ephemeral=True,
        )
        return

    bot_name = bot.value
    target = BOTS[bot_name]

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