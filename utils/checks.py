import re

import discord
from discord.ext import commands

_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_duration(text: str) -> int | None:
    parts = re.findall(r"(\d+)\s*([smhdw])", text.lower())
    if not parts:
        return None
    return sum(int(n) * _UNITS[u] for n, u in parts)


def fmt_duration(seconds: int) -> str:
    out = []
    for name, size in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        if seconds >= size:
            out.append(f"{seconds // size}{name}")
            seconds %= size
    return " ".join(out) or "0s"


def can_act(ctx, target: discord.Member) -> str | None:
    """None = allowed, warna error text."""
    g = ctx.guild
    if target.id == ctx.author.id:
        return "You can't use this action on yourself."
    if target.id == g.owner_id:
        return "This action can't be used on the server owner."
    if target.id == ctx.bot.user.id:
        return "This action can't be used on me."
    if target.top_role >= g.me.top_role:
        return "That member's top role is equal to or higher than mine."
    if ctx.author.id != g.owner_id and target.top_role >= ctx.author.top_role:
        return "That member's top role is equal to or higher than yours."
    return None


def _missing(perms: dict, have: discord.Permissions) -> list[str]:
    if have.administrator:
        return []
    return [k for k, v in perms.items() if v and not getattr(have, k)]


def guild_perms(**perms):
    """User permission check at GUILD level.
    (commands.has_permissions checks the text channel, which never includes voice permissions
    like Move/Mute/Deafen Members, so it always fails for those.)"""
    async def pred(ctx):
        if not ctx.guild:
            raise commands.NoPrivateMessage()
        missing = _missing(perms, ctx.author.guild_permissions)
        if missing:
            raise commands.MissingPermissions(missing)
        return True
    return commands.check(pred)


def bot_guild_perms(**perms):
    """Bot permission check at GUILD level (see guild_perms)."""
    async def pred(ctx):
        if not ctx.guild:
            raise commands.NoPrivateMessage()
        missing = _missing(perms, ctx.guild.me.guild_permissions)
        if missing:
            raise commands.BotMissingPermissions(missing)
        return True
    return commands.check(pred)
