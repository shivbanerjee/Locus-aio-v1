import datetime
import difflib
import re
import time
from collections import defaultdict, deque

import discord
from discord import ui
from discord.ext import commands

import config
from emojis import em
from utils.v2 import Panel, sep, footer, send_ok, send_err, send_panel, send_list, confirm

FILTERS = [
    "Anti Spam", "Anti Caps", "Anti Link", "Anti Invites", "Anti Mass Mention", "Anti Emoji Spam",
    "Anti NSFW Link", "Anti Attachment Spam", "Anti Zalgo Spam", "Similar Message Spam",
    "Character Limit Spam", "New Line Spam", "Blacklist Word",
]
DESC = {
    "Anti Spam": "Rapid messages build heat; punished at 100 heat.",
    "Anti Caps": "More than 70% CAPS (min 45 chars).",
    "Anti Link": "Any unauthorized link.",
    "Anti Invites": "Discord server invites.",
    "Anti Mass Mention": "5 or more mentions in one message.",
    "Anti Emoji Spam": "More than 5 emojis in one message.",
    "Anti NSFW Link": "NSFW links / keywords (message always deleted).",
    "Anti Attachment Spam": "5 or more attachments in one message.",
    "Anti Zalgo Spam": "Zalgo / glitch text (message deleted).",
    "Similar Message Spam": "Near-identical messages repeated.",
    "Character Limit Spam": "Message longer than 1200 characters.",
    "New Line Spam": "10 or more line breaks (message deleted).",
    "Blacklist Word": "Words from the server blacklist.",
}
HEAT = {"Anti Spam": 15, "Anti Caps": 50, "Anti Link": 100, "Anti Invites": 100, "Anti Mass Mention": 100,
        "Anti Emoji Spam": 50, "Anti NSFW Link": 100, "Anti Attachment Spam": 50, "Anti Zalgo Spam": 100,
        "Similar Message Spam": 35, "Character Limit Spam": 100, "New Line Spam": 50, "Blacklist Word": 100}
FIXED_DELETE = {"Anti NSFW Link", "Anti Zalgo Spam", "New Line Spam"}
PUNISH_TYPES = ["Auto Mute", "Kick", "Ban", "Delete"]
HEAT_LIMIT, HEAT_DECAY, MUTE_MIN = 100.0, 5.0, 10

INVITE_RE = re.compile(r"(discord\.gg|discord(?:app)?\.com/invite)/\S+", re.I)
LINK_RE = re.compile(r"https?://\S+|www\.\S+", re.I)
EMOJI_RE = re.compile(r"<a?:\w+:\d+>|[\U0001F300-\U0001FAFF\u2600-\u27BF]")
ZALGO_RE = re.compile("[\u0300-\u036f\u0483-\u0489\u1dc0-\u1dff\u20d0-\u20ff\ufe20-\ufe2f]{3,}")
NSFW = ("pornhub", "xvideos", "xnxx", "xhamster", "redtube", "brazzers", "rule34", "hentai", "onlyfans.com", "porn")


class AutoMod(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.heat: dict = {}
        self.recent = defaultdict(lambda: deque(maxlen=4))

    # ---------- config ----------
    async def cfg(self, gid: int) -> dict:
        d = await self.bot.db.kget(gid, "am", {})
        d.setdefault("enabled", False)
        d.setdefault("filters", {})
        d.setdefault("punish", {})
        d.setdefault("log", None)
        d.setdefault("wl_channels", [])
        d.setdefault("wl_roles", [])
        d.setdefault("words", [])
        return d

    async def save(self, gid: int, d: dict):
        await self.bot.db.kset(gid, "am", d)

    def _add_heat(self, gid, uid, amount) -> float:
        now = time.time()
        v, ts = self.heat.get((gid, uid), (0.0, now))
        v = max(0.0, v - (now - ts) * HEAT_DECAY) + amount
        self.heat[(gid, uid)] = (v, now)
        return v

    # ---------- detection ----------
    def _hit(self, name: str, m: discord.Message, cfg: dict) -> bool:
        t = m.content
        if name == "Anti Spam":
            return True  # every message adds heat
        if name == "Anti Caps":
            letters = [c for c in t if c.isalpha()]
            return len(t) >= 45 and letters and sum(c.isupper() for c in letters) / len(letters) > 0.7
        if name == "Anti Link":
            return bool(LINK_RE.search(t)) and not INVITE_RE.search(t)
        if name == "Anti Invites":
            return bool(INVITE_RE.search(t))
        if name == "Anti Mass Mention":
            return len(m.mentions) + len(m.role_mentions) >= 5
        if name == "Anti Emoji Spam":
            return len(EMOJI_RE.findall(t)) > 5
        if name == "Anti NSFW Link":
            low = t.lower()
            return any(k in low for k in NSFW)
        if name == "Anti Attachment Spam":
            return len(m.attachments) >= 5
        if name == "Anti Zalgo Spam":
            return bool(ZALGO_RE.search(t))
        if name == "Similar Message Spam":
            q = self.recent[(m.guild.id, m.author.id)]
            now = time.time()
            sim = sum(1 for ts, old in q if now - ts < 60 and difflib.SequenceMatcher(None, old, t).ratio() >= 0.9)
            q.append((now, t))
            return len(t) > 3 and sim >= 2
        if name == "Character Limit Spam":
            return len(t) > 1200
        if name == "New Line Spam":
            return t.count("\n") >= 10
        if name == "Blacklist Word":
            tokens = set(re.findall(r"\w+", t.lower()))
            return bool(tokens & set(cfg["words"]))
        return False

    async def _apply(self, m: discord.Message, name: str, cfg: dict, punish: str):
        reason = f"AutoMod: {name}"
        try:
            if punish == "Auto Mute":
                await m.author.timeout(datetime.timedelta(minutes=MUTE_MIN), reason=reason)
            elif punish == "Kick":
                await m.author.kick(reason=reason)
            elif punish == "Ban":
                await m.guild.ban(m.author, reason=reason)
        except discord.HTTPException:
            pass
        await self._log(m.guild, cfg, f"{name} • {punish}", f"**User:** {m.author.mention} (`{m.author.id}`)\n**Channel:** {m.channel.mention}")
        if name == "Anti Spam":  # clean up the burst
            try:
                await m.channel.purge(limit=15, check=lambda x: x.author.id == m.author.id and (time.time() - x.created_at.timestamp()) < 20)
            except discord.HTTPException:
                pass

    async def _log(self, guild, cfg, title, text):
        ch = guild.get_channel(cfg["log"]) if cfg["log"] else None
        if ch:
            try:
                await ch.send(view=Panel(f"### {em('automod')} {title}", text, color=config.YELLOW, timeout=None),
                              allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_message(self, m: discord.Message):
        if m.author.bot or not m.guild or not isinstance(m.author, discord.Member):
            return
        cfg = await self.cfg(m.guild.id)
        if not cfg["enabled"] or not any(cfg["filters"].values()):
            return
        if (m.author.guild_permissions.administrator or m.author.id in config.OWNER_IDS
                or m.channel.id in cfg["wl_channels"] or any(r.id in cfg["wl_roles"] for r in m.author.roles)):
            return
        for name in FILTERS:
            if not cfg["filters"].get(name) or not self._hit(name, m, cfg):
                continue
            punish = "Delete" if name in FIXED_DELETE else cfg["punish"].get(name, "Auto Mute")
            heat = self._add_heat(m.guild.id, m.author.id, HEAT[name])
            if name != "Anti Spam":
                try:
                    await m.delete()
                except discord.HTTPException:
                    pass
            if heat >= HEAT_LIMIT:
                self.heat[(m.guild.id, m.author.id)] = (0.0, time.time())
                await self._apply(m, name, cfg, punish)
                try:
                    await m.channel.send(view=Panel(f"{em('warn')} {m.author.mention} — **{name}** ({punish}).",
                                                    color=config.YELLOW, timeout=None), delete_after=5)
                except discord.HTTPException:
                    pass
            return

    # ---------- UI ----------
    async def settings_view(self, author_id, guild) -> Panel:
        cfg = await self.cfg(guild.id)
        lines = "\n".join(f"{em('on') if cfg['filters'].get(f) else em('off')} **{f}** — `{'Delete' if f in FIXED_DELETE else cfg['punish'].get(f, 'Auto Mute')}`" for f in FILTERS)
        sel = ui.Select(placeholder="Enabled filters (select / unselect)", min_values=0, max_values=len(FILTERS), options=[
            discord.SelectOption(label=f, value=f, description=DESC[f][:100], default=bool(cfg["filters"].get(f))) for f in FILTERS])
        pun = ui.Select(placeholder="Set punishment for ALL filters", options=[discord.SelectOption(label=p, value=p) for p in PUNISH_TYPES])

        async def on_sel(i):
            c = await self.cfg(i.guild.id)
            c["filters"] = {f: f in sel.values for f in FILTERS}
            await self.save(i.guild.id, c)
            await i.response.edit_message(view=await self.settings_view(i.user.id, i.guild))

        async def on_pun(i):
            c = await self.cfg(i.guild.id)
            c["punish"] = {f: pun.values[0] for f in FILTERS}
            await self.save(i.guild.id, c)
            await i.response.edit_message(view=await self.settings_view(i.user.id, i.guild))
        sel.callback, pun.callback = on_sel, on_pun
        state = f"{em('on')} Enabled" if cfg["enabled"] else f"{em('off')} Disabled"
        log = f"<#{cfg['log']}>" if cfg["log"] else "Not set"
        return Panel(f"## {em('automod')} AutoMod", f"**Status:** {state} • **Log:** {log}\n"
                     f"**Whitelist:** `{len(cfg['wl_channels'])}` channels • `{len(cfg['wl_roles'])}` roles • "
                     f"**Blacklist words:** `{len(cfg['words'])}`", sep(), lines, sep(),
                     ui.ActionRow(sel), ui.ActionRow(pun), footer(), color=config.HELP_COLOR, timeout=180, author_id=author_id)

    # ---------- commands ----------
    @commands.group(name="automod", aliases=["am", "amod"], invoke_without_command=True, help="AutoMod settings panel")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def automod(self, ctx):
        await ctx.send(view=await self.settings_view(ctx.author.id, ctx.guild))

    @automod.command(name="help", aliases=["commands", "cmds"], help="AutoMod command list")
    async def am_help(self, ctx):
        p = ctx.clean_prefix
        await send_panel(ctx, f"## {em('automod')} AutoMod Help", sep(),
                         f"`{p}automod enable|disable` • `manage` • `settings` • `rules` • `reset`\n"
                         f"`{p}automod punishment <filter> <Auto Mute|Kick|Ban|Delete>`\n`{p}automod logging [#channel]`\n"
                         f"`{p}automod whitelist channel|role|show|reset`\n`{p}automod blacklist add|remove|list <words>`",
                         footer(), color=config.HELP_COLOR)

    @automod.command(name="enable", help="Enable automod (all filters if none enabled)")
    @commands.has_permissions(manage_guild=True)
    async def am_enable(self, ctx):
        c = await self.cfg(ctx.guild.id)
        c["enabled"] = True
        if not any(c["filters"].values()):
            c["filters"] = {f: True for f in FILTERS}
        await self.save(ctx.guild.id, c)
        await send_ok(ctx, "AutoMod **enabled**.")

    @automod.command(name="disable", help="Disable automod")
    @commands.has_permissions(manage_guild=True)
    async def am_disable(self, ctx):
        c = await self.cfg(ctx.guild.id)
        c["enabled"] = False
        await self.save(ctx.guild.id, c)
        await send_ok(ctx, "AutoMod **disabled**.")

    @automod.command(name="manage", aliases=["filters", "toggle"], help="Toggle filters & punishments")
    @commands.has_permissions(manage_guild=True)
    async def am_manage(self, ctx):
        await ctx.send(view=await self.settings_view(ctx.author.id, ctx.guild))

    @automod.command(name="settings", aliases=["config", "panel"], help="Show current settings")
    @commands.has_permissions(manage_guild=True)
    async def am_settings(self, ctx):
        await ctx.send(view=await self.settings_view(ctx.author.id, ctx.guild))

    @automod.command(name="rules", help="Explain every filter")
    async def am_rules(self, ctx):
        await send_list(ctx, f"{em('automod')} AutoMod Rules", [f"**{f}**\n{DESC[f]}" for f in FILTERS], per_page=5, color=config.HELP_COLOR)

    @automod.command(name="punishment", aliases=["punish"], help="Set punishment for one filter")
    @commands.has_permissions(manage_guild=True)
    async def am_punish(self, ctx, filter_name: str, *, mode: str):
        f = next((x for x in FILTERS if x.lower().replace(" ", "") == filter_name.lower().replace(" ", "")), None)
        p = next((x for x in PUNISH_TYPES if x.lower() == mode.lower()), None)
        if not f or not p:
            return await send_err(ctx, f"Filter: `{', '.join(x.replace(' ', '') for x in FILTERS)}`\nPunishment: `{', '.join(PUNISH_TYPES)}`")
        c = await self.cfg(ctx.guild.id)
        c["punish"][f] = p
        await self.save(ctx.guild.id, c)
        await send_ok(ctx, f"**{f}** → `{p}`")

    @automod.command(name="reset", help="Reset all automod settings")
    @commands.has_permissions(manage_guild=True)
    async def am_reset(self, ctx):
        if await confirm(ctx, "Reset **all AutoMod settings**?"):
            await self.bot.db.kdel(ctx.guild.id, "am")
            await send_ok(ctx, "AutoMod has been reset.")

    @automod.command(name="logging", aliases=["log", "logs"], help="Set or view the automod log channel")
    @commands.has_permissions(manage_guild=True)
    async def am_logging(self, ctx, channel: discord.TextChannel = None):
        c = await self.cfg(ctx.guild.id)
        if channel is None:
            chan = f"<#{c['log']}>" if c["log"] else "Not set"
            return await send_panel(ctx, f"{em('logger')} AutoMod log channel: {chan}")
        c["log"] = channel.id
        await self.save(ctx.guild.id, c)
        await send_ok(ctx, f"AutoMod logs → {channel.mention}")

    @automod.group(name="whitelist", aliases=["wl", "ignore"], invoke_without_command=True, help="Whitelist channels/roles")
    @commands.has_permissions(manage_guild=True)
    async def am_wl(self, ctx):
        await self.wl_show(ctx)

    @am_wl.command(name="channel", help="Toggle a whitelisted channel")
    async def wl_channel(self, ctx, channel: discord.TextChannel):
        c = await self.cfg(ctx.guild.id)
        if channel.id in c["wl_channels"]:
            c["wl_channels"].remove(channel.id)
            msg = f"{channel.mention} removed from the whitelist."
        else:
            c["wl_channels"].append(channel.id)
            msg = f"{channel.mention} added to the whitelist."
        await self.save(ctx.guild.id, c)
        await send_ok(ctx, msg)

    @am_wl.command(name="role", help="Toggle a whitelisted role")
    async def wl_role(self, ctx, role: discord.Role):
        c = await self.cfg(ctx.guild.id)
        if role.id in c["wl_roles"]:
            c["wl_roles"].remove(role.id)
            msg = f"{role.mention} removed from the whitelist."
        else:
            c["wl_roles"].append(role.id)
            msg = f"{role.mention} added to the whitelist."
        await self.save(ctx.guild.id, c)
        await send_ok(ctx, msg)

    @am_wl.command(name="show", aliases=["list", "view"], help="Show whitelist")
    async def wl_show(self, ctx):
        c = await self.cfg(ctx.guild.id)
        items = [f"<#{i}>" for i in c["wl_channels"]] + [f"<@&{i}>" for i in c["wl_roles"]]
        await send_list(ctx, f"{em('automod')} AutoMod Whitelist", items, color=config.HELP_COLOR)

    @am_wl.command(name="reset", aliases=["clear"], help="Clear whitelist")
    async def wl_reset(self, ctx):
        c = await self.cfg(ctx.guild.id)
        c["wl_channels"], c["wl_roles"] = [], []
        await self.save(ctx.guild.id, c)
        await send_ok(ctx, "Whitelist clear.")

    @automod.group(name="blacklist", aliases=["bl", "words"], invoke_without_command=True, help="Blacklisted words")
    @commands.has_permissions(manage_guild=True)
    async def am_bl(self, ctx):
        await self.bl_list(ctx)

    @am_bl.command(name="add", help="Add blacklisted words")
    async def bl_add(self, ctx, *words: str):
        c = await self.cfg(ctx.guild.id)
        c["words"] = sorted(set(c["words"]) | {w.lower() for w in words})
        await self.save(ctx.guild.id, c)
        await send_ok(ctx, f"Added **{len(words)}** word(s). (Keep the `Blacklist Word` filter ON.)")

    @am_bl.command(name="remove", aliases=["del", "rm"], help="Remove blacklisted words")
    async def bl_remove(self, ctx, *words: str):
        c = await self.cfg(ctx.guild.id)
        c["words"] = [w for w in c["words"] if w not in {x.lower() for x in words}]
        await self.save(ctx.guild.id, c)
        await send_ok(ctx, "Words removed.")

    @am_bl.command(name="list", aliases=["show", "view"], help="Show blacklisted words")
    async def bl_list(self, ctx):
        c = await self.cfg(ctx.guild.id)
        await send_list(ctx, f"{em('automod')} Blacklisted Words", [f"||{w}||" for w in c["words"]], color=config.HELP_COLOR)


async def setup(bot):
    await bot.add_cog(AutoMod(bot))
