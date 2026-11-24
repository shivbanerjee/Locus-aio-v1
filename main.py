import asyncio
import copy
import os
import time

import discord
from discord import ui
from discord.ext import commands

import config
from database import Database
from emojis import em, load_app_emojis
from utils.v2 import Panel, sep, td, footer, button


class LocusBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=config.PREFIX,
            intents=discord.Intents.all(),
            help_command=None,
            case_insensitive=True,
            owner_ids=config.OWNER_IDS,
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True),
        )
        self.db = Database()
        self.prefixes: dict[int, str] = {}
        self.noprefix: dict[int, int] = {}   # user_id -> expiry epoch (0 = lifetime)
        self.start_time = time.time()
        self._ready_once = False

    # ---------- prefix ----------
    def prefix_for(self, guild: discord.Guild | None) -> str:
        return self.prefixes.get(guild.id, config.PREFIX) if guild else config.PREFIX

    async def get_prefix(self, message: discord.Message):
        return commands.when_mentioned_or(self.prefix_for(message.guild))(self, message)

    # ---------- startup ----------
    async def setup_hook(self):
        await self.db.connect()
        for r in await self.db.all("SELECT guild_id, prefix FROM guilds WHERE prefix IS NOT NULL"):
            self.prefixes[r["guild_id"]] = r["prefix"]
        for r in await self.db.all("SELECT user_id, expires FROM np_users"):
            self.noprefix[r["user_id"]] = r["expires"] or 0
        for f in sorted(os.listdir("./cogs")):
            if f.endswith(".py") and not f.startswith("_"):
                try:
                    await self.load_extension(f"cogs.{f[:-3]}")
                    print(f"[+] Loaded {f}")
                except Exception as ex:
                    print(f"[!] Failed {f}: {ex!r}")

    async def on_ready(self):
        if not self._ready_once:
            self._ready_once = True
            try:
                n = await load_app_emojis(self)
                print(f"[+] {n} custom emojis loaded")
            except Exception as ex:
                print(f"[!] Emoji load failed: {ex!r}")
        print(f"Logged in as {self.user} ({self.user.id}) | {len(self.guilds)} guilds")
        await self.change_presence(
            activity=discord.Activity(type=discord.ActivityType.listening, name=f"{config.PREFIX}help | {config.BOT_NAME}")
        )

    # ---------- mention panel ----------
    def mention_panel(self, message: discord.Message) -> Panel:
        prefix = self.prefix_for(message.guild)
        row = ui.ActionRow(
            button("Support", url=config.SUPPORT_URL),
            button("Invite", url=config.INVITE_URL),
        )
        return Panel(
            f"### {self.user.display_name}  •  Hey there, I am {config.BOT_NAME}!",
            f"**Thanks for mentioning me, {message.author.mention}!** I'm an advanced multi-purpose "
            f"Discord bot designed for absolute server security and moderation.",
            sep(),
            f"{em('folder')} __**Quick Information**__\n"
            f"{em('prefix')} **Global Prefix:** `{prefix}`\n"
            f"{em('server')} **Server ID:** `{message.guild.id}`\n"
            f"{em('latency')} **Latency:** `{round(self.latency * 1000)}ms`",
            sep(),
            f"{em('folder')} __**Getting Started**__\n"
            f"{em('gear')} Type `{prefix}help` to see a full list of my commands and features.\n"
            f"{em('question')} Need assistance? Click the **Support** button below!",
            row,
            f"-# Requested by {message.author.name} • Developed with ❤️ By {config.DEVELOPER}",
            color=config.INFO_COLOR,
            timeout=None,
        )

    def has_noprefix(self, uid: int) -> bool:
        exp = self.noprefix.get(uid)
        return exp is not None and (exp == 0 or exp > time.time())

    # ---------- message routing ----------
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        if message.content.strip() in (f"<@{self.user.id}>", f"<@!{self.user.id}>"):
            await message.channel.send(view=self.mention_panel(message))
            return

        # ignored channels (admins are excluded)
        ignored = await self.db.kget(message.guild.id, "ignored", [])
        if message.channel.id in ignored and not message.author.guild_permissions.administrator:
            return

        # No-prefix users: "ping" == "&ping"
        if self.has_noprefix(message.author.id) and message.content:
            prefix = self.prefix_for(message.guild)
            first = message.content.split(maxsplit=1)[0]
            if not message.content.startswith(prefix) and self.get_command(first):
                fake = copy.copy(message)
                fake.content = prefix + message.content
                await self.process_commands(fake)
                return

        await self.process_commands(message)

    async def close(self):
        await self.db.close()
        await super().close()


async def main():
    if not config.TOKEN:
        raise SystemExit("TOKEN is missing. Add it to your .env file.")
    bot = LocusBot()
    async with bot:
        await bot.start(config.TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
