import asyncio
import json
import time
from typing import Union

import discord
from discord import ui
from discord.ext import commands

import config
from emojis import em
from utils.v2 import Panel, Paginated, sep, td, footer, button, send_ok, send_err, send_panel, send_list, i_ok, i_err

A = discord.AuditLogAction
FILTER_META = {
    "ban": "Ban", "kick": "Kick", "prune": "Prune", "memup": "Member Update (dangerous role)",
    "rlcr": "Role Create", "rldl": "Role Delete", "rlup": "Role Update",
    "chcr": "Channel Create", "chdl": "Channel Delete", "chup": "Channel Update",
    "webhookcr": "Webhook Create", "webhookdl": "Webhook Delete", "webhookup": "Webhook Update",
    "botadd": "Bot Add", "serverup": "Guild Update", "meneve": "Mention Spam (@everyone/@here)",
}
ACTION_MAP = {
    A.ban: "ban", A.kick: "kick", A.member_prune: "prune", A.member_role_update: "memup",
    A.role_create: "rlcr", A.role_delete: "rldl", A.role_update: "rlup",
    A.channel_create: "chcr", A.channel_delete: "chdl", A.channel_update: "chup",
    A.overwrite_create: "chup", A.overwrite_update: "chup", A.overwrite_delete: "chup",
    A.webhook_create: "webhookcr", A.webhook_delete: "webhookdl", A.webhook_update: "webhookup",
    A.bot_add: "botadd", A.guild_update: "serverup",
}
PUNISHMENTS = ("ban", "kick", "stripstaff")
DANGEROUS = discord.Permissions(
    administrator=True, ban_members=True, kick_members=True, manage_guild=True, manage_roles=True,
    manage_channels=True, manage_webhooks=True, mention_everyone=True, manage_messages=True,
    manage_threads=True, moderate_members=True)
PUNISH_COOLDOWN = 20.0
SECURITY_ROLE = "Locus Security [X+]"


def dangerous(p: discord.Permissions) -> bool:
    return bool(p.value & DANGEROUS.value)


def an_owner_only():
    async def pred(ctx):
        if not ctx.guild:
            raise commands.NoPrivateMessage()
        if await ctx.bot.get_cog("AntiNuke").is_owner(ctx.guild, ctx.author.id):
            return True
        raise commands.CheckFailure("Only the **server owner** or **extra owners** can do this.")
    return commands.check(pred)


class AntiNuke(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cool: dict = {}
        self.gone_ch: dict = {}
        self.gone_role: dict = {}
        self.prev_role: dict = {}
        self.prev_ch: dict = {}
        self.prev_guild: dict = {}

    # ---------- storage ----------
    async def cfg(self, gid: int) -> dict:
        d = await self.bot.db.kget(gid, "an", {})
        d.setdefault("enabled", False)
        d.setdefault("filters", {})
        d.setdefault("punish", {})
        d.setdefault("log", None)
        return d

    async def save(self, gid: int, d: dict):
        await self.bot.db.kset(gid, "an", d)

    async def extra_owners(self, gid: int) -> set[int]:
        return {r["user_id"] for r in await self.bot.db.all("SELECT user_id FROM an_owners WHERE guild_id=?", gid)}

    async def is_owner(self, guild, uid: int) -> bool:
        return uid == guild.owner_id or uid in await self.extra_owners(guild.id) or uid in config.OWNER_IDS

    async def wl_keys(self, guild, uid: int, member) -> bool | set:
        ids = [uid] + ([r.id for r in member.roles] if member else [])
        keys: set[str] = set()
        for tid in ids:
            row = await self.bot.db.one("SELECT filters FROM an_wl WHERE guild_id=? AND target_id=?", guild.id, tid)
            if row:
                keys |= set(json.loads(row["filters"]))
        return keys

    # ---------- snapshots for recovery ----------
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, ch):
        self.gone_ch[ch.id] = ch

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        self.gone_role[role.id] = role

    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        self.prev_role[after.id] = before

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        self.prev_ch[after.id] = before

    @commands.Cog.listener()
    async def on_guild_update(self, before, after):
        self.prev_guild[after.id] = before

    async def _wait(self, store: dict, key: int):
        for _ in range(10):
            if key in store:
                return store.pop(key)
            await asyncio.sleep(0.3)
        return None

    # ---------- punish / recover ----------
    async def _punish(self, guild, user, member, mode, reason) -> str:
        k = (guild.id, user.id)
        if time.time() - self.cool.get(k, 0) < PUNISH_COOLDOWN:
            return "already punished"
        self.cool[k] = time.time()
        try:
            if mode == "kick" and member:
                await member.kick(reason=reason)
            elif mode == "stripstaff" and member:
                roles = [r for r in member.roles if not r.is_default() and not r.managed
                         and r < guild.me.top_role and dangerous(r.permissions)]
                await member.remove_roles(*roles, reason=reason)
            else:
                await guild.ban(user, reason=reason)
            return mode
        except discord.HTTPException as ex:
            return f"FAILED ({ex.status})"

    async def _recover(self, guild, entry, key) -> str:
        try:
            tid = getattr(entry.target, "id", None)
            if key == "chdl" and (ch := await self._wait(self.gone_ch, tid)):
                new = await ch.clone(reason="AntiNuke recovery")
                try:
                    await new.edit(position=ch.position)
                except discord.HTTPException:
                    pass
                return "channel restored"
            if key == "rldl" and (r := await self._wait(self.gone_role, tid)):
                new = await guild.create_role(name=r.name, permissions=r.permissions, colour=r.colour,
                                              hoist=r.hoist, mentionable=r.mentionable, reason="AntiNuke recovery")
                try:
                    await new.edit(position=r.position)
                except discord.HTTPException:
                    pass
                return "role restored"
            if key == "chcr" and (c := guild.get_channel(tid)):
                await c.delete(reason="AntiNuke recovery")
                return "channel removed"
            if key == "rlcr" and (r := guild.get_role(tid)):
                await r.delete(reason="AntiNuke recovery")
                return "role removed"
            if key == "rlup" and (r := guild.get_role(tid)):
                await asyncio.sleep(0.5)
                if p := self.prev_role.get(tid):
                    await r.edit(name=p.name, permissions=p.permissions, colour=p.colour, hoist=p.hoist,
                                 mentionable=p.mentionable, reason="AntiNuke recovery")
                    return "role reverted"
            if key == "chup" and (c := guild.get_channel(tid)):
                await asyncio.sleep(0.5)
                if p := self.prev_ch.get(tid):
                    await c.edit(name=p.name, overwrites=p.overwrites, reason="AntiNuke recovery")
                    return "channel reverted"
            if key == "serverup":
                await asyncio.sleep(0.5)
                if p := self.prev_guild.get(guild.id):
                    await guild.edit(name=p.name, verification_level=p.verification_level, reason="AntiNuke recovery")
                    return "server settings reverted"
            if key == "webhookcr" and tid:
                await (await self.bot.fetch_webhook(tid)).delete(reason="AntiNuke recovery")
                return "webhook removed"
            if key == "ban" and tid:
                await guild.unban(discord.Object(id=tid), reason="AntiNuke recovery")
                return "victim unbanned"
            if key == "botadd" and (m := guild.get_member(tid)):
                await m.kick(reason="AntiNuke: unauthorized bot")
                return "bot kicked"
        except discord.HTTPException:
            return "recovery failed"
        return "—"

    async def _log(self, guild, cfg, title, text):
        ch = guild.get_channel(cfg["log"]) if cfg["log"] else None
        if ch:
            try:
                await ch.send(view=Panel(f"### {em('antinuke')} {title}", text, color=config.RED, timeout=None),
                              allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                pass

    # ---------- main guard (instant, no counting) ----------
    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry: discord.AuditLogEntry):
        guild, key = entry.guild, ACTION_MAP.get(entry.action)
        if not key or entry.user is None or entry.user.id == self.bot.user.id:
            return
        cfg = await self.cfg(guild.id)
        if not cfg["enabled"] or not cfg["filters"].get(key):
            return
        if await self.is_owner(guild, entry.user.id):
            return
        member = guild.get_member(entry.user.id)
        if key in await self.wl_keys(guild, entry.user.id, member):
            return
        if key == "memup":
            added = [guild.get_role(r.id) for r in getattr(entry.after, "roles", []) or []]
            if not any(r and dangerous(r.permissions) for r in added):
                return
        mode = cfg["punish"].get(key, "ban")
        result = await self._punish(guild, entry.user, member, mode, f"AntiNuke: {FILTER_META[key]}")
        rec = await self._recover(guild, entry, key)
        await self._log(guild, cfg, "AntiNuke Triggered",
                        f"**User:** {entry.user.mention} (`{entry.user.id}`)\n**Action:** {FILTER_META[key]}\n"
                        f"**Punishment:** `{result}`\n**Recovery:** `{rec}`")

    @commands.Cog.listener()
    async def on_message(self, m: discord.Message):
        if m.author.bot or not m.guild or not m.mention_everyone:
            return
        cfg = await self.cfg(m.guild.id)
        if not cfg["enabled"] or not cfg["filters"].get("meneve"):
            return
        if await self.is_owner(m.guild, m.author.id) or "meneve" in await self.wl_keys(m.guild, m.author.id, m.author):
            return
        try:
            await m.delete()
        except discord.HTTPException:
            pass
        result = await self._punish(m.guild, m.author, m.author, cfg["punish"].get("meneve", "ban"), "AntiNuke: mention spam")
        await self._log(m.guild, cfg, "Mention Spam Blocked", f"**User:** {m.author.mention}\n**Punishment:** `{result}`")

    # ---------- UI ----------
    def _filters_text(self, cfg: dict) -> str:
        keys = list(FILTER_META)
        line = lambda k: f"{em('on') if cfg['filters'].get(k) else em('off')} **{FILTER_META[k]}** — `{cfg['punish'].get(k, 'ban')}`"
        return "\n".join(line(k) for k in keys)

    async def filters_view(self, ctx) -> Panel:
        cfg = await self.cfg(ctx.guild.id)
        sel = ui.Select(placeholder="Enabled filters (select / unselect)", min_values=0, max_values=len(FILTER_META), options=[
            discord.SelectOption(label=v[:100], value=k, default=bool(cfg["filters"].get(k))) for k, v in FILTER_META.items()])
        pun = ui.Select(placeholder="Set punishment for ALL filters", options=[
            discord.SelectOption(label=p, value=p) for p in PUNISHMENTS])

        async def on_sel(i: discord.Interaction):
            c = await self.cfg(i.guild.id)
            c["filters"] = {k: (k in sel.values) for k in FILTER_META}
            await self.save(i.guild.id, c)
            await i.response.edit_message(view=await self.filters_view_for(i))

        async def on_pun(i: discord.Interaction):
            c = await self.cfg(i.guild.id)
            c["punish"] = {k: pun.values[0] for k in FILTER_META}
            await self.save(i.guild.id, c)
            await i.response.edit_message(view=await self.filters_view_for(i))
        sel.callback, pun.callback = on_sel, on_pun
        state = f"{em('on')} Enabled" if cfg["enabled"] else f"{em('off')} Disabled"
        return Panel(f"## {em('antinuke')} AntiNuke Filters", f"**Status:** {state}", sep(),
                     self._filters_text(cfg), sep(), ui.ActionRow(sel), ui.ActionRow(pun), footer(),
                     color=config.HELP_COLOR, timeout=180, author_id=ctx.author.id)

    async def filters_view_for(self, interaction):
        class _C:  # minimal ctx
            guild, author = interaction.guild, interaction.user
        return await self.filters_view(_C)

    # ---------- commands ----------
    @commands.group(name="antinuke", aliases=["security", "anti", "an", "antiraid", "sec"],
                    invoke_without_command=True, help="Antinuke status & filters")
    @commands.guild_only()
    async def antinuke(self, ctx):
        await ctx.send(view=await self.filters_view(ctx))

    @antinuke.command(name="help", aliases=["commands", "cmds"], help="Antinuke command list")
    async def an_help(self, ctx):
        p = ctx.clean_prefix
        await send_panel(ctx, f"## {em('antinuke')} AntiNuke Help", sep(),
                         f"`{p}antinuke enable|disable` • `{p}antinuke filters` • `{p}antinuke wizard`\n"
                         f"`{p}antinuke punishment <filter|all> <ban|kick|stripstaff>`\n"
                         f"`{p}antinuke logs [#channel]`\n`{p}antinuke wl <user|role|bot>` • `{p}antinuke unwl <target>`\n"
                         f"`{p}antinuke wlist` • `{p}antinuke wlreset`\n`{p}extraowner set|reset|view|clear [@user]`",
                         footer(), color=config.HELP_COLOR)

    @antinuke.command(name="enable", help="Enable antinuke (all filters if none enabled)")
    @an_owner_only()
    async def an_enable(self, ctx):
        c = await self.cfg(ctx.guild.id)
        c["enabled"] = True
        if not any(c["filters"].values()):
            c["filters"] = {k: True for k in FILTER_META}
        await self.save(ctx.guild.id, c)
        await send_ok(ctx, "AntiNuke **enabled**. Keep my role at the top so I can punish.")

    @antinuke.command(name="disable", help="Disable antinuke")
    @an_owner_only()
    async def an_disable(self, ctx):
        c = await self.cfg(ctx.guild.id)
        c["enabled"] = False
        await self.save(ctx.guild.id, c)
        await send_ok(ctx, "AntiNuke **disabled**.")

    @antinuke.command(name="filters", aliases=["filter"], help="Toggle filters & punishment panel")
    @an_owner_only()
    async def an_filters(self, ctx):
        await ctx.send(view=await self.filters_view(ctx))

    @antinuke.command(name="punishment", aliases=["punish"], help="Set punishment for a filter")
    @an_owner_only()
    async def an_punish(self, ctx, filter_key: str, mode: str):
        mode, filter_key = mode.lower(), filter_key.lower()
        if mode not in PUNISHMENTS or (filter_key != "all" and filter_key not in FILTER_META):
            return await send_err(ctx, f"Filters: `{', '.join(FILTER_META)}`, `all`\nModes: `{', '.join(PUNISHMENTS)}`")
        c = await self.cfg(ctx.guild.id)
        for k in (FILTER_META if filter_key == "all" else [filter_key]):
            c["punish"][k] = mode
        await self.save(ctx.guild.id, c)
        await send_ok(ctx, f"`{filter_key}` → punishment `{mode}`")

    @antinuke.command(name="logs", aliases=["log"], help="Set or view the antinuke log channel")
    @an_owner_only()
    async def an_logs(self, ctx, channel: discord.TextChannel = None):
        c = await self.cfg(ctx.guild.id)
        if channel is None:
            chan = f"<#{c['log']}>" if c["log"] else "Not set"
            return await send_panel(ctx, f"{em('logger')} Log channel: {chan}")
        c["log"] = channel.id
        await self.save(ctx.guild.id, c)
        await send_ok(ctx, f"Antinuke logs → {channel.mention}")

    @antinuke.command(name="wizard", help="Guided one-click setup")
    @an_owner_only()
    @commands.bot_has_permissions(manage_roles=True, manage_channels=True)
    async def an_wizard(self, ctx):
        steps = []
        msg = await ctx.send(view=Panel(f"## {em('antinuke')} AntiNuke Wizard", "Starting…", color=config.HELP_COLOR, timeout=None))

        async def step(t):
            steps.append(f"{em('tick')} {t}")
            await msg.edit(view=Panel(f"## {em('antinuke')} AntiNuke Wizard", "\n".join(steps), color=config.HELP_COLOR, timeout=None))
        g = ctx.guild
        for r in [r for r in g.roles if r.name == SECURITY_ROLE]:
            try:
                await r.delete()
            except discord.HTTPException:
                pass
        role = await g.create_role(name=SECURITY_ROLE, permissions=discord.Permissions(administrator=True), reason="AntiNuke wizard")
        try:
            await role.edit(position=max(1, g.me.top_role.position - 1))
        except discord.HTTPException:
            pass
        await g.me.add_roles(role)
        await step(f"Created role **{SECURITY_ROLE}** and assigned it to me.")
        c = await self.cfg(g.id)
        c["enabled"], c["filters"] = True, {k: True for k in FILTER_META}
        c["punish"] = {k: "ban" for k in FILTER_META}
        await step("Enabled all **16 filters** (punishment: ban).")
        ch = g.get_channel(c["log"]) if c["log"] else None
        if not ch:
            ch = await g.create_text_channel("antinuke-logs", overwrites={
                g.default_role: discord.PermissionOverwrite(view_channel=False),
                g.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)})
            c["log"] = ch.id
        await self.save(g.id, c)
        await step(f"Log channel: {ch.mention}")
        await step(f"Done! Use `{ctx.clean_prefix}antinuke wl @trusted` to whitelist trusted users.")

    async def _wl_view(self, author_id, guild, target) -> Panel:
        kind = "role" if isinstance(target, discord.Role) else ("bot" if getattr(target, "bot", False) else "user")
        row = await self.bot.db.one("SELECT filters FROM an_wl WHERE guild_id=? AND target_id=?", guild.id, target.id)
        cur = set(json.loads(row["filters"])) if row else set()
        sel = ui.Select(placeholder="Whitelisted filters", min_values=0, max_values=len(FILTER_META), options=[
            discord.SelectOption(label=v[:100], value=k, default=k in cur) for k, v in FILTER_META.items()])

        async def cb(i: discord.Interaction):
            vals = list(sel.values)
            if vals:
                await self.bot.db.run("INSERT OR REPLACE INTO an_wl VALUES(?,?,?,?)", guild.id, target.id, kind, json.dumps(vals))
            else:
                await self.bot.db.run("DELETE FROM an_wl WHERE guild_id=? AND target_id=?", guild.id, target.id)
            await i.response.edit_message(view=await self._wl_view(author_id, guild, target))
        sel.callback = cb
        lines = "\n".join(f"{em('on') if k in cur else em('off')} **{v}**" for k, v in FILTER_META.items())
        return Panel(f"## {em('antinuke')} Whitelist • {target.mention}", f"*Manage immunity for this {kind}.*", sep(),
                     lines, sep(), ui.ActionRow(sel), footer(), color=config.HELP_COLOR, timeout=180, author_id=author_id)

    @antinuke.command(name="wl", aliases=["whitelist"], help="Whitelist a user/role/bot per filter")
    @an_owner_only()
    async def an_wl(self, ctx, target: Union[discord.Member, discord.Role, discord.User]):
        await ctx.send(view=await self._wl_view(ctx.author.id, ctx.guild, target), allowed_mentions=discord.AllowedMentions.none())

    @antinuke.command(name="unwl", aliases=["unwhitelist"], help="Remove from whitelist")
    @an_owner_only()
    async def an_unwl(self, ctx, target: Union[discord.Member, discord.Role, discord.User]):
        await self.bot.db.run("DELETE FROM an_wl WHERE guild_id=? AND target_id=?", ctx.guild.id, target.id)
        await send_ok(ctx, f"{target.mention} removed from the whitelist.")

    @antinuke.command(name="wlist", aliases=["whitelisted"], help="List whitelisted targets")
    @an_owner_only()
    async def an_wlist(self, ctx):
        rows = await self.bot.db.all("SELECT * FROM an_wl WHERE guild_id=?", ctx.guild.id)
        items = [f"{'<@&%d>' % r['target_id'] if r['kind'] == 'role' else '<@%d>' % r['target_id']} — `{r['kind']}` • "
                 f"`{len(json.loads(r['filters']))}` filters" for r in rows]
        await send_list(ctx, f"{em('antinuke')} Whitelisted", items, color=config.HELP_COLOR)

    @antinuke.command(name="wlreset", help="Clear the whole whitelist")
    @an_owner_only()
    async def an_wlreset(self, ctx):
        await self.bot.db.run("DELETE FROM an_wl WHERE guild_id=?", ctx.guild.id)
        await send_ok(ctx, "Whitelist cleared.")

    @commands.command(name="extraowner", aliases=["owner", "eo"], help="Manage extra owners: set/reset/view/clear")
    @commands.guild_only()
    async def extraowner(self, ctx, option: str = None, user: discord.Member = None):
        if ctx.author.id != ctx.guild.owner_id and ctx.author.id not in config.OWNER_IDS:
            return await send_err(ctx, "Only the **server owner** can change extra owners.")
        o, db, gid = (option or "").lower(), self.bot.db, ctx.guild.id
        if o == "set" and user:
            await db.run("INSERT OR IGNORE INTO an_owners VALUES(?,?)", gid, user.id)
            return await send_ok(ctx, f"{user.mention} is now an **extra owner**.")
        if o == "reset" and user:
            await db.run("DELETE FROM an_owners WHERE guild_id=? AND user_id=?", gid, user.id)
            return await send_ok(ctx, f"{user.mention} is no longer an extra owner.")
        if o == "view":
            ids = await self.extra_owners(gid)
            return await send_panel(ctx, "## Extra Owners", "\n".join(f"<@{i}>" for i in ids) or "None.")
        if o == "clear":
            await db.run("DELETE FROM an_owners WHERE guild_id=?", gid)
            return await send_ok(ctx, "All extra owners removed.")
        p = ctx.clean_prefix
        await send_panel(ctx, "## Extra Owners", f"`{p}extraowner set @user` • `reset @user` • `view` • `clear`")


async def setup(bot):
    await bot.add_cog(AntiNuke(bot))
