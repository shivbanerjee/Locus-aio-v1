"""Join To Create (VoiceMaster style): hub VC + interface panel with 14 buttons."""
import time

import discord
from discord import ui
from discord.ext import commands

import config
from emojis import em
from utils.checks import bot_guild_perms
from utils.v2 import Panel, AskModal, sep, td, footer, button, confirm, send_ok, send_err, send_panel, i_ok, i_err

B = discord.ButtonStyle
DEFAULT_NAME = "{user}'s VC"
# key: (label, emoji key, style)
BUTTONS = {
    "lock": ("Lock", "lock", B.secondary), "unlock": ("Unlock", "unlock", B.secondary),
    "hide": ("Hide", "hide", B.secondary), "unhide": ("Unhide", "unhide", B.secondary),
    "rename": ("Rename", "rename", B.primary), "limit": ("Limit", "limit", B.primary),
    "mute": ("Mute", "mute", B.secondary), "unmute": ("Unmute", "unmute", B.secondary),
    "deafen": ("Deafen", "deafen", B.secondary), "undeafen": ("Undeafen", "undeafen", B.secondary),
    "permit": ("Permit", "permit", B.success), "ban": ("Ban", "ban", B.danger),
    "transfer": ("Transfer", "transfer", B.primary), "claim": ("Claim", "claim", B.success),
}


async def temp_of(bot, member):
    vs = member.voice
    if not vs or not vs.channel:
        return None, None, "Join your temporary voice channel first."
    row = await bot.db.one("SELECT * FROM j2c_channels WHERE channel_id=?", vs.channel.id)
    if not row:
        return None, None, "This isn't a Join-To-Create voice channel."
    return vs.channel, row, None


async def _ow(ch, target=None, **kw):
    target = target or ch.guild.default_role
    o = ch.overwrites_for(target)
    for k, v in kw.items():
        setattr(o, k, v)
    await ch.set_permissions(target, overwrite=o)


async def claim_channel(bot, ch, member):
    await bot.db.run("UPDATE j2c_channels SET owner_id=? WHERE channel_id=?", member.id, ch.id)
    await ch.set_permissions(member, connect=True, view_channel=True, manage_channels=True, move_members=True)


def find_member(guild, text: str):
    t = text.strip().lstrip("<@!").rstrip(">")
    if t.isdigit():
        return guild.get_member(int(t))
    low = text.strip().lower()
    return discord.utils.find(lambda m: m.name.lower() == low or m.display_name.lower() == low, guild.members)


# ---------- modals ----------
TextModal = AskModal


# ---------- panel ----------
class PanelView(ui.LayoutView):
    def __init__(self, enabled: list[str] | None = None):
        super().__init__(timeout=None)
        keys = [k for k in BUTTONS if enabled is None or k in enabled]
        btns = [button(BUTTONS[k][0], em(BUTTONS[k][1]), BUTTONS[k][2], self.make_cb(k), f"locus:vm:{k}") for k in keys]
        rows = [ui.ActionRow(*btns[i:i + 5]) for i in range(0, len(btns), 5)]
        self.add_item(ui.Container(
            td(f"## {em('join2create')} VoiceMaster Interface"), td("Stay in your temporary voice channel and use the buttons to control it."),
            sep(), *rows, td(footer()), accent_colour=config.HELP_COLOR))

    async def _owned(self, interaction):
        ch, row, err = await temp_of(interaction.client, interaction.user)
        if err:
            await i_err(interaction, err)
            return None
        if row["owner_id"] != interaction.user.id and not interaction.user.guild_permissions.administrator:
            await i_err(interaction, "Only the VC owner can do this. (If the owner left, use **Claim**.)")
            return None
        return ch

    def make_cb(self, key):
        async def cb(interaction: discord.Interaction):
            if key == "claim":
                ch, row, err = await temp_of(interaction.client, interaction.user)
                if err:
                    return await i_err(interaction, err)
                owner = interaction.guild.get_member(row["owner_id"])
                if owner and owner in ch.members:
                    return await i_err(interaction, "The owner is still in the VC.")
                await claim_channel(interaction.client, ch, interaction.user)
                return await i_ok(interaction, "You are now the **owner** of this VC 👑")
            ch = await self._owned(interaction)
            if not ch:
                return
            simple = {"lock": ({"connect": False}, "VC **locked** 🔒"), "unlock": ({"connect": None}, "VC **unlocked** 🔓"),
                      "hide": ({"view_channel": False}, "VC **hidden** 🙈"), "unhide": ({"view_channel": None}, "VC **visible** 👁️")}
            if key in simple:
                await _ow(ch, **simple[key][0])
                return await i_ok(interaction, simple[key][1])
            if key == "rename":
                async def h(i, v):
                    await ch.edit(name=v[:90])
                    await i_ok(i, f"Renamed to **{v[:90]}**")
                return await interaction.response.send_modal(TextModal("Rename VC", "New name", h, required=True, max_length=90))
            if key == "limit":
                async def h(i, v):
                    if not v.isdigit() or int(v) > 99:
                        return await i_err(i, "Enter a number between 0 and 99.")
                    await ch.edit(user_limit=int(v))
                    await i_ok(i, f"Limit: **{v if int(v) else 'Unlimited'}**")
                return await interaction.response.send_modal(TextModal("User Limit", "Limit (0 = unlimited)", h, required=True, max_length=2))

            async def target_action(i, v):
                m = find_member(i.guild, v)
                if not m or m.bot and key == "transfer":
                    return await i_err(i, "Member not found (use their ID or username).")
                if key in ("mute", "unmute", "deafen", "undeafen"):
                    if m not in ch.members:
                        return await i_err(i, "That member isn't in your VC.")
                    await m.edit(**{"mute": key == "mute"} if "mute" in key else {"deafen": key == "deafen"})
                    return await i_ok(i, f"{m.mention} → `{key}`")
                if key == "permit":
                    await ch.set_permissions(m, connect=True, view_channel=True)
                    return await i_ok(i, f"{m.mention} permitted ✅")
                if key == "ban":
                    if m.id == ch.guild.owner_id or m.id == i.user.id:
                        return await i_err(i, "You can't ban this member.")
                    await ch.set_permissions(m, connect=False)
                    if m in ch.members:
                        await m.move_to(None)
                    return await i_ok(i, f"{m.mention} banned from VC ⛔")
                if key == "transfer":
                    if m not in ch.members:
                        return await i_err(i, "That member must be in your VC.")
                    await claim_channel(i.client, ch, m)
                    return await i_ok(i, f"Owner: {m.mention} 🔁")
            await interaction.response.send_modal(TextModal(f"{BUTTONS[key][0]} Member", "Member ID / username", target_action, required=True, max_length=40))
        return cb


class ButtonPicker(ui.LayoutView):
    """Lets you choose which buttons to show during setup."""

    def __init__(self, author_id, cog, current):
        super().__init__(timeout=120)
        self.author_id = author_id
        sel = ui.Select(placeholder="Select buttons to show", min_values=1, max_values=len(BUTTONS), options=[
            discord.SelectOption(label=v[0], value=k, default=k in current) for k, v in BUTTONS.items()])

        async def cb(i):
            vals = [k for k in BUTTONS if k in sel.values]
            cfg = await i.client.db.kget(i.guild.id, "vm", {})
            cfg["buttons"] = vals
            await i.client.db.kset(i.guild.id, "vm", cfg)
            ch = i.guild.get_channel(cfg.get("interface"))
            if ch:
                try:
                    await ch.purge(limit=10, check=lambda m: m.author.id == i.client.user.id)
                except discord.HTTPException:
                    pass
                await ch.send(view=PanelView(vals))
            await i.response.edit_message(view=Panel(f"{em('tick')} **{len(vals)}** buttons set. Panel sent to {ch.mention if ch else 'the interface channel'}.",
                                                     color=config.GREEN, timeout=None))
        sel.callback = cb
        self.add_item(ui.Container(td(f"## {em('join2create')} Select Buttons"), td("Choose the buttons you want on the interface."),
                                   ui.ActionRow(sel), accent_colour=config.HELP_COLOR))

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await i_err(interaction, "This isn't for you.")
            return False
        return True


class JoinToCreate(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cool: dict[int, float] = {}

    async def cog_load(self):
        self.bot.add_view(PanelView())

    async def cog_check(self, ctx):
        if not ctx.guild:
            raise commands.NoPrivateMessage()
        return True

    async def _remove(self, ch):
        await self.bot.db.run("DELETE FROM j2c_channels WHERE channel_id=?", ch.id)
        try:
            await ch.delete(reason="VoiceMaster: empty")
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_ready(self):
        for r in await self.bot.db.all("SELECT channel_id FROM j2c_channels"):
            ch = self.bot.get_channel(r["channel_id"])
            if ch is None:
                await self.bot.db.run("DELETE FROM j2c_channels WHERE channel_id=?", r["channel_id"])
            elif not ch.members:
                await self._remove(ch)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return
        if after.channel and after.channel != before.channel:
            cfg = await self.bot.db.kget(member.guild.id, "vm", {})
            if cfg.get("hub") == after.channel.id:
                if time.time() - self.cool.get(member.id, 0) < 3:
                    return await member.move_to(None)
                self.cool[member.id] = time.time()
                hub = after.channel
                name = (cfg.get("name") or DEFAULT_NAME).replace("{user}", member.display_name)[:90]
                try:
                    ch = await member.guild.create_voice_channel(
                        name, category=hub.category, user_limit=cfg.get("limit", 0),
                        bitrate=min(hub.bitrate, member.guild.bitrate_limit),
                        overwrites={member: discord.PermissionOverwrite(connect=True, view_channel=True, manage_channels=True, move_members=True)},
                        reason=f"VoiceMaster for {member}")
                    await self.bot.db.run("INSERT INTO j2c_channels VALUES(?,?,?)", ch.id, member.guild.id, member.id)
                    try:
                        await member.move_to(ch)
                    except discord.HTTPException as ex:
                        print(f"[VoiceMaster] could not move {member} ({ex.status}): {ex.text}")
                        await self._remove(ch)
                except discord.HTTPException as ex:
                    print(f"[VoiceMaster] could not create a channel in {member.guild} ({ex.status}): {ex.text}")
        if before.channel and before.channel != after.channel and not before.channel.members:
            if await self.bot.db.one("SELECT 1 FROM j2c_channels WHERE channel_id=?", before.channel.id):
                await self._remove(before.channel)

    # ---------- commands ----------
    @commands.group(name="voicemaster", aliases=["vm", "j2c", "jtc"], invoke_without_command=True, help="VoiceMaster status")
    @commands.has_permissions(manage_channels=True)
    async def voicemaster(self, ctx):
        p = ctx.clean_prefix
        await send_panel(ctx, f"## {em('join2create')} VoiceMaster", sep(),
                         f"`{p}vm setup` • `{p}vm buttons` • `{p}vm config` • `{p}vm reset`\n"
                         f"`{p}vm limit <n>` • `{p}vm name <template>`", footer(), color=config.HELP_COLOR)

    @voicemaster.command(name="setup", help="Create hub VC + interface channel")
    @commands.has_permissions(manage_channels=True)
    @bot_guild_perms(manage_channels=True, move_members=True)
    async def vm_setup(self, ctx):
        cfg = await self.bot.db.kget(ctx.guild.id, "vm", {})
        if cfg.get("hub") and ctx.guild.get_channel(cfg["hub"]):
            return await send_err(ctx, f"Already set up. Run `{ctx.clean_prefix}vm reset` first to set it up again.")
        cat = await ctx.guild.create_category("VoiceMaster")
        hub = await ctx.guild.create_voice_channel("➕ Join To Create", category=cat)
        ui_ch = await ctx.guild.create_text_channel("interface", category=cat, overwrites={
            ctx.guild.default_role: discord.PermissionOverwrite(send_messages=False)})
        cfg = {"hub": hub.id, "category": cat.id, "interface": ui_ch.id, "buttons": list(BUTTONS), "name": DEFAULT_NAME, "limit": 0}
        await self.bot.db.kset(ctx.guild.id, "vm", cfg)
        await ctx.send(view=ButtonPicker(ctx.author.id, self, cfg["buttons"]))
        await send_ok(ctx, f"Setup done: {hub.mention} • {ui_ch.mention}. Choose your buttons, or keep them all.")
        await ui_ch.send(view=PanelView(cfg["buttons"]))

    @voicemaster.command(name="buttons", help="Choose which buttons the interface shows")
    @commands.has_permissions(manage_channels=True)
    async def vm_buttons(self, ctx):
        cfg = await self.bot.db.kget(ctx.guild.id, "vm", {})
        if not cfg.get("hub"):
            return await send_err(ctx, f"Run `{ctx.clean_prefix}vm setup` first.")
        await ctx.send(view=ButtonPicker(ctx.author.id, self, cfg.get("buttons", list(BUTTONS))))

    @voicemaster.command(name="config", aliases=["settings"], help="Show VoiceMaster config")
    @commands.has_permissions(manage_channels=True)
    async def vm_config(self, ctx):
        cfg = await self.bot.db.kget(ctx.guild.id, "vm", {})
        if not cfg.get("hub"):
            return await send_err(ctx, "Not set up.")
        await send_panel(ctx, f"## {em('join2create')} VoiceMaster Config", sep(),
                         f"**Hub:** <#{cfg['hub']}>\n**Interface:** <#{cfg['interface']}>\n**Name:** `{cfg.get('name', DEFAULT_NAME)}`\n"
                         f"**Default limit:** `{cfg.get('limit') or 'Unlimited'}`\n**Buttons:** {', '.join(f'`{b}`' for b in cfg.get('buttons', []))}",
                         color=config.HELP_COLOR)

    @voicemaster.command(name="limit", help="Default user limit for new VCs")
    @commands.has_permissions(manage_channels=True)
    async def vm_limit(self, ctx, n: commands.Range[int, 0, 99]):
        cfg = await self.bot.db.kget(ctx.guild.id, "vm", {})
        cfg["limit"] = n
        await self.bot.db.kset(ctx.guild.id, "vm", cfg)
        await send_ok(ctx, f"Default limit: **{n or 'Unlimited'}**")

    @voicemaster.command(name="name", help="Name template. Use {user}")
    @commands.has_permissions(manage_channels=True)
    async def vm_name(self, ctx, *, template: str):
        cfg = await self.bot.db.kget(ctx.guild.id, "vm", {})
        cfg["name"] = template[:80]
        await self.bot.db.kset(ctx.guild.id, "vm", cfg)
        await send_ok(ctx, f"Template: `{template[:80]}`")

    @voicemaster.command(name="reset", aliases=["disable"], help="Remove VoiceMaster setup")
    @commands.has_permissions(manage_channels=True)
    async def vm_reset(self, ctx):
        cfg = await self.bot.db.kget(ctx.guild.id, "vm", {})
        if not cfg.get("hub"):
            return await send_err(ctx, "Not set up.")
        if not await confirm(ctx, "Delete the VoiceMaster channels and reset?"):
            return
        for cid in (cfg.get("hub"), cfg.get("interface"), cfg.get("category")):
            ch = ctx.guild.get_channel(cid) if cid else None
            if ch and not (isinstance(ch, discord.CategoryChannel) and ch.channels):
                try:
                    await ch.delete()
                except discord.HTTPException:
                    pass
        await self.bot.db.kdel(ctx.guild.id, "vm")
        await send_ok(ctx, "VoiceMaster has been reset.")


async def setup(bot):
    await bot.add_cog(JoinToCreate(bot))
