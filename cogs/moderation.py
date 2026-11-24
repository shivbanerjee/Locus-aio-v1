import asyncio
import datetime
import re
import time
from typing import Optional

import discord
from discord.ext import commands

import config
from emojis import em
from utils.checks import can_act, parse_duration, fmt_duration
from utils.v2 import Panel, NO_MENTIONS, confirm, send_ok, send_err, send_panel, send_list

EMOJI_RE = re.compile(r"<a?:\w+:\d+>|[\U0001F300-\U0001FAFF\u2600-\u27BF]")


def _imgs(m):
    return any((a.content_type or "").startswith("image/") for a in m.attachments)


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sniped: dict[int, tuple] = {}

    async def cog_check(self, ctx):
        if not ctx.guild:
            raise commands.NoPrivateMessage()
        return True

    @commands.Cog.listener()
    async def on_message_delete(self, m):
        if m.guild and not m.author.bot and (m.content or m.attachments):
            self.sniped[m.channel.id] = (m.author, m.content, time.time(), [a.url for a in m.attachments])

    async def _dm(self, user, text):
        try:
            await user.send(text)
        except discord.HTTPException:
            pass

    async def _perm(self, ch, **perms):
        role = ch.guild.default_role
        ow = ch.overwrites_for(role)
        for k, v in perms.items():
            setattr(ow, k, v)
        await ch.set_permissions(role, overwrite=ow)

    # ================= member actions =================
    @commands.command(aliases=["kickmember"], help="Kick a member")
    @commands.has_permissions(kick_members=True)
    @commands.bot_has_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason: str = "No reason provided"):
        if err := can_act(ctx, member):
            return await send_err(ctx, err)
        await self._dm(member, f"You were kicked from **{ctx.guild.name}**.\nReason: {reason}")
        await member.kick(reason=f"{ctx.author} | {reason}")
        await send_ok(ctx, f"**{member}** was kicked.")

    @commands.command(aliases=["banmember"], help="Ban a member or user ID")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def ban(self, ctx, user: discord.User, *, reason: str = "No reason provided"):
        m = ctx.guild.get_member(user.id)
        if m and (err := can_act(ctx, m)):
            return await send_err(ctx, err)
        await self._dm(user, f"You were banned from **{ctx.guild.name}**.\nReason: {reason}")
        await ctx.guild.ban(user, reason=f"{ctx.author} | {reason}")
        await send_ok(ctx, f"**{user}** was banned. Reason: {reason}")

    @commands.command(help="Unban a user by ID")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def unban(self, ctx, user_id: int):
        try:
            await ctx.guild.unban(discord.Object(id=user_id), reason=str(ctx.author))
        except discord.NotFound:
            return await send_err(ctx, "That user isn't banned.")
        await send_ok(ctx, f"`{user_id}` was unbanned.")

    @commands.command(help="Ban + unban to delete a member's recent messages")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def softban(self, ctx, member: discord.Member, *, reason: str = "Softban"):
        if err := can_act(ctx, member):
            return await send_err(ctx, err)
        await ctx.guild.ban(member, reason=f"Softban | {reason}", delete_message_seconds=86400)
        await ctx.guild.unban(member, reason="Softban")
        await send_ok(ctx, f"**{member}** was softbanned (recent messages deleted).")

    @commands.command(help="Fake ban (prank only, no real ban)")
    @commands.has_permissions(ban_members=True)
    async def fakeban(self, ctx, member: discord.Member):
        await send_panel(ctx, f"{em('ban')} **{member}** has been banned. *(just kidding 😄)*", color=config.RED)

    @commands.command(help="Unban every banned user")
    @commands.has_permissions(administrator=True)
    @commands.bot_has_permissions(ban_members=True)
    async def unbanall(self, ctx):
        if not await confirm(ctx, "Unban **every** banned user?"):
            return
        n = 0
        async for e in ctx.guild.bans(limit=None):
            try:
                await ctx.guild.unban(e.user, reason=f"unbanall by {ctx.author}")
                n += 1
            except discord.HTTPException:
                pass
        await send_ok(ctx, f"Unbanned **{n}** users.")

    @commands.command(aliases=["timeout"], help="Timeout a member (e.g. 10m, 2h, 1d)")
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    async def mute(self, ctx, member: discord.Member, duration: str = "10m", *, reason: str = "No reason provided"):
        if err := can_act(ctx, member):
            return await send_err(ctx, err)
        secs = parse_duration(duration)
        if not secs or secs > 28 * 86400:
            return await send_err(ctx, "Invalid duration. Example: `10m`, `2h`, `1d` (max 28d).")
        await member.timeout(datetime.timedelta(seconds=secs), reason=f"{ctx.author} | {reason}")
        await send_ok(ctx, f"**{member}** was muted for **{fmt_duration(secs)}**.")

    @commands.command(aliases=["untimeout"], help="Remove timeout")
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    async def unmute(self, ctx, member: discord.Member):
        await member.timeout(None, reason=str(ctx.author))
        await send_ok(ctx, f"**{member}** was unmuted.")

    @commands.command(aliases=["nickname"], help="Change or reset a member's nickname")
    @commands.has_permissions(manage_nicknames=True)
    @commands.bot_has_permissions(manage_nicknames=True)
    async def nick(self, ctx, member: discord.Member, *, nickname: str = None):
        if err := can_act(ctx, member):
            return await send_err(ctx, err)
        await member.edit(nick=nickname[:32] if nickname else None)
        await send_ok(ctx, f"Nickname {'reset' if not nickname else 'set'} for **{member.name}**.")

    # ================= warnings (extra) =================
    @commands.command(help="Warn a member")
    @commands.has_permissions(moderate_members=True)
    async def warn(self, ctx, member: discord.Member, *, reason: str = "No reason provided"):
        if err := can_act(ctx, member):
            return await send_err(ctx, err)
        await self.bot.db.run("INSERT INTO warnings(guild_id,user_id,mod_id,reason,ts) VALUES(?,?,?,?,?)",
                              ctx.guild.id, member.id, ctx.author.id, reason, int(time.time()))
        n = await self.bot.db.val("SELECT COUNT(*) FROM warnings WHERE guild_id=? AND user_id=?", ctx.guild.id, member.id)
        await self._dm(member, f"You received a warning in **{ctx.guild.name}**: {reason}")
        await send_ok(ctx, f"**{member}** warned (total **{n}**). Reason: {reason}")

    @commands.command(aliases=["warns"], help="Show warnings of a member")
    @commands.has_permissions(moderate_members=True)
    async def warnings(self, ctx, member: discord.Member):
        rows = await self.bot.db.all("SELECT id, mod_id, reason, ts FROM warnings WHERE guild_id=? AND user_id=? ORDER BY id DESC",
                                     ctx.guild.id, member.id)
        await send_list(ctx, f"{em('warn')} Warnings • {member.display_name}",
                        [f"`#{r['id']}` <t:{r['ts']}:R> by <@{r['mod_id']}> — {r['reason'][:80]}" for r in rows], color=config.YELLOW)

    @commands.command(aliases=["clearwarnings"], help="Clear all warnings of a member")
    @commands.has_permissions(administrator=True)
    async def clearwarns(self, ctx, member: discord.Member):
        await self.bot.db.run("DELETE FROM warnings WHERE guild_id=? AND user_id=?", ctx.guild.id, member.id)
        await send_ok(ctx, f"Cleared all warnings for **{member}**.")

    # ================= channel controls =================
    @commands.command(help="Lock a channel")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def lock(self, ctx, channel: discord.TextChannel = None):
        ch = channel or ctx.channel
        await self._perm(ch, send_messages=False)
        await send_ok(ctx, f"{ch.mention} **locked** 🔒")

    @commands.command(help="Unlock a channel")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def unlock(self, ctx, channel: discord.TextChannel = None):
        ch = channel or ctx.channel
        await self._perm(ch, send_messages=None)
        await send_ok(ctx, f"{ch.mention} **unlocked** 🔓")

    @commands.command(help="Hide a channel from everyone")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def hide(self, ctx, channel: discord.TextChannel = None):
        ch = channel or ctx.channel
        await self._perm(ch, view_channel=False)
        await send_ok(ctx, f"{ch.mention} **hidden** 🙈")

    @commands.command(help="Unhide a channel")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def unhide(self, ctx, channel: discord.TextChannel = None):
        ch = channel or ctx.channel
        await self._perm(ch, view_channel=None)
        await send_ok(ctx, f"{ch.mention} **visible** 👁️")

    async def _all(self, ctx, label, **perms):
        if not await confirm(ctx, f"Apply **{label}** to all text channels?"):
            return
        n = 0
        for ch in ctx.guild.text_channels:
            try:
                await self._perm(ch, **perms)
                n += 1
            except discord.HTTPException:
                pass
        await send_ok(ctx, f"**{label}** applied to **{n}** channels.")

    @commands.command(help="Lock all text channels")
    @commands.has_permissions(administrator=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def lockall(self, ctx):
        await self._all(ctx, "lock", send_messages=False)

    @commands.command(help="Unlock all text channels")
    @commands.has_permissions(administrator=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def unlockall(self, ctx):
        await self._all(ctx, "unlock", send_messages=None)

    @commands.command(help="Hide all text channels")
    @commands.has_permissions(administrator=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def hideall(self, ctx):
        await self._all(ctx, "hide", view_channel=False)

    @commands.command(help="Unhide all text channels")
    @commands.has_permissions(administrator=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def unhideall(self, ctx):
        await self._all(ctx, "unhide", view_channel=None)

    @commands.command(aliases=["slow"], help="Set slowmode in seconds")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def slowmode(self, ctx, seconds: commands.Range[int, 0, 21600] = 5, channel: discord.TextChannel = None):
        ch = channel or ctx.channel
        await ch.edit(slowmode_delay=seconds)
        await send_ok(ctx, f"{ch.mention} slowmode: **{seconds}s**")

    @commands.command(aliases=["unslow"], help="Remove slowmode")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def unslowmode(self, ctx, channel: discord.TextChannel = None):
        ch = channel or ctx.channel
        await ch.edit(slowmode_delay=0)
        await send_ok(ctx, f"{ch.mention} slowmode **off**.")

    @commands.command(help="Delete & recreate a channel (wipes all messages)")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def nuke(self, ctx, channel: discord.TextChannel = None):
        ch = channel or ctx.channel
        if not await confirm(ctx, f"Delete **all messages** in {ch.mention}? (The channel will be recreated.)"):
            return
        pos = ch.position
        new = await ch.clone(reason=f"Nuke by {ctx.author}")
        await ch.delete()
        await new.edit(position=pos)
        await new.send(view=Panel(f"💥 Channel nuked by {ctx.author.mention}", color=config.RED, timeout=None))

    @commands.command(help="Show the last deleted message of this channel")
    async def snipe(self, ctx):
        s = self.sniped.get(ctx.channel.id)
        if not s:
            return await send_err(ctx, "Nothing to snipe.")
        files = "\n".join(s[3])
        await send_panel(ctx, f"### 🔫 Sniped • {s[0].display_name}", (s[1] or "*no text*")[:1500] + (f"\n{files}" if files else ""),
                         f"-# <t:{int(s[2])}:R>")

    # ================= channel group =================
    @commands.group(name="channel", aliases=["ch"], invoke_without_command=True, help="Channel tools")
    @commands.has_permissions(manage_channels=True)
    async def channel_group(self, ctx):
        p = ctx.clean_prefix
        await send_panel(ctx, "## Channel Tools", f"`{p}channel create <name>` • `delete [#ch]` • `rename <name>`\n`clone [#ch]` • `transfer <#ch> <category>`")

    @channel_group.command(name="create", help="Create a text channel")
    @commands.bot_has_permissions(manage_channels=True)
    async def ch_create(self, ctx, *, name: str):
        ch = await ctx.guild.create_text_channel(name[:90], reason=str(ctx.author))
        await send_ok(ctx, f"Created {ch.mention}")

    @channel_group.command(name="delete", help="Delete a channel")
    @commands.bot_has_permissions(manage_channels=True)
    async def ch_delete(self, ctx, channel: discord.abc.GuildChannel = None):
        ch = channel or ctx.channel
        if not await confirm(ctx, f"Delete **#{ch.name}**?"):
            return
        await ch.delete(reason=str(ctx.author))
        if ch.id != ctx.channel.id:
            await send_ok(ctx, f"`#{ch.name}` deleted.")

    @channel_group.command(name="rename", help="Rename this channel")
    @commands.bot_has_permissions(manage_channels=True)
    async def ch_rename(self, ctx, *, name: str):
        await ctx.channel.edit(name=name[:90])
        await send_ok(ctx, f"Renamed to **{name[:90]}**")

    @channel_group.command(name="clone", help="Clone a channel")
    @commands.bot_has_permissions(manage_channels=True)
    async def ch_clone(self, ctx, channel: discord.abc.GuildChannel = None):
        new = await (channel or ctx.channel).clone(reason=str(ctx.author))
        await send_ok(ctx, f"Cloned → {new.mention}")

    @channel_group.command(name="transfer", help="Move a channel to a category")
    @commands.bot_has_permissions(manage_channels=True)
    async def ch_transfer(self, ctx, channel: discord.abc.GuildChannel, category: discord.CategoryChannel):
        await channel.edit(category=category)
        await send_ok(ctx, f"{channel.mention} → **{category.name}**")

    # ================= purge =================
    async def _purge(self, ctx, amount: int, pred=None):
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass
        count = {"n": 0}

        def check(m):
            if count["n"] >= amount or (pred and not pred(m)):
                return False
            count["n"] += 1
            return True
        deleted = await ctx.channel.purge(limit=1000 if pred else amount, check=check if pred else None)
        await ctx.send(view=Panel(f"{em('tick')} **{len(deleted)}** messages deleted.", color=config.GREEN, timeout=None), delete_after=4)

    @commands.group(name="clear", aliases=["purge", "clean"], invoke_without_command=True, help="Delete the last N messages")
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def clear(self, ctx, amount: commands.Range[int, 1, 1000] = 10):
        await self._purge(ctx, amount)

    @commands.command(aliases=["purgeall"], help="Delete up to 1000 recent messages")
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def clearall(self, ctx):
        await self._purge(ctx, 1000)

    @commands.command(aliases=["purgeuser"], help="Delete messages of one member")
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def clearuser(self, ctx, member: discord.Member, amount: commands.Range[int, 1, 1000] = 100):
        await self._purge(ctx, amount, lambda m: m.author.id == member.id)

    @commands.command(aliases=["purgebots"], help="Delete bot messages")
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def clearbots(self, ctx, amount: commands.Range[int, 1, 1000] = 100):
        await self._purge(ctx, amount, lambda m: m.author.bot)

    @commands.command(aliases=["clearembeds"], help="Delete messages with embeds")
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def clearembed(self, ctx, amount: commands.Range[int, 1, 1000] = 100):
        await self._purge(ctx, amount, lambda m: bool(m.embeds))

    @commands.command(help="Delete messages with mentions")
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def clearmentions(self, ctx, amount: commands.Range[int, 1, 1000] = 100):
        await self._purge(ctx, amount, lambda m: bool(m.mentions or m.role_mentions or m.mention_everyone))

    @commands.command(help="Delete messages with attachments (non-image)")
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def clearfiles(self, ctx, amount: commands.Range[int, 1, 1000] = 100):
        await self._purge(ctx, amount, lambda m: bool(m.attachments) and not _imgs(m))

    @commands.command(help="Delete messages with images")
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def clearimages(self, ctx, amount: commands.Range[int, 1, 1000] = 100):
        await self._purge(ctx, amount, _imgs)

    @commands.command(help="Delete messages with emojis")
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def clearemoji(self, ctx, amount: commands.Range[int, 1, 1000] = 100):
        await self._purge(ctx, amount, lambda m: bool(EMOJI_RE.search(m.content)))

    @commands.command(help="Delete messages containing some text")
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def clearcontain(self, ctx, text: str, amount: commands.Range[int, 1, 1000] = 100):
        await self._purge(ctx, amount, lambda m: text.lower() in m.content.lower())

    @commands.command(help="Remove reactions from the last N messages")
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def clearreactions(self, ctx, amount: commands.Range[int, 1, 100] = 20):
        n = 0
        async for m in ctx.channel.history(limit=amount):
            if m.reactions:
                await m.clear_reactions()
                n += 1
        await send_ok(ctx, f"Cleared reactions from **{n}** messages.")

    # ================= roles =================
    def _role_ok(self, ctx, role) -> Optional[str]:
        if role.managed or role.is_default():
            return "This role can't be assigned or removed."
        if role >= ctx.guild.me.top_role:
            return "That role is equal to or higher than my top role."
        if ctx.author.id != ctx.guild.owner_id and role >= ctx.author.top_role:
            return "That role is equal to or higher than your top role."
        return None

    @commands.group(name="role", aliases=["r"], invoke_without_command=True, help="Toggle a role on a member")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def role(self, ctx, member: discord.Member = None, *, role: discord.Role = None):
        if not member or not role:
            p = ctx.clean_prefix
            return await send_panel(ctx, "## Role Tools",
                                    f"`{p}role <member> <role>` toggle • `add` • `remove` • `create <name>` • `delete <role>`\n"
                                    f"`rename <role> <name>` • `colour <role> <#hex>` • `all|humans|bots <role>`\n"
                                    f"`{p}rrole <role>` • `rrolehumans` • `rrolebots` • `rroleall`")
        if err := self._role_ok(ctx, role):
            return await send_err(ctx, err)
        if role in member.roles:
            await member.remove_roles(role, reason=str(ctx.author))
            await send_ok(ctx, f"{role.mention} ← **{member}**")
        else:
            await member.add_roles(role, reason=str(ctx.author))
            await send_ok(ctx, f"{role.mention} → **{member}**")

    @role.command(name="add", help="Give a role to a member")
    async def role_add(self, ctx, member: discord.Member, *, role: discord.Role):
        if err := self._role_ok(ctx, role):
            return await send_err(ctx, err)
        await member.add_roles(role, reason=str(ctx.author))
        await send_ok(ctx, f"{role.mention} → **{member}**")

    @role.command(name="remove", help="Remove a role from a member")
    async def role_remove(self, ctx, member: discord.Member, *, role: discord.Role):
        if err := self._role_ok(ctx, role):
            return await send_err(ctx, err)
        await member.remove_roles(role, reason=str(ctx.author))
        await send_ok(ctx, f"{role.mention} ← **{member}**")

    @role.command(name="create", help="Create a role")
    async def role_create(self, ctx, *, name: str):
        r = await ctx.guild.create_role(name=name[:100], reason=str(ctx.author))
        await send_ok(ctx, f"Created {r.mention}")

    @role.command(name="delete", help="Delete a role")
    async def role_delete(self, ctx, *, role: discord.Role):
        if err := self._role_ok(ctx, role):
            return await send_err(ctx, err)
        await role.delete(reason=str(ctx.author))
        await send_ok(ctx, f"`{role.name}` deleted.")

    @role.command(name="rename", help="Rename a role")
    async def role_rename(self, ctx, role: discord.Role, *, name: str):
        if err := self._role_ok(ctx, role):
            return await send_err(ctx, err)
        await role.edit(name=name[:100])
        await send_ok(ctx, f"Renamed to **{name[:100]}**")

    @role.command(name="colour", aliases=["color"], help="Change role colour (hex)")
    async def role_colour(self, ctx, role: discord.Role, colour: discord.Colour):
        if err := self._role_ok(ctx, role):
            return await send_err(ctx, err)
        await role.edit(colour=colour)
        await send_ok(ctx, f"Colour updated: `{colour}`")

    async def _mass(self, ctx, role, members, add: bool):
        if err := self._role_ok(ctx, role):
            return await send_err(ctx, err)
        if not await confirm(ctx, f"{'Add' if add else 'Remove'} {role.mention} {'to' if add else 'from'} **{len(members)}** members?"):
            return
        n = 0
        for m in members:
            try:
                await (m.add_roles(role) if add else m.remove_roles(role))
                n += 1
                await asyncio.sleep(0.4)
            except discord.HTTPException:
                pass
        await send_ok(ctx, f"{role.mention} → **{n}** members.")

    @role.command(name="all", help="Give a role to everyone")
    async def role_all(self, ctx, *, role: discord.Role):
        await self._mass(ctx, role, [m for m in ctx.guild.members if role not in m.roles], True)

    @role.command(name="humans", help="Give a role to all humans")
    async def role_humans(self, ctx, *, role: discord.Role):
        await self._mass(ctx, role, [m for m in ctx.guild.members if not m.bot and role not in m.roles], True)

    @role.command(name="bots", help="Give a role to all bots")
    async def role_bots(self, ctx, *, role: discord.Role):
        await self._mass(ctx, role, [m for m in ctx.guild.members if m.bot and role not in m.roles], True)

    @commands.command(help="Remove a role from everyone")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def rroleall(self, ctx, *, role: discord.Role):
        await self._mass(ctx, role, list(role.members), False)

    @commands.command(aliases=["rrolehuman"], help="Remove a role from all humans")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def rrolehumans(self, ctx, *, role: discord.Role):
        await self._mass(ctx, role, [m for m in role.members if not m.bot], False)

    @commands.command(aliases=["rrolebot"], help="Remove a role from all bots")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def rrolebots(self, ctx, *, role: discord.Role):
        await self._mass(ctx, role, [m for m in role.members if m.bot], False)

    @commands.command(help="Remove a role from everyone (alias of rroleall)")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def rrole(self, ctx, *, role: discord.Role):
        await self._mass(ctx, role, list(role.members), False)


async def setup(bot):
    await bot.add_cog(Moderation(bot))
