import platform
import sys
import time

import discord
from discord import ui
from discord.ext import commands

import config
from emojis import em
from utils.checks import fmt_duration
from utils.v2 import Panel, sep, td, footer, media, button, send_ok, send_err, send_panel, send_list

try:
    import psutil
except ImportError:  # optional
    psutil = None

YES = "✅"
NO = "❌"


def _members(g, pred):
    return [f"{m.mention} (`{m.id}`)" for m in g.members if pred(m)]


class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        if not ctx.guild:
            raise commands.NoPrivateMessage()
        return True

    # ---------- afk ----------
    @commands.Cog.listener()
    async def on_message(self, m):
        if m.author.bot or not m.guild:
            return
        db = self.bot.db
        if await db.one("SELECT 1 FROM afk WHERE guild_id=? AND user_id=?", m.guild.id, m.author.id):
            await db.run("DELETE FROM afk WHERE guild_id=? AND user_id=?", m.guild.id, m.author.id)
            await m.channel.send(view=Panel(f"👋 Welcome back {m.author.mention}, your AFK was removed.", color=config.GREEN, timeout=None), delete_after=6)
        for u in m.mentions[:5]:
            row = await db.one("SELECT reason, ts FROM afk WHERE guild_id=? AND user_id=?", m.guild.id, u.id)
            if row:
                await m.channel.send(view=Panel(f"💤 **{u.display_name}** is AFK: {row['reason']} (<t:{row['ts']}:R>)",
                                                color=config.YELLOW, timeout=None), delete_after=8)

    @commands.command(aliases=["away"], help="Set yourself AFK")
    async def afk(self, ctx, *, reason: str = "AFK"):
        await self.bot.db.run("INSERT OR REPLACE INTO afk VALUES(?,?,?,?)", ctx.guild.id, ctx.author.id, reason[:100], int(time.time()))
        await send_ok(ctx, f"AFK set: {reason[:100]}")

    # ---------- general ----------
    @commands.command(aliases=["latency", "ms"], help="Check bot latency")
    async def ping(self, ctx):
        await send_panel(ctx, f"{em('latency')} **Pong!** `{round(self.bot.latency * 1000)}ms`")

    @commands.command(aliases=["mc", "members"], help="Server member count")
    async def membercount(self, ctx):
        g = ctx.guild
        bots = sum(m.bot for m in g.members)
        await send_panel(ctx, f"👥 **{g.member_count}** members • 🙋 `{g.member_count - bots}` humans • 🤖 `{bots}` bots")

    @commands.command(aliases=["boosts", "bc"], help="Server boost count")
    async def boostcount(self, ctx):
        g = ctx.guild
        await send_panel(ctx, f"💎 **{g.premium_subscription_count}** boosts • Level **{g.premium_tier}** • `{len(g.premium_subscribers)}` boosters")

    @commands.command(aliases=["joined", "joindate"], help="When a member joined")
    async def joinedat(self, ctx, member: discord.Member = None):
        m = member or ctx.author
        await send_panel(ctx, f"📅 **{m.display_name}** joined {discord.utils.format_dt(m.joined_at, 'F')} ({discord.utils.format_dt(m.joined_at, 'R')})")

    @commands.command(aliases=["av", "pfp"], help="Show a user's avatar")
    async def avatar(self, ctx, member: discord.Member = None):
        m = member or ctx.author
        await send_panel(ctx, f"### {m.display_name}'s Avatar", media(m.display_avatar.url), color=config.BLURPLE)

    @commands.command(aliases=["userbanner", "ub"], help="Show a user's banner")
    async def banner(self, ctx, member: discord.Member = None):
        u = await self.bot.fetch_user((member or ctx.author).id)
        if not u.banner:
            return await send_err(ctx, "This user has no banner.")
        await send_panel(ctx, f"### {u.display_name}'s Banner", media(u.banner.url), color=config.BLURPLE)

    @commands.command(aliases=["sicon", "icon", "guildicon"], help="Show the server icon")
    async def servericon(self, ctx):
        if not ctx.guild.icon:
            return await send_err(ctx, "This server has no icon.")
        await send_panel(ctx, f"### {ctx.guild.name} Icon", media(ctx.guild.icon.url), color=config.BLURPLE)

    @commands.command(aliases=["sbanner", "guildbanner"], help="Show the server banner")
    async def serverbanner(self, ctx):
        if not ctx.guild.banner:
            return await send_err(ctx, "This server has no banner.")
        await send_panel(ctx, f"### {ctx.guild.name} Banner", media(ctx.guild.banner.url), color=config.BLURPLE)

    @commands.command(aliases=["inv", "botinvite"], help="Bot invite & support links")
    async def invite(self, ctx):
        await ctx.send(view=Panel(f"## Invite {config.BOT_NAME}", "Add me to your server or join the support server.",
                                  ui.ActionRow(button("Invite Me", url=config.INVITE_URL), button("Support Server", url=config.SUPPORT_URL)),
                                  color=config.BLURPLE, timeout=None))

    @commands.command(aliases=["totalusers", "botusers"], help="Total users across all servers")
    async def users(self, ctx):
        await send_panel(ctx, f"👥 **{sum(g.member_count or 0 for g in self.bot.guilds):,}** users • **{len(self.bot.guilds)}** servers")

    # ---------- info ----------
    @commands.command(aliases=["ui", "whois", "who"], help="User information")
    async def userinfo(self, ctx, member: discord.Member = None):
        m = member or ctx.author
        roles = ", ".join(r.mention for r in m.roles[:0:-1][:12]) or "None"
        head = ui.Section(td(f"## {m.display_name}"),
                          td(f"**ID:** `{m.id}`\n**Created:** {discord.utils.format_dt(m.created_at, 'R')}\n"
                             f"**Joined:** {discord.utils.format_dt(m.joined_at, 'R')}\n**Bot:** {YES if m.bot else NO}"),
                          accessory=ui.Thumbnail(m.display_avatar.url))
        await send_panel(ctx, head, sep(), f"**Top role:** {m.top_role.mention}\n**Roles ({len(m.roles) - 1}):** {roles}",
                         color=m.color.value or config.BLURPLE)

    @commands.command(aliases=["si", "guildinfo", "server"], help="Server information")
    async def serverinfo(self, ctx):
        g = ctx.guild
        items = [td(f"## {g.name}"),
                 td(f"**ID:** `{g.id}`\n**Owner:** {g.owner.mention if g.owner else '?'}\n"
                    f"**Created:** {discord.utils.format_dt(g.created_at, 'R')}\n**Members:** `{g.member_count}`\n"
                    f"**Channels:** `{len(g.text_channels)}` text • `{len(g.voice_channels)}` voice\n"
                    f"**Roles:** `{len(g.roles)}` • **Emojis:** `{len(g.emojis)}`\n"
                    f"**Boosts:** `{g.premium_subscription_count}` (Lv {g.premium_tier})")]
        if g.icon:
            await send_panel(ctx, ui.Section(*items, accessory=ui.Thumbnail(g.icon.url)), color=config.BLURPLE)
        else:
            await send_panel(ctx, *items, color=config.BLURPLE)

    @commands.command(aliases=["ri", "rinfo"], help="Role information")
    async def roleinfo(self, ctx, *, role: discord.Role):
        perms = ", ".join(p.replace("_", " ").title() for p, v in role.permissions if v and p in
                          ("administrator", "manage_guild", "manage_roles", "manage_channels", "ban_members", "kick_members", "moderate_members"))
        await send_panel(ctx, f"## {role.name}",
                         f"**ID:** `{role.id}`\n**Colour:** `{role.colour}`\n**Members:** `{len(role.members)}`\n"
                         f"**Position:** `{role.position}`\n**Hoisted:** {YES if role.hoist else NO} • **Mentionable:** {YES if role.mentionable else NO}\n"
                         f"**Created:** {discord.utils.format_dt(role.created_at, 'R')}\n**Key perms:** {perms or 'None'}",
                         color=role.colour.value or config.BLURPLE)

    @commands.command(aliases=["ci", "cinfo", "chinfo"], help="Channel information")
    async def channelinfo(self, ctx, channel: discord.abc.GuildChannel = None):
        c = channel or ctx.channel
        extra = ""
        if isinstance(c, discord.TextChannel):
            extra = f"\n**Topic:** {c.topic or '—'}\n**Slowmode:** `{c.slowmode_delay}s` • **NSFW:** {YES if c.is_nsfw() else NO}"
        elif isinstance(c, discord.VoiceChannel):
            extra = f"\n**Bitrate:** `{c.bitrate // 1000}kbps` • **Limit:** `{c.user_limit or '∞'}` • **Members:** `{len(c.members)}`"
        await send_panel(ctx, f"## #{c.name}", f"**ID:** `{c.id}`\n**Type:** `{c.type.name}`\n**Category:** {c.category.name if c.category else '—'}\n"
                         f"**Created:** {discord.utils.format_dt(c.created_at, 'R')}{extra}", color=config.BLURPLE)

    # ---------- bot stats ----------
    @commands.command(aliases=["botstats", "botinfo", "bi"], help="Bot statistics")
    async def stats(self, ctx):
        b = self.bot
        head = ui.Section(td(f"## {b.user.display_name}"), td(f"**Team:** {config.TEAM}\n**Developer:** {config.DEVELOPER}"),
                          accessory=ui.Thumbnail(b.user.display_avatar.url))
        mem = f"\n**Memory:** `{psutil.Process().memory_info().rss / 1048576:.0f} MB`" if psutil else ""
        await send_panel(ctx, head, sep(),
                         f"**Servers:** `{len(b.guilds)}` • **Users:** `{sum(g.member_count or 0 for g in b.guilds):,}`\n"
                         f"**Commands:** `{len([c for c in b.walk_commands() if not c.hidden])}`\n**Latency:** `{round(b.latency * 1000)}ms`\n"
                         f"**Uptime:** `{fmt_duration(int(time.time() - b.start_time))}`{mem}\n"
                         f"**Python:** `{sys.version.split()[0]}` • **discord.py:** `{discord.__version__}`", footer(), color=config.BLURPLE)

    @commands.command(aliases=["up"], help="Bot uptime")
    async def uptime(self, ctx):
        await send_panel(ctx, f"⏱️ Uptime: **{fmt_duration(int(time.time() - self.bot.start_time))}**")

    @commands.command(aliases=["sys"], help="System resource usage")
    async def system(self, ctx):
        if not psutil:
            return await send_err(ctx, "Run `pip install psutil` to use this.")
        vm, du = psutil.virtual_memory(), psutil.disk_usage("/")
        await send_panel(ctx, "## 🖥️ System", f"**OS:** `{platform.system()} {platform.release()}`\n**CPU:** `{psutil.cpu_percent(interval=0.3)}%` • `{psutil.cpu_count()}` cores\n"
                         f"**RAM:** `{vm.used / 1073741824:.1f}/{vm.total / 1073741824:.1f} GB` ({vm.percent}%)\n"
                         f"**Disk:** `{du.used / 1073741824:.1f}/{du.total / 1073741824:.1f} GB` ({du.percent}%)", color=config.BLURPLE)

    # ---------- prefix & ignore ----------
    @commands.command(help="Show the server prefix")
    async def prefix(self, ctx):
        await send_panel(ctx, f"{em('prefix')} Prefix: `{self.bot.prefix_for(ctx.guild)}`")

    @commands.command(aliases=["bprefix"], help="Change the server prefix")
    @commands.has_permissions(manage_guild=True)
    async def setprefix(self, ctx, new: str):
        if len(new) > 5:
            return await send_err(ctx, "Prefix max 5 characters.")
        await self.bot.db.run("INSERT INTO guilds(guild_id,prefix) VALUES(?,?) ON CONFLICT(guild_id) DO UPDATE SET prefix=excluded.prefix", ctx.guild.id, new)
        self.bot.prefixes[ctx.guild.id] = new
        await send_ok(ctx, f"Prefix is now `{new}`.")

    @commands.command(help="Reset the prefix to default")
    @commands.has_permissions(manage_guild=True)
    async def resetprefix(self, ctx):
        await self.bot.db.run("UPDATE guilds SET prefix=NULL WHERE guild_id=?", ctx.guild.id)
        self.bot.prefixes.pop(ctx.guild.id, None)
        await send_ok(ctx, f"Prefix reset: `{config.PREFIX}`")

    @commands.command(help="Ignore commands in a channel")
    @commands.has_permissions(manage_guild=True)
    async def ignore(self, ctx, channel: discord.TextChannel = None):
        ch = channel or ctx.channel
        ig = await self.bot.db.kget(ctx.guild.id, "ignored", [])
        if ch.id not in ig:
            ig.append(ch.id)
            await self.bot.db.kset(ctx.guild.id, "ignored", ig)
        await send_ok(ctx, f"{ch.mention} is now ignored (admins excluded).")

    @commands.command(help="Stop ignoring a channel")
    @commands.has_permissions(manage_guild=True)
    async def unignore(self, ctx, channel: discord.TextChannel = None):
        ch = channel or ctx.channel
        ig = [i for i in await self.bot.db.kget(ctx.guild.id, "ignored", []) if i != ch.id]
        await self.bot.db.kset(ctx.guild.id, "ignored", ig)
        await send_ok(ctx, f"{ch.mention} is no longer ignored.")

    @commands.command(aliases=["ignoredchannels", "ignlist"], help="List ignored channels")
    async def ignorelist(self, ctx):
        ig = await self.bot.db.kget(ctx.guild.id, "ignored", [])
        await send_list(ctx, "Ignored Channels", [f"<#{i}>" for i in ig])

    # ---------- list group ----------
    @commands.group(name="list", aliases=["ls"], invoke_without_command=True, help="List roles, users, bans, boosters...")
    async def list_group(self, ctx):
        subs = ", ".join(f"`{c.name}`" for c in self.list_group.commands)
        await send_panel(ctx, f"## {em('list')} List", f"`{ctx.clean_prefix}list <type>`\n{subs}")

    async def _l(self, ctx, title, items, header=None):
        await send_list(ctx, f"{em('list')} {title}", items, header=header)

    @list_group.command(name="roles", help="All roles")
    async def l_roles(self, ctx):
        await self._l(ctx, "Roles", [f"{r.mention} (`{len(r.members)}`)" for r in ctx.guild.roles[:0:-1]])

    @list_group.command(name="users", help="All human members")
    async def l_users(self, ctx):
        await self._l(ctx, "Users", _members(ctx.guild, lambda m: not m.bot))

    @list_group.command(name="bots", help="All bots")
    async def l_bots(self, ctx):
        await self._l(ctx, "Bots", _members(ctx.guild, lambda m: m.bot))

    @list_group.command(name="bans", help="Banned users")
    @commands.has_permissions(ban_members=True)
    async def l_bans(self, ctx):
        items = [f"{e.user} (`{e.user.id}`)" async for e in ctx.guild.bans(limit=None)]
        await self._l(ctx, "Bans", items)

    @list_group.command(name="boosters", help="Server boosters")
    async def l_boosters(self, ctx):
        await self._l(ctx, "Boosters", _members(ctx.guild, lambda m: m.premium_since))

    @list_group.command(name="emojis", help="Server emojis")
    async def l_emojis(self, ctx):
        await self._l(ctx, "Emojis", [f"{e} `:{e.name}:`" for e in ctx.guild.emojis])

    @list_group.command(name="channels", help="All channels")
    async def l_channels(self, ctx):
        await self._l(ctx, "Channels", [f"{c.mention} — `{c.type.name}`" for c in ctx.guild.channels if not isinstance(c, discord.CategoryChannel)])

    @list_group.command(name="timeouts", help="Members in timeout")
    async def l_timeouts(self, ctx):
        await self._l(ctx, "Timeouts", [f"{m.mention} — {discord.utils.format_dt(m.timed_out_until, 'R')}" for m in ctx.guild.members if m.is_timed_out()])

    @list_group.command(name="hasperms", aliases=["hasperm"], help="Members having a permission")
    async def l_hasperms(self, ctx, permission: str):
        perm = permission.lower().replace(" ", "_")
        if perm not in discord.Permissions.VALID_FLAGS:
            return await send_err(ctx, "Invalid permission. Example: `ban_members`")
        await self._l(ctx, f"Has {perm}", _members(ctx.guild, lambda m: getattr(m.guild_permissions, perm) and not m.bot))

    @list_group.command(name="admins", aliases=["admin"], help="Members with Administrator")
    async def l_admins(self, ctx):
        await self._l(ctx, "Admins", _members(ctx.guild, lambda m: m.guild_permissions.administrator and not m.bot))

    @list_group.command(name="mods", aliases=["mod"], help="Moderators (kick/ban/manage messages)")
    async def l_mods(self, ctx):
        p = lambda m: not m.bot and (m.guild_permissions.kick_members or m.guild_permissions.ban_members or m.guild_permissions.manage_messages)
        await self._l(ctx, "Mods", _members(ctx.guild, p))

    @list_group.command(name="inrole", help="Members in a role")
    async def l_inrole(self, ctx, *, role: discord.Role):
        await self._l(ctx, f"In {role.name}", [f"{m.mention} (`{m.id}`)" for m in role.members])

    @list_group.command(name="hypesquad", help="HypeSquad members")
    async def l_hypesquad(self, ctx):
        def f(m):
            pf = m.public_flags
            return "Bravery" if pf.hypesquad_bravery else "Brilliance" if pf.hypesquad_brilliance else "Balance" if pf.hypesquad_balance else None
        await self._l(ctx, "HypeSquad", [f"{m.mention} — {f(m)}" for m in ctx.guild.members if f(m)])

    @list_group.command(name="pending", help="Members who haven't passed screening")
    async def l_pending(self, ctx):
        await self._l(ctx, "Pending", _members(ctx.guild, lambda m: m.pending))

    @list_group.command(name="invoice", aliases=["invc", "invchannel"], help="Members in your voice channel")
    async def l_invoice(self, ctx):
        if not ctx.author.voice:
            return await send_err(ctx, "Join a voice channel first.")
        ch = ctx.author.voice.channel
        await self._l(ctx, f"In {ch.name}", [f"{m.mention} (`{m.id}`)" for m in ch.members])

    @list_group.command(name="activedeveloper", aliases=["activedev", "adev"], help="Active Developer badge holders")
    async def l_adev(self, ctx):
        await self._l(ctx, "Active Developers", _members(ctx.guild, lambda m: m.public_flags.active_developer))

    @list_group.command(name="joinedat", aliases=["joindate"], help="Members sorted by join date")
    async def l_joinedat(self, ctx):
        ms = sorted((m for m in ctx.guild.members if m.joined_at), key=lambda m: m.joined_at)
        await self._l(ctx, "Join Order", [f"{m.mention} — {discord.utils.format_dt(m.joined_at, 'd')}" for m in ms])

    @list_group.command(name="early", aliases=["earlysupporter"], help="Early Supporter badge holders")
    async def l_early(self, ctx):
        await self._l(ctx, "Early Supporters", _members(ctx.guild, lambda m: m.public_flags.early_supporter))

    @list_group.command(name="createdat", aliases=["accountage"], help="Members sorted by account age")
    async def l_createdat(self, ctx):
        ms = sorted(ctx.guild.members, key=lambda m: m.created_at)
        await self._l(ctx, "Oldest Accounts", [f"{m.mention} — {discord.utils.format_dt(m.created_at, 'd')}" for m in ms])

    @list_group.command(name="bughunters", aliases=["bughunter"], help="Bug Hunter badge holders")
    async def l_bughunters(self, ctx):
        await self._l(ctx, "Bug Hunters", _members(ctx.guild, lambda m: m.public_flags.bug_hunter or m.public_flags.bug_hunter_level_2))


async def setup(bot):
    await bot.add_cog(Utility(bot))
