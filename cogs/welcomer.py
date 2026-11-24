import discord
from discord.ext import commands

import config
from emojis import em
from utils.v2 import Panel, sep, footer, confirm, send_ok, send_err, send_panel

VARS = {
    "{user}": "Member mention", "{user.name}": "Display name", "{user.id}": "User ID", "{user.tag}": "Username",
    "{user.avatar}": "Avatar URL", "{server}": "Server name", "{server.id}": "Server ID",
    "{server.membercount}": "Member count", "{server.icon}": "Server icon URL", "{timestamp}": "Join time (Discord format)",
}
DEFAULT = {"enabled": False, "channel": None, "type": "simple", "message": "Welcome {user} to **{server}**! You are member **#{server.membercount}** 💖",
           "content": "", "title": "Welcome to {server}", "description": "Hey {user}, enjoy your stay!", "color": "#ff69b4",
           "thumbnail": "{user.avatar}", "image": "", "delete_after": 0, "autorole": None}


def render(text: str, m: discord.Member) -> str:
    if not text:
        return ""
    rep = {
        "{user}": m.mention, "{user.name}": m.display_name, "{user.id}": str(m.id), "{user.tag}": str(m),
        "{user.avatar}": m.display_avatar.url, "{server}": m.guild.name, "{server.id}": str(m.guild.id),
        "{server.membercount}": str(m.guild.member_count), "{server.icon}": m.guild.icon.url if m.guild.icon else "",
        "{timestamp}": discord.utils.format_dt(discord.utils.utcnow(), "R"),
    }
    for k, v in rep.items():
        text = text.replace(k, v)
    return text


class Welcomer(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        if not ctx.guild:
            raise commands.NoPrivateMessage()
        return True

    async def cfg(self, gid):
        return {**DEFAULT, **await self.bot.db.kget(gid, "greet", {})}

    async def save(self, gid, c):
        await self.bot.db.kset(gid, "greet", c)

    async def _set(self, ctx, **kw):
        c = await self.cfg(ctx.guild.id)
        c.update(kw)
        await self.save(ctx.guild.id, c)

    def build(self, m, c):
        content, embed = None, None
        if c["type"] in ("simple", "both"):
            content = render(c["message"], m) or None
        if c["type"] in ("embed", "both"):
            try:
                col = discord.Colour(int(c["color"].lstrip("#"), 16))
            except ValueError:
                col = discord.Colour.blurple()
            embed = discord.Embed(title=render(c["title"], m)[:256] or None, description=render(c["description"], m)[:4000] or None, colour=col)
            if th := render(c["thumbnail"], m):
                embed.set_thumbnail(url=th)
            if im := render(c["image"], m):
                embed.set_image(url=im)
            if c["content"]:
                content = render(c["content"], m)
        return content, embed

    async def greet_member(self, m, channel=None):
        c = await self.cfg(m.guild.id)
        ch = channel or (m.guild.get_channel(c["channel"]) if c["channel"] else None)
        if not ch:
            return None
        content, embed = self.build(m, c)
        try:
            return await ch.send(content=content, embed=embed, delete_after=c["delete_after"] or None,
                                 allowed_mentions=discord.AllowedMentions(users=True))
        except discord.HTTPException:
            return None

    @commands.Cog.listener()
    async def on_member_join(self, m: discord.Member):
        c = await self.cfg(m.guild.id)
        if c["autorole"] and not m.bot and (role := m.guild.get_role(c["autorole"])):
            try:
                await m.add_roles(role, reason="Greet autorole")
            except discord.HTTPException:
                pass
        if c["enabled"]:
            await self.greet_member(m)

    # ---------- commands ----------
    @commands.group(name="greet", aliases=["welcome", "welcomer", "wlc"], invoke_without_command=True, help="Welcome message settings")
    @commands.has_permissions(manage_guild=True)
    async def greet(self, ctx):
        await self.g_config(ctx)

    @greet.command(name="setup", help="Quick setup in this (or given) channel")
    @commands.has_permissions(manage_guild=True)
    async def g_setup(self, ctx, channel: discord.TextChannel = None):
        ch = channel or ctx.channel
        await self._set(ctx, channel=ch.id, enabled=True)
        await send_ok(ctx, f"Greet setup done → {ch.mention}. Use `{ctx.clean_prefix}greet test` to preview.")

    @greet.command(name="channel", help="Set the welcome channel")
    @commands.has_permissions(manage_guild=True)
    async def g_channel(self, ctx, channel: discord.TextChannel):
        await self._set(ctx, channel=channel.id, enabled=True)
        await send_ok(ctx, f"Welcome channel: {channel.mention}")

    @greet.command(name="type", help="Mode: simple / embed / both")
    @commands.has_permissions(manage_guild=True)
    async def g_type(self, ctx, mode: str):
        if mode.lower() not in ("simple", "embed", "both"):
            return await send_err(ctx, "Modes: `simple`, `embed`, `both`")
        await self._set(ctx, type=mode.lower())
        await send_ok(ctx, f"Type: `{mode.lower()}`")

    def _text_cmd(group, name, key, aliases, help_):
        @group.command(name=name, aliases=aliases, help=help_)
        @commands.has_permissions(manage_guild=True)
        async def cmd(self, ctx, *, value: str):
            v = "" if value.lower() in ("none", "off", "clear") else value
            await self._set(ctx, **{key: v})
            await send_ok(ctx, f"`{name}` updated.")
        cmd.__name__ = f"g_{name}"
        return cmd

    for _n, _k, _a, _h in (("message", "message", ["msg"], "Plain welcome message (simple/both)"),
                           ("content", "content", [], "Text above the embed"),
                           ("title", "title", [], "Embed title"),
                           ("description", "description", ["desc"], "Embed description"),
                           ("thumbnail", "thumbnail", ["thumb"], "Embed thumbnail URL or {user.avatar}"),
                           ("image", "image", ["img"], "Embed image URL")):
        _text_cmd(greet, _n, _k, _a, _h)

    @greet.command(name="color", aliases=["colour"], help="Embed colour (hex)")
    @commands.has_permissions(manage_guild=True)
    async def g_color(self, ctx, colour: discord.Colour):
        await self._set(ctx, color=f"#{colour.value:06x}")
        await send_ok(ctx, f"Colour: `#{colour.value:06x}`")

    @greet.command(name="deleteafter", aliases=["da"], help="Auto-delete greeting after N seconds (0 = off)")
    @commands.has_permissions(manage_guild=True)
    async def g_da(self, ctx, seconds: commands.Range[int, 0, 600]):
        await self._set(ctx, delete_after=seconds)
        await send_ok(ctx, f"Delete after: **{seconds or 'off'}**")

    @greet.command(name="autorole", help="Role to give every new member (no arg = off)")
    @commands.has_permissions(manage_guild=True)
    async def g_autorole(self, ctx, role: discord.Role = None):
        if role and role >= ctx.guild.me.top_role:
            return await send_err(ctx, "That role is higher than my top role.")
        await self._set(ctx, autorole=role.id if role else None)
        await send_ok(ctx, f"Autorole: {role.mention if role else 'off'}")

    @greet.command(name="test", help="Preview the greeting")
    @commands.has_permissions(manage_guild=True)
    async def g_test(self, ctx):
        c = await self.cfg(ctx.guild.id)
        if not await self.greet_member(ctx.author, ctx.channel):
            await send_err(ctx, "Couldn't build the preview.")

    @greet.command(name="config", aliases=["settings", "show"], help="Show greet configuration")
    @commands.has_permissions(manage_guild=True)
    async def g_config(self, ctx):
        c = await self.cfg(ctx.guild.id)
        chan = f"<#{c['channel']}>" if c["channel"] else "Not set"
        auto = f"<@&{c['autorole']}>" if c["autorole"] else "Off"
        await send_panel(
            ctx, f"## {em('welcomer')} Greet", f"**Status:** {em('on') if c['enabled'] else em('off')} • **Channel:** {chan} • **Type:** `{c['type']}`",
            sep(),
            f"**Message:** {c['message'][:150] or '—'}\n**Content:** {c['content'][:80] or '—'}\n**Title:** {c['title'][:80] or '—'}\n"
            f"**Description:** {c['description'][:120] or '—'}\n**Colour:** `{c['color']}` • **Delete after:** `{c['delete_after'] or 'off'}`\n"
            f"**Thumbnail:** `{c['thumbnail'] or '—'}` • **Image:** `{c['image'] or '—'}`\n**Autorole:** {auto}",
            sep(), f"-# `{ctx.clean_prefix}greet variables` for placeholders", footer(), color=config.HELP_COLOR)

    @greet.command(name="variables", aliases=["vars"], help="Show available variables")
    async def g_vars(self, ctx):
        await send_panel(ctx, "## Greet Variables", "\n".join(f"`{k}` — {v}" for k, v in VARS.items()))

    @greet.command(name="disable", aliases=["off"], help="Turn greeting off")
    @commands.has_permissions(manage_guild=True)
    async def g_disable(self, ctx):
        await self._set(ctx, enabled=False)
        await send_ok(ctx, "Greeting **disabled**.")

    @greet.command(name="reset", help="Reset all greet settings")
    @commands.has_permissions(manage_guild=True)
    async def g_reset(self, ctx):
        if await confirm(ctx, "Reset **all greet settings**?"):
            await self.bot.db.kdel(ctx.guild.id, "greet")
            await send_ok(ctx, "Greet has been reset.")


async def setup(bot):
    await bot.add_cog(Welcomer(bot))
