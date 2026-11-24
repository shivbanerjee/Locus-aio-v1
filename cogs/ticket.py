"""Ticket system: config panel + category dropdown + Lock/Unlock/Claim/Close + Reopen/Transcript/Delete."""
import asyncio
import io
import time

import discord
from discord import ui
from discord.ext import commands

import config
from emojis import em
from utils.v2 import Panel, AskModal, sep, td, footer, media, button, confirm, send_ok, send_err, send_panel, i_ok, i_err

B = discord.ButtonStyle
DEFAULT = {"title": "Support Tickets", "description": "Pick a category below to open a ticket. Staff will reply shortly.",
           "placeholder": "Select a category", "thumbnail": "", "image": "",
           "message": "Hello {user}, please describe your issue here. Staff will be with you shortly!", "max": 1,
           "log": None, "staff": [], "categories": [], "open_cat": None, "closed_cat": None}


async def get_cfg(bot, gid):
    return {**DEFAULT, **await bot.db.kget(gid, "ticket", {})}


async def put_cfg(bot, gid, c):
    await bot.db.kset(gid, "ticket", c)


def is_staff(member: discord.Member, cfg) -> bool:
    p = member.guild_permissions
    return p.administrator or p.manage_channels or any(r.id in cfg["staff"] for r in member.roles)


async def log_ticket(bot, guild, cfg, text):
    ch = guild.get_channel(cfg["log"]) if cfg["log"] else None
    if ch:
        try:
            await ch.send(view=Panel(f"### {em('ticket')} Ticket Log", text, color=config.BLURPLE, timeout=None),
                          allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            pass


async def make_transcript(channel: discord.TextChannel) -> discord.File:
    lines = [f"Transcript of #{channel.name}", "=" * 40]
    async for m in channel.history(limit=None, oldest_first=True):
        att = " ".join(a.url for a in m.attachments)
        lines.append(f"[{m.created_at:%Y-%m-%d %H:%M}] {m.author} ({m.author.id}): {m.content} {att}".strip())
    return discord.File(io.BytesIO("\n".join(lines).encode("utf-8")), filename=f"transcript-{channel.name}.txt")


# ================= ticket flow =================
async def open_ticket(interaction: discord.Interaction, category: str | None):
    bot, g, user = interaction.client, interaction.guild, interaction.user
    cfg = await get_cfg(bot, g.id)
    n_open = await bot.db.val("SELECT COUNT(*) FROM tickets WHERE guild_id=? AND owner_id=? AND status='open'", g.id, user.id)
    if n_open >= cfg["max"]:
        return await i_err(interaction, f"You already have **{n_open}** open ticket(s) (max {cfg['max']}).")
    await interaction.response.defer(ephemeral=True)
    cat = g.get_channel(cfg["open_cat"]) if cfg["open_cat"] else None
    if not cat:
        cat = await g.create_category("Tickets", overwrites={g.default_role: discord.PermissionOverwrite(view_channel=False)})
        cfg["open_cat"] = cat.id
    n = (await bot.db.kget(g.id, "ticket_n", 0)) + 1
    await bot.db.kset(g.id, "ticket_n", n)
    ow = {
        g.default_role: discord.PermissionOverwrite(view_channel=False),
        user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, read_message_history=True),
        g.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, manage_messages=True),
    }
    pings = []
    for rid in cfg["staff"]:
        if r := g.get_role(rid):
            ow[r] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_messages=True)
            pings.append(r.mention)
    ch = await g.create_text_channel(f"ticket-{n:04d}", category=cat, overwrites=ow, topic=f"{user.id} | {category or 'General'}")
    await bot.db.run("INSERT INTO tickets(channel_id,guild_id,owner_id,category,status,number,created) VALUES(?,?,?,?,?,?,?)",
                     ch.id, g.id, user.id, category or "General", "open", n, int(time.time()))
    await put_cfg(bot, g.id, cfg)
    msg = cfg["message"].replace("{user}", user.mention)
    await ch.send(view=Panel(f"## {em('ticket')} Ticket #{n:04d} • {category or 'General'}", msg, " ".join(pings) or "-# Staff notified",
                             sep(), controls_row(), color=config.GREEN, timeout=None),
                  allowed_mentions=discord.AllowedMentions(users=True, roles=True))
    await log_ticket(bot, g, cfg, f"**Opened** {ch.mention} by {user.mention} • `{category or 'General'}`")
    await i_ok(interaction, f"Ticket created: {ch.mention}")


async def _ticket_ctx(interaction):
    bot = interaction.client
    row = await bot.db.one("SELECT * FROM tickets WHERE channel_id=?", interaction.channel.id)
    if not row:
        await i_err(interaction, "This isn't a ticket channel.")
        return None, None
    return row, await get_cfg(bot, interaction.guild.id)


async def t_lock(interaction, lock: bool):
    row, cfg = await _ticket_ctx(interaction)
    if not row:
        return
    if not is_staff(interaction.user, cfg):
        return await i_err(interaction, "Only staff can do this.")
    owner = interaction.guild.get_member(row["owner_id"])
    if owner:
        await interaction.channel.set_permissions(owner, view_channel=True, send_messages=not lock, read_message_history=True)
    await i_ok(interaction, "Ticket **locked** 🔒" if lock else "Ticket **unlocked** 🔓", ephemeral=False)


async def t_claim(interaction):
    row, cfg = await _ticket_ctx(interaction)
    if not row:
        return
    if not is_staff(interaction.user, cfg):
        return await i_err(interaction, "Only staff can claim tickets.")
    if row["claimed_by"]:
        return await i_err(interaction, f"Already claimed by <@{row['claimed_by']}>.")
    await interaction.client.db.run("UPDATE tickets SET claimed_by=? WHERE channel_id=?", interaction.user.id, interaction.channel.id)
    await interaction.response.send_message(view=Panel(f"👑 {interaction.user.mention} **claimed** this ticket.", color=config.GREEN, timeout=None),
                                            allowed_mentions=discord.AllowedMentions.none())


async def t_close(interaction):
    row, cfg = await _ticket_ctx(interaction)
    if not row:
        return
    if interaction.user.id != row["owner_id"] and not is_staff(interaction.user, cfg):
        return await i_err(interaction, "Only the ticket owner or staff can close this ticket.")
    if row["status"] == "closed":
        return await i_err(interaction, "This ticket is already closed.")
    g = interaction.guild
    await interaction.response.defer()
    await interaction.client.db.run("UPDATE tickets SET status='closed' WHERE channel_id=?", interaction.channel.id)
    owner = g.get_member(row["owner_id"])
    if owner:
        await interaction.channel.set_permissions(owner, view_channel=True, send_messages=False, read_message_history=True)
    cc = g.get_channel(cfg["closed_cat"]) if cfg["closed_cat"] else None
    if not cc:
        cc = await g.create_category("Closed Tickets", overwrites={g.default_role: discord.PermissionOverwrite(view_channel=False)})
        cfg["closed_cat"] = cc.id
        await put_cfg(interaction.client, g.id, cfg)
    try:
        await interaction.channel.edit(category=cc, sync_permissions=False)
    except discord.HTTPException:
        pass
    await interaction.followup.send(view=Panel(f"## 🔒 Ticket Closed", f"Closed by {interaction.user.mention}.", sep(), closed_row(),
                                               color=config.RED, timeout=None), allowed_mentions=discord.AllowedMentions.none())
    await log_ticket(interaction.client, g, cfg, f"**Closed** `#{interaction.channel.name}` by {interaction.user.mention}")


async def t_reopen(interaction):
    row, cfg = await _ticket_ctx(interaction)
    if not row:
        return
    if not is_staff(interaction.user, cfg):
        return await i_err(interaction, "Only staff can reopen tickets.")
    g = interaction.guild
    await interaction.client.db.run("UPDATE tickets SET status='open' WHERE channel_id=?", interaction.channel.id)
    owner = g.get_member(row["owner_id"])
    if owner:
        await interaction.channel.set_permissions(owner, view_channel=True, send_messages=True, read_message_history=True)
    oc = g.get_channel(cfg["open_cat"]) if cfg["open_cat"] else None
    if oc:
        try:
            await interaction.channel.edit(category=oc, sync_permissions=False)
        except discord.HTTPException:
            pass
    await interaction.response.send_message(view=Panel(f"🔓 Ticket **reopened** by {interaction.user.mention}.", color=config.GREEN, timeout=None),
                                            allowed_mentions=discord.AllowedMentions.none())


async def t_transcript(interaction):
    row, cfg = await _ticket_ctx(interaction)
    if not row:
        return
    if not is_staff(interaction.user, cfg):
        return await i_err(interaction, "Only staff can get the transcript.")
    await interaction.response.defer(ephemeral=True)
    f = await make_transcript(interaction.channel)
    logch = interaction.guild.get_channel(cfg["log"]) if cfg["log"] else None
    await (logch or interaction.channel).send(content=f"📄 Transcript of `#{interaction.channel.name}`", file=f)
    await interaction.followup.send("Transcript sent ✅", ephemeral=True)


async def t_delete(interaction):
    row, cfg = await _ticket_ctx(interaction)
    if not row:
        return
    if not is_staff(interaction.user, cfg):
        return await i_err(interaction, "Only staff can delete tickets.")
    await interaction.response.send_message(view=Panel("🗑️ This ticket will be deleted in **5 seconds** (the transcript goes to the log channel).", color=config.RED, timeout=None))
    logch = interaction.guild.get_channel(cfg["log"]) if cfg["log"] else None
    if logch:
        await logch.send(content=f"📄 Transcript of `#{interaction.channel.name}` (deleted by {interaction.user})", file=await make_transcript(interaction.channel))
    await asyncio.sleep(5)
    await interaction.client.db.run("DELETE FROM tickets WHERE channel_id=?", interaction.channel.id)
    try:
        await interaction.channel.delete(reason=f"Ticket deleted by {interaction.user}")
    except discord.HTTPException:
        pass


def controls_row() -> ui.ActionRow:
    return ui.ActionRow(
        button("Lock", em("lock"), B.secondary, lambda i: t_lock(i, True), "locus:t:lock"),
        button("Unlock", em("unlock"), B.secondary, lambda i: t_lock(i, False), "locus:t:unlock"),
        button("Claim", em("claim"), B.success, t_claim, "locus:t:claim"),
        button("Close", "🔒", B.danger, t_close, "locus:t:close"))


def closed_row() -> ui.ActionRow:
    return ui.ActionRow(
        button("Reopen", "🔓", B.success, t_reopen, "locus:t:reopen"),
        button("Transcript", "📄", B.secondary, t_transcript, "locus:t:transcript"),
        button("Delete", em("delete"), B.danger, t_delete, "locus:t:delete"))


class PersistentHolder(ui.LayoutView):
    """Only used to register button/select callbacks (add_view)."""

    def __init__(self):
        super().__init__(timeout=None)
        sel = ui.Select(custom_id="locus:t:cat", options=[discord.SelectOption(label="x", value="x")])

        async def on_cat(i):
            await open_ticket(i, sel.values[0])
        sel.callback = on_cat
        self.add_item(ui.Container(controls_row(), closed_row(), ui.ActionRow(sel),
                                   ui.ActionRow(button("Open Ticket", em("ticket"), B.primary, lambda i: open_ticket(i, None), "locus:t:open"))))


def public_panel(cfg, bot_user) -> ui.LayoutView:
    v = ui.LayoutView(timeout=None)
    head = [td(f"## {cfg['title']}"), td(cfg["description"])]
    top = ui.Section(*head, accessory=ui.Thumbnail(cfg["thumbnail"])) if cfg["thumbnail"] else None
    items = [top] if top else head
    if cfg["image"]:
        items.append(media(cfg["image"]))
    if cfg["categories"]:
        sel = ui.Select(custom_id="locus:t:cat", placeholder=cfg["placeholder"][:100], options=[
            discord.SelectOption(label=c["name"][:100], value=c["name"][:100], description=(c.get("desc") or None),
                                 emoji=c.get("emoji") or None) for c in cfg["categories"][:25]])

        async def on_cat(i):
            await open_ticket(i, sel.values[0])
        sel.callback = on_cat
        items.append(ui.ActionRow(sel))
    else:
        items.append(ui.ActionRow(button("Open Ticket", em("ticket"), B.primary, lambda i: open_ticket(i, None), "locus:t:open")))
    items.append(td(footer()))
    v.add_item(ui.Container(*items, accent_colour=config.HELP_COLOR))
    return v


# ================= config panel =================
async def config_view(bot, author_id, guild) -> Panel:
    cfg = await get_cfg(bot, guild.id)
    staff = ", ".join(f"<@&{r}>" for r in cfg["staff"]) or "None"
    cats = ", ".join(f"{c.get('emoji', '')} {c['name']}" for c in cfg["categories"]) or "None"
    log = f"<#{cfg['log']}>" if cfg["log"] else "Not set"

    def edit_btn(label, key, paragraph=False, numeric=False):
        async def cb(i):
            async def h(inter, text):
                c = await get_cfg(inter.client, inter.guild.id)
                if numeric:
                    if not text.isdigit() or not 1 <= int(text) <= 10:
                        return await i_err(inter, "Enter a number between 1 and 10.")
                    text = int(text)
                c[key] = text
                await put_cfg(inter.client, inter.guild.id, c)
                await inter.response.edit_message(view=await config_view(inter.client, inter.user.id, inter.guild))
            c = await get_cfg(i.client, i.guild.id)
            await i.response.send_modal(AskModal(f"Edit {label}", label, h, default=str(c[key]), paragraph=paragraph, max_length=1000 if paragraph else 256))
        return button(label, None, B.secondary, cb)

    roles = ui.RoleSelect(placeholder="Staff roles", min_values=0, max_values=10)
    logsel = ui.ChannelSelect(placeholder="Log channel", channel_types=[discord.ChannelType.text], min_values=0, max_values=1)

    async def on_roles(i):
        c = await get_cfg(i.client, i.guild.id)
        c["staff"] = [r.id for r in roles.values]
        await put_cfg(i.client, i.guild.id, c)
        await i.response.edit_message(view=await config_view(i.client, i.user.id, i.guild))

    async def on_log(i):
        c = await get_cfg(i.client, i.guild.id)
        c["log"] = logsel.values[0].id if logsel.values else None
        await put_cfg(i.client, i.guild.id, c)
        await i.response.edit_message(view=await config_view(i.client, i.user.id, i.guild))

    async def cats_cb(i):
        await i.response.edit_message(view=await cats_view(i.client, i.user.id, i.guild))

    async def send_cb(i):
        s = ui.ChannelSelect(placeholder="Which channel should I send the panel to?", channel_types=[discord.ChannelType.text])

        async def pick(inter):
            ch = inter.guild.get_channel(s.values[0].id)
            c = await get_cfg(inter.client, inter.guild.id)
            try:
                await ch.send(view=public_panel(c, inter.client.user))
            except discord.HTTPException:
                return await i_err(inter, "I couldn't send it to that channel (missing permission?).")
            await inter.response.edit_message(view=Panel(f"{em('tick')} Panel sent to {ch.mention}.", color=config.GREEN, timeout=None))
        s.callback = pick
        await i.response.send_message(view=Panel("Choose a channel:", ui.ActionRow(s), timeout=120, author_id=i.user.id), ephemeral=True)

    roles.callback, logsel.callback = on_roles, on_log
    return Panel(
        f"## {em('ticket')} Ticket Setup",
        f"**Title:** {cfg['title']}\n**Description:** {cfg['description'][:120]}\n**Placeholder:** {cfg['placeholder']}\n"
        f"**Thumbnail:** {cfg['thumbnail'] or '—'} • **Image:** {cfg['image'] or '—'}\n**Ticket message:** {cfg['message'][:120]}\n"
        f"**Max tickets / user:** `{cfg['max']}` • **Log:** {log}\n**Staff roles:** {staff}\n**Categories:** {cats}",
        sep(),
        ui.ActionRow(edit_btn("Title", "title"), edit_btn("Description", "description", True), edit_btn("Placeholder", "placeholder")),
        ui.ActionRow(edit_btn("Thumbnail", "thumbnail"), edit_btn("Image", "image"), edit_btn("Ticket Message", "message", True)),
        ui.ActionRow(edit_btn("Max Tickets", "max", numeric=True), button("Categories", None, B.primary, cats_cb),
                     button("Send Panel", em("ticket"), B.success, send_cb)),
        ui.ActionRow(roles), ui.ActionRow(logsel), footer(),
        color=config.HELP_COLOR, timeout=300, author_id=author_id)


async def cats_view(bot, author_id, guild) -> Panel:
    cfg = await get_cfg(bot, guild.id)

    async def add_cb(i):
        async def h(inter, text):
            parts = [p.strip() for p in text.split("|")]
            c = await get_cfg(inter.client, inter.guild.id)
            if len(c["categories"]) >= 25 or not parts[0]:
                return await i_err(inter, "A name is required (max 25 categories).")
            c["categories"].append({"name": parts[0][:100], "emoji": parts[1] if len(parts) > 1 else "", "desc": parts[2][:100] if len(parts) > 2 else ""})
            await put_cfg(inter.client, inter.guild.id, c)
            await inter.response.edit_message(view=await cats_view(inter.client, inter.user.id, inter.guild))
        await i.response.send_modal(AskModal("Add Category", "Name | emoji | description", h, required=True, max_length=250, placeholder="Support | 🛠️ | General help"))

    async def back_cb(i):
        await i.response.edit_message(view=await config_view(i.client, i.user.id, i.guild))

    items = [td(f"## {em('ticket')} Ticket Categories"), td("\n".join(f"**{n}.** {c.get('emoji', '')} {c['name']} — {c.get('desc', '')}" for n, c in enumerate(cfg["categories"], 1)) or "No categories — the ticket panel will show a simple **Open Ticket** button."),
             sep()]
    if cfg["categories"]:
        dsel = ui.Select(placeholder="Delete a category", options=[discord.SelectOption(label=c["name"][:100], value=str(n)) for n, c in enumerate(cfg["categories"])])

        async def del_cb(i):
            c = await get_cfg(i.client, i.guild.id)
            c["categories"].pop(int(dsel.values[0]))
            await put_cfg(i.client, i.guild.id, c)
            await i.response.edit_message(view=await cats_view(i.client, i.user.id, i.guild))
        dsel.callback = del_cb
        items.append(ui.ActionRow(dsel))
    items.append(ui.ActionRow(button("Add Category", None, B.success, add_cb), button("Back", None, B.secondary, back_cb)))
    return Panel(*items, color=config.HELP_COLOR, timeout=300, author_id=author_id)


class Ticket(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(PersistentHolder())

    async def cog_check(self, ctx):
        if not ctx.guild:
            raise commands.NoPrivateMessage()
        return True

    @commands.hybrid_command(name="ticket", aliases=["tickets"], help="Open the ticket setup panel", description="Open the ticket setup panel")
    @commands.has_permissions(administrator=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def ticket(self, ctx):
        await ctx.send(view=await config_view(self.bot, ctx.author.id, ctx.guild))

    async def _row(self, ctx):
        row = await self.bot.db.one("SELECT * FROM tickets WHERE channel_id=?", ctx.channel.id)
        if not row:
            await send_err(ctx, "This command only works inside a ticket channel.")
        return row

    @commands.command(name="tclose", aliases=["closeticket"], help="Close this ticket")
    async def tclose(self, ctx):
        row = await self._row(ctx)
        if not row:
            return
        cfg = await get_cfg(self.bot, ctx.guild.id)
        if ctx.author.id != row["owner_id"] and not is_staff(ctx.author, cfg):
            return await send_err(ctx, "Only the owner or staff can close this ticket.")
        await self.bot.db.run("UPDATE tickets SET status='closed' WHERE channel_id=?", ctx.channel.id)
        owner = ctx.guild.get_member(row["owner_id"])
        if owner:
            await ctx.channel.set_permissions(owner, view_channel=True, send_messages=False, read_message_history=True)
        await ctx.send(view=Panel("## 🔒 Ticket Closed", f"Closed by {ctx.author.mention}.", sep(), closed_row(), color=config.RED, timeout=None),
                       allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="tdelete", aliases=["deleteticket"], help="Delete this ticket (staff)")
    async def tdelete(self, ctx):
        row = await self._row(ctx)
        if not row:
            return
        cfg = await get_cfg(self.bot, ctx.guild.id)
        if not is_staff(ctx.author, cfg):
            return await send_err(ctx, "Only staff can delete tickets.")
        if not await confirm(ctx, "Delete this ticket?"):
            return
        logch = ctx.guild.get_channel(cfg["log"]) if cfg["log"] else None
        if logch:
            await logch.send(content=f"📄 Transcript of `#{ctx.channel.name}`", file=await make_transcript(ctx.channel))
        await self.bot.db.run("DELETE FROM tickets WHERE channel_id=?", ctx.channel.id)
        await ctx.channel.delete(reason=f"Ticket deleted by {ctx.author}")

    @commands.command(name="tadd", help="Add a member to this ticket")
    async def tadd(self, ctx, member: discord.Member):
        if await self._row(ctx):
            if not is_staff(ctx.author, await get_cfg(self.bot, ctx.guild.id)):
                return await send_err(ctx, "Only staff.")
            await ctx.channel.set_permissions(member, view_channel=True, send_messages=True, read_message_history=True)
            await send_ok(ctx, f"{member.mention} was added.")

    @commands.command(name="tremove", help="Remove a member from this ticket")
    async def tremove(self, ctx, member: discord.Member):
        if await self._row(ctx):
            if not is_staff(ctx.author, await get_cfg(self.bot, ctx.guild.id)):
                return await send_err(ctx, "Only staff.")
            await ctx.channel.set_permissions(member, overwrite=None)
            await send_ok(ctx, f"{member.mention} was removed.")

    @commands.command(name="ticketsync", aliases=["tsync"], help="Clean DB entries of deleted ticket channels")
    @commands.has_permissions(administrator=True)
    async def ticketsync(self, ctx):
        rows = await self.bot.db.all("SELECT channel_id FROM tickets WHERE guild_id=?", ctx.guild.id)
        gone = [r["channel_id"] for r in rows if not ctx.guild.get_channel(r["channel_id"])]
        for cid in gone:
            await self.bot.db.run("DELETE FROM tickets WHERE channel_id=?", cid)
        await send_ok(ctx, f"Sync done: removed **{len(gone)}** stale tickets, **{len(rows) - len(gone)}** active.")


async def setup(bot):
    await bot.add_cog(Ticket(bot))
