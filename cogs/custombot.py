"""Custom Bot: change the bot's name / avatar / banner / bio / nameplate for this server only
(Discord per-guild bot profile: PATCH /guilds/{id}/members/@me)."""
import asyncio
import base64

import aiohttp
import discord
from discord import ui
from discord.ext import commands
from discord.http import Route

import config
from emojis import em
from utils.v2 import Panel, AskModal, sep, td, footer, button, send_ok, send_err, send_panel, i_ok, i_err

B = discord.ButtonStyle
ALLOWED = ("image/png", "image/jpeg", "image/gif", "image/webp")
# Discord display-name style IDs (API values)
FONTS = {"Default": 11, "Sans": 1, "Playful": 2, "Typewriter": 3, "Handwritten": 4, "Cursive": 5, "Serif": 6,
         "Chunky": 7, "Retro": 8, "Fancy": 9, "Condensed": 10}
EFFECTS = {"Solid": (1, 1), "Gradient": (2, 2), "Neon": (3, 1), "Toon": (4, 1), "Pop": (5, 1), "Glow": (6, 1)}  # id, colours needed
COLORS = {"Red": 0xE74C3C, "Orange": 0xE67E22, "Yellow": 0xF1C40F, "Green": 0x2ECC71, "Teal": 0x1ABC9C, "Blue": 0x3498DB,
          "Purple": 0x9B59B6, "Pink": 0xFF69B4, "White": 0xFFFFFF}


def has_cb_perm():
    async def pred(ctx):
        if not ctx.guild:
            raise commands.NoPrivateMessage()
        if ctx.author.guild_permissions.administrator or ctx.author.id in config.OWNER_IDS:
            return True
        raise commands.CheckFailure("**Administrator** permission is required for Custom Bot.")
    return commands.check(pred)


class CustomBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ---------- api ----------
    async def patch(self, guild_id: int, **payload):
        route = Route("PATCH", "/guilds/{guild_id}/members/@me", guild_id=guild_id)
        return await self.bot.http.request(route, json=payload, reason="Custom bot profile")

    async def _image(self, ctx, url):
        try:
            if ctx.message.attachments:
                a = ctx.message.attachments[0]
                data, ctype = await a.read(), (a.content_type or "").split(";")[0]
            elif url:
                async with aiohttp.ClientSession() as s, s.get(url) as r:
                    data, ctype = await r.read(), r.headers.get("Content-Type", "").split(";")[0]
            else:
                await send_err(ctx, "Attach an image or provide a URL.")
                return None
        except Exception:
            await send_err(ctx, "Couldn't download the image.")
            return None
        if ctype not in ALLOWED or len(data) > 10 * 1024 * 1024:
            await send_err(ctx, "Only png/jpg/gif/webp up to 10MB.")
            return None
        return f"data:{ctype};base64,{base64.b64encode(data).decode()}"

    async def _try(self, ctx, ok_text, **payload):
        try:
            await self.patch(ctx.guild.id, **payload)
            await send_ok(ctx, ok_text)
        except discord.HTTPException as ex:
            await send_err(ctx, f"Discord rejected it: `{ex.text or ex.status}`")

    async def _wait_image(self, ctx, prompt):
        await ctx.channel.send(view=Panel(prompt, timeout=None))
        try:
            m = await self.bot.wait_for("message", timeout=60, check=lambda x: x.author.id == ctx.author.id and x.channel.id == ctx.channel.id)
        except asyncio.TimeoutError:
            await send_err(ctx, "Timed out.")
            return None
        ctx.message = m
        return await self._image(ctx, m.content.strip() or None)

    # ---------- panel ----------
    def panel(self, ctx_user_id, guild) -> Panel:
        me = guild.me

        async def name_cb(i):
            async def h(inter, text):
                try:
                    await self.patch(inter.guild.id, nick=text[:32] or None)
                    await i_ok(inter, "Name updated.")
                except discord.HTTPException as ex:
                    await i_err(inter, f"`{ex.text or ex.status}`")
            await i.response.send_modal(AskModal("Bot Name", "Name (empty = reset)", h, default=i.guild.me.nick or "", max_length=32))

        async def bio_cb(i):
            async def h(inter, text):
                try:
                    await self.patch(inter.guild.id, bio=text[:190] or None)
                    await i_ok(inter, "Bio updated.")
                except discord.HTTPException as ex:
                    await i_err(inter, f"`{ex.text or ex.status}`")
            await i.response.send_modal(AskModal("Bot Bio", "Bio (empty = reset)", h, paragraph=True, max_length=190))

        async def img_cb(i, key):
            await i.response.send_message(f"Within **60 seconds**, send the {key} image as an attachment (or a URL).", ephemeral=True)

            class _C:
                guild, author, channel = i.guild, i.user, i.channel
                message = None

                async def send(self, *a, **kw):
                    return await i.channel.send(*a, **kw)
            c = _C()
            img = await self._wait_image(c, f"{i.user.mention} send the image…")
            if img:
                try:
                    await self.patch(i.guild.id, **{key: img})
                    await i.followup.send(f"{key} updated ✅", ephemeral=True)
                except discord.HTTPException as ex:
                    await i.followup.send(f"Reject: `{ex.text or ex.status}`", ephemeral=True)

        async def reset_cb(i):
            try:
                await self.patch(i.guild.id, nick=None, avatar=None, banner=None, bio=None,
                                 display_name_font_id=None, display_name_effect_id=None, display_name_colors=None)
                await i_ok(i, "Server profile reset.")
            except discord.HTTPException as ex:
                await i_err(i, f"`{ex.text or ex.status}`")

        async def np_cb(i):
            await i.response.send_message(view=NameplateView(self, i.user.id, i.guild.id, False), ephemeral=True)

        async def close_cb(i):
            await i.response.defer()
            await i.delete_original_response()

        head = ui.Section(td(f"## {em('custombot')} Custom Bot"),
                          td(f"**Name here:** {me.display_name}\n**Server-only profile** — other servers keep the original profile."),
                          accessory=ui.Thumbnail(me.display_avatar.url))
        return Panel(
            head, sep(),
            ui.ActionRow(button("Name", None, B.primary, name_cb), button("Avatar", None, B.primary, lambda i: img_cb(i, "avatar")),
                         button("Banner", None, B.primary, lambda i: img_cb(i, "banner")), button("Bio", None, B.primary, bio_cb)),
            ui.ActionRow(button("Nameplate", None, B.success, np_cb), button("Reset All", None, B.danger, reset_cb), button("Close", None, B.secondary, close_cb)),
            footer(), color=config.HELP_COLOR, timeout=300, author_id=ctx_user_id)

    # ---------- commands ----------
    @commands.command(name="custombot", aliases=["cb", "customize"], help="Customize the bot profile for this server")
    @has_cb_perm()
    async def custombot(self, ctx):
        await ctx.send(view=self.panel(ctx.author.id, ctx.guild))

    @commands.command(name="bbio", help="Set the bot bio in this server (none = reset)")
    @has_cb_perm()
    async def bbio(self, ctx, *, text: str):
        await self._try(ctx, "Bio updated.", bio=None if text.lower() == "none" else text[:190])

    @commands.command(name="bpfp", aliases=["bavatar"], help="Set bot avatar: attach / URL (none = reset)")
    @has_cb_perm()
    async def bpfp(self, ctx, url: str = None):
        if url and url.lower() == "none":
            return await self._try(ctx, "Avatar reset.", avatar=None)
        if img := await self._image(ctx, url):
            await self._try(ctx, "Server avatar updated.", avatar=img)

    @commands.command(name="bbanner", help="Set bot banner: attach / URL (none = reset)")
    @has_cb_perm()
    async def bbanner(self, ctx, url: str = None):
        if url and url.lower() == "none":
            return await self._try(ctx, "Banner reset.", banner=None)
        if img := await self._image(ctx, url):
            await self._try(ctx, "Server banner updated.", banner=img)

    @commands.command(name="bnameplate", aliases=["bstyle"], help="Design the bot's display-name style (font/effect/colours)")
    @has_cb_perm()
    async def bnameplate(self, ctx):
        await ctx.send(view=NameplateView(self, ctx.author.id, ctx.guild.id, False))

    @commands.command(name="gnameplate", aliases=["gstyle"], help="(Owner) default nameplate for all servers")
    @commands.is_owner()
    async def gnameplate(self, ctx):
        await ctx.send(view=NameplateView(self, ctx.author.id, ctx.guild.id, True))


class NameplateView(ui.LayoutView):
    def __init__(self, cog, author_id, guild_id, global_mode: bool):
        super().__init__(timeout=180)
        self.cog, self.author_id, self.guild_id, self.global_mode = cog, author_id, guild_id, global_mode
        self.font, self.effect, self.colors = "Default", "Solid", [COLORS["Blue"]]
        self._build()

    def _build(self):
        self.clear_items()
        need = EFFECTS[self.effect][1]
        fsel = ui.Select(placeholder=f"Font: {self.font}", options=[discord.SelectOption(label=k, value=k, default=k == self.font) for k in FONTS])
        esel = ui.Select(placeholder=f"Effect: {self.effect}", options=[discord.SelectOption(label=k, value=k, default=k == self.effect) for k in EFFECTS])
        csel = ui.Select(placeholder=f"Colour (choose {need})", min_values=need, max_values=need,
                         options=[discord.SelectOption(label=k, value=k) for k in COLORS])

        async def on_f(i):
            self.font = fsel.values[0]
            self._build()
            await i.response.edit_message(view=self)

        async def on_e(i):
            self.effect = esel.values[0]
            self.colors = self.colors[:EFFECTS[self.effect][1]] or [COLORS["Blue"]]
            while len(self.colors) < EFFECTS[self.effect][1]:
                self.colors.append(COLORS["Pink"])
            self._build()
            await i.response.edit_message(view=self)

        async def on_c(i):
            self.colors = [COLORS[v] for v in csel.values]
            self._build()
            await i.response.edit_message(view=self)

        async def hex_cb(i):
            async def h(inter, text):
                try:
                    cols = [int(x.strip().lstrip("#"), 16) for x in text.split(",") if x.strip()]
                except ValueError:
                    return await i_err(inter, "Format: `#ff0000` or `#ff0000,#00ff00`")
                if len(cols) != EFFECTS[self.effect][1]:
                    return await i_err(inter, f"This effect needs **{EFFECTS[self.effect][1]}** colour(s).")
                self.colors = cols
                self._build()
                await inter.response.edit_message(view=self)
            await i.response.send_modal(AskModal("Custom Hex", "Hex colour(s)", h, required=True, max_length=40, placeholder="#ff0000,#00ff00"))

        async def save_cb(i):
            payload = {"display_name_font_id": FONTS[self.font], "display_name_effect_id": EFFECTS[self.effect][0],
                       "display_name_colors": self.colors}
            targets = [g.id for g in self.cog.bot.guilds] if self.global_mode else [self.guild_id]
            await i.response.defer(ephemeral=True)
            ok = 0
            for gid in targets:
                try:
                    await self.cog.patch(gid, **payload)
                    ok += 1
                except discord.HTTPException:
                    pass
                if self.global_mode:
                    await asyncio.sleep(0.6)
            await i.followup.send(f"Nameplate applied in **{ok}/{len(targets)}** server(s) ✅", ephemeral=True)

        async def reset_cb(i):
            try:
                await self.cog.patch(self.guild_id, display_name_font_id=None, display_name_effect_id=None, display_name_colors=None)
                await i_ok(i, "Nameplate reset.")
            except discord.HTTPException as ex:
                await i_err(i, f"`{ex.text or ex.status}`")

        fsel.callback, esel.callback, csel.callback = on_f, on_e, on_c
        preview = ", ".join(f"`#{c:06x}`" for c in self.colors)
        self.add_item(ui.Container(
            td(f"## {em('custombot')} Nameplate {'(Global)' if self.global_mode else ''}"),
            td(f"**Font:** {self.font} • **Effect:** {self.effect} • **Colours:** {preview}"), sep(),
            ui.ActionRow(fsel), ui.ActionRow(esel), ui.ActionRow(csel),
            ui.ActionRow(button("Custom Hex", None, B.secondary, hex_cb), button("Save", None, B.success, save_cb), button("Reset", None, B.danger, reset_cb)),
            accent_colour=config.HELP_COLOR))

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await i_err(interaction, "This isn't for you.")
            return False
        return True


async def setup(bot):
    await bot.add_cog(CustomBot(bot))
