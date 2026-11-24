import discord
from discord.ext import commands

import config
from emojis import em
from utils.v2 import Panel, NO_MENTIONS, confirm, send_ok, send_err, send_panel, send_list

LOG_TYPES = [
    "message_delete", "message_edit", "bulk_delete", "member_join", "member_leave", "member_update",
    "member_ban", "member_unban", "role_create", "role_delete", "role_update",
    "channel_create", "channel_delete", "channel_update", "voice", "invite",
]


class Logger(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cfg(self, gid: int) -> dict:
        d = await self.bot.db.kget(gid, "log", {})
        d.setdefault("default", None)
        d.setdefault("types", {})
        return d

    async def save(self, gid, d):
        await self.bot.db.kset(gid, "log", d)

    async def send(self, guild, log_type, title, text, color=config.INFO_COLOR):
        cfg = await self.cfg(guild.id)
        t = cfg["types"].get(log_type, {})
        if t.get("enabled") is False:
            return
        cid = t.get("channel") or cfg["default"]
        ch = guild.get_channel(cid) if cid else None
        if not ch:
            return
        ts = discord.utils.format_dt(discord.utils.utcnow(), "f")
        try:
            await ch.send(view=Panel(f"### {title}", text, f"-# {ts}", color=color, timeout=None), allowed_mentions=NO_MENTIONS)
        except discord.HTTPException:
            pass

    # ---------- events ----------
    @commands.Cog.listener()
    async def on_message_delete(self, m):
        if m.guild and not m.author.bot:
            files = "\n".join(a.url for a in m.attachments)
            await self.send(m.guild, "message_delete", "🗑️ Message Deleted",
                            f"**Author:** {m.author.mention}\n**Channel:** {m.channel.mention}\n{(m.content or '*no text*')[:1500]}\n{files}", config.RED)

    @commands.Cog.listener()
    async def on_message_edit(self, b, a):
        if b.guild and not b.author.bot and b.content != a.content:
            await self.send(b.guild, "message_edit", "✏️ Message Edited",
                            f"**Author:** {b.author.mention} • [Jump]({a.jump_url})\n**Before:** {b.content[:700]}\n**After:** {a.content[:700]}", config.YELLOW)

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages):
        if messages and messages[0].guild:
            await self.send(messages[0].guild, "bulk_delete", "🧹 Bulk Delete",
                            f"**{len(messages)}** messages deleted in {messages[0].channel.mention}", config.RED)

    @commands.Cog.listener()
    async def on_member_join(self, m):
        await self.send(m.guild, "member_join", "📥 Member Joined",
                        f"{m.mention} (`{m.id}`)\nAccount created: {discord.utils.format_dt(m.created_at, 'R')}", config.GREEN)

    @commands.Cog.listener()
    async def on_member_remove(self, m):
        await self.send(m.guild, "member_leave", "📤 Member Left", f"{m.mention} (`{m.id}`)", config.RED)

    @commands.Cog.listener()
    async def on_member_update(self, b, a):
        parts = []
        if b.nick != a.nick:
            parts.append(f"**Nick:** `{b.nick}` → `{a.nick}`")
        added, removed = set(a.roles) - set(b.roles), set(b.roles) - set(a.roles)
        if added:
            parts.append("**Roles +** " + ", ".join(r.mention for r in added))
        if removed:
            parts.append("**Roles −** " + ", ".join(r.mention for r in removed))
        if b.timed_out_until != a.timed_out_until:
            parts.append(f"**Timeout:** {discord.utils.format_dt(a.timed_out_until, 'R') if a.timed_out_until else 'removed'}")
        if parts:
            await self.send(a.guild, "member_update", f"👤 Member Updated • {a}", f"{a.mention}\n" + "\n".join(parts), config.BLURPLE)

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        await self.send(guild, "member_ban", "🔨 Member Banned", f"{user.mention} (`{user.id}`)", config.RED)

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        await self.send(guild, "member_unban", "♻️ Member Unbanned", f"{user.mention} (`{user.id}`)", config.GREEN)

    @commands.Cog.listener()
    async def on_guild_role_create(self, r):
        await self.send(r.guild, "role_create", "🏷️ Role Created", f"{r.mention} (`{r.name}`)", config.GREEN)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, r):
        await self.send(r.guild, "role_delete", "🏷️ Role Deleted", f"`{r.name}` (`{r.id}`)", config.RED)

    @commands.Cog.listener()
    async def on_guild_role_update(self, b, a):
        parts = []
        if b.name != a.name:
            parts.append(f"**Name:** `{b.name}` → `{a.name}`")
        if b.colour != a.colour:
            parts.append(f"**Colour:** `{b.colour}` → `{a.colour}`")
        if b.permissions != a.permissions:
            parts.append("**Permissions changed**")
        if parts:
            await self.send(a.guild, "role_update", f"🏷️ Role Updated • {a.name}", "\n".join(parts), config.YELLOW)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, ch):
        await self.send(ch.guild, "channel_create", "📁 Channel Created", f"{ch.mention} (`{ch.name}`)", config.GREEN)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, ch):
        await self.send(ch.guild, "channel_delete", "📁 Channel Deleted", f"`#{ch.name}` (`{ch.id}`)", config.RED)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, b, a):
        parts = []
        if b.name != a.name:
            parts.append(f"**Name:** `{b.name}` → `{a.name}`")
        if getattr(b, "topic", None) != getattr(a, "topic", None):
            parts.append("**Topic changed**")
        if b.overwrites != a.overwrites:
            parts.append("**Permissions changed**")
        if parts:
            await self.send(a.guild, "channel_update", f"📁 Channel Updated • #{a.name}", f"{a.mention}\n" + "\n".join(parts), config.YELLOW)

    @commands.Cog.listener()
    async def on_voice_state_update(self, m, b, a):
        if b.channel == a.channel:
            return
        if not b.channel:
            text = f"{m.mention} joined {a.channel.mention}"
        elif not a.channel:
            text = f"{m.mention} left {b.channel.mention}"
        else:
            text = f"{m.mention} moved {b.channel.mention} → {a.channel.mention}"
        await self.send(m.guild, "voice", "🔊 Voice Activity", text, config.BLURPLE)

    @commands.Cog.listener()
    async def on_invite_create(self, inv):
        if inv.guild:
            await self.send(inv.guild, "invite", "✉️ Invite Created", f"`{inv.code}` by {inv.inviter.mention if inv.inviter else '?'} → {inv.channel.mention}", config.GREEN)

    @commands.Cog.listener()
    async def on_invite_delete(self, inv):
        if inv.guild:
            await self.send(inv.guild, "invite", "✉️ Invite Deleted", f"`{inv.code}`", config.RED)

    # ---------- commands ----------
    @commands.group(name="logging", aliases=["log", "logger"], invoke_without_command=True, help="Logging status")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def logging(self, ctx):
        await self.lg_config(ctx)

    @logging.command(name="setup", help="Set default log channel (creates one if not given)")
    @commands.has_permissions(manage_guild=True)
    async def lg_setup(self, ctx, channel: discord.TextChannel = None):
        if channel is None:
            channel = await ctx.guild.create_text_channel("locus-logs", overwrites={
                ctx.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                ctx.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)})
        c = await self.cfg(ctx.guild.id)
        c["default"] = channel.id
        await self.save(ctx.guild.id, c)
        await send_ok(ctx, f"Default log channel: {channel.mention}")

    @logging.command(name="set", help="Set channel for one log type")
    @commands.has_permissions(manage_guild=True)
    async def lg_set(self, ctx, log_type: str, channel: discord.TextChannel):
        log_type = log_type.lower()
        if log_type not in LOG_TYPES:
            return await send_err(ctx, f"Types: `{', '.join(LOG_TYPES)}`")
        c = await self.cfg(ctx.guild.id)
        c["types"].setdefault(log_type, {})["channel"] = channel.id
        c["types"][log_type]["enabled"] = True
        await self.save(ctx.guild.id, c)
        await send_ok(ctx, f"`{log_type}` → {channel.mention}")

    async def _toggle(self, ctx, log_type, state):
        log_type = log_type.lower()
        names = LOG_TYPES if log_type == "all" else [log_type]
        if any(n not in LOG_TYPES for n in names):
            return await send_err(ctx, f"Types: `{', '.join(LOG_TYPES)}`, `all`")
        c = await self.cfg(ctx.guild.id)
        for n in names:
            c["types"].setdefault(n, {})["enabled"] = state
        await self.save(ctx.guild.id, c)
        await send_ok(ctx, f"`{log_type}` **{'enabled' if state else 'disabled'}**.")

    @logging.command(name="enable", help="Enable a log type (or all)")
    @commands.has_permissions(manage_guild=True)
    async def lg_enable(self, ctx, log_type: str):
        await self._toggle(ctx, log_type, True)

    @logging.command(name="disable", help="Disable a log type (or all)")
    @commands.has_permissions(manage_guild=True)
    async def lg_disable(self, ctx, log_type: str):
        await self._toggle(ctx, log_type, False)

    @logging.command(name="types", help="List all log types")
    async def lg_types(self, ctx):
        await send_list(ctx, f"{em('logger')} Log Types", [f"`{t}`" for t in LOG_TYPES], color=config.HELP_COLOR)

    @logging.command(name="config", aliases=["show"], help="Show logging configuration")
    @commands.has_permissions(manage_guild=True)
    async def lg_config(self, ctx):
        c = await self.cfg(ctx.guild.id)
        items = []
        for t in LOG_TYPES:
            d = c["types"].get(t, {})
            ch = d.get("channel") or c["default"]
            on = d.get("enabled", True) and ch
            items.append(f"{em('on') if on else em('off')} `{t}` → {f'<#{ch}>' if ch else '—'}")
        dflt = f"<#{c['default']}>" if c["default"] else "Not set"
        head = f"**Default channel:** {dflt}"
        await send_list(ctx, f"{em('logger')} Logging", items, header=head, per_page=16, color=config.HELP_COLOR, numbered=False)

    @logging.command(name="reset", help="Reset all logging settings")
    @commands.has_permissions(manage_guild=True)
    async def lg_reset(self, ctx):
        if await confirm(ctx, "Reset **all logging settings**?"):
            await self.bot.db.kdel(ctx.guild.id, "log")
            await send_ok(ctx, "Logging has been reset.")


async def setup(bot):
    await bot.add_cog(Logger(bot))
