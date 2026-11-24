"""Components V2 helpers (discord.py >= 2.6)."""
import discord
from discord import ui
import config
from emojis import em

NO_MENTIONS = discord.AllowedMentions.none()


def td(text: str) -> ui.TextDisplay:
    return ui.TextDisplay(text)


def sep(large: bool = False) -> ui.Separator:
    return ui.Separator(
        visible=True,
        spacing=discord.SeparatorSpacing.large if large else discord.SeparatorSpacing.small,
    )


def media(url: str):
    """Shows a large image (MediaGallery); falls back to a plain link."""
    try:
        return ui.MediaGallery(discord.MediaGalleryItem(url))
    except Exception:
        return ui.TextDisplay(url)


def footer() -> str:
    return f"-# Developed with 💖 By {config.DEVELOPER}"


def button(label=None, emoji=None, style=discord.ButtonStyle.secondary, callback=None, custom_id=None, url=None):
    b = ui.Button(label=label, emoji=emoji, style=style, custom_id=custom_id, url=url) if url is None \
        else ui.Button(label=label, emoji=emoji, url=url)
    if callback:
        b.callback = callback
    return b


class Panel(ui.LayoutView):
    """A single-Container V2 message. str items become TextDisplay automatically."""

    def __init__(self, *items, color: int = config.INFO_COLOR, timeout=180, author_id: int | None = None):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        children = [ui.TextDisplay(i) if isinstance(i, str) else i for i in items]
        self.add_item(ui.Container(*children, accent_colour=color))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.author_id and interaction.user.id != self.author_id:
            await interaction.response.send_message(
                view=Panel(f"{em('cross')} This panel isn't for you.", color=config.RED), ephemeral=True
            )
            return False
        return True


async def send_ok(ctx, text: str):
    return await ctx.send(view=Panel(f"{em('tick')} {text}", color=config.GREEN), allowed_mentions=NO_MENTIONS)


async def send_err(ctx, text: str):
    return await ctx.send(view=Panel(f"{em('cross')} {text}", color=config.RED), allowed_mentions=NO_MENTIONS)


async def send_panel(ctx, *items, color: int = config.INFO_COLOR):
    return await ctx.send(view=Panel(*items, color=color), allowed_mentions=NO_MENTIONS)


async def i_ok(interaction: discord.Interaction, text: str, ephemeral: bool = True):
    await interaction.response.send_message(
        view=Panel(f"{em('tick')} {text}", color=config.GREEN), ephemeral=ephemeral, allowed_mentions=NO_MENTIONS
    )


async def i_err(interaction: discord.Interaction, text: str):
    await interaction.response.send_message(
        view=Panel(f"{em('cross')} {text}", color=config.RED), ephemeral=True, allowed_mentions=NO_MENTIONS
    )


class Paginated(ui.LayoutView):
    """Numbered list with first/prev/delete/next/last buttons."""

    def __init__(self, author_id: int, title: str, items: list, per_page: int = 10,
                 header: str | None = None, color: int = config.INFO_COLOR, numbered: bool = True):
        super().__init__(timeout=120)
        self.author_id, self.title, self.items = author_id, title, items
        self.per_page, self.header, self.color, self.numbered = per_page, header, color, numbered
        self.page = 0
        self._build()

    def total(self) -> int:
        return max(1, -(-len(self.items) // self.per_page))

    def _build(self):
        self.clear_items()
        s = self.page * self.per_page
        chunk = self.items[s:s + self.per_page]
        body = "\n".join((f"**[{s + i + 1:02d}]** {t}" if self.numbered else str(t)) for i, t in enumerate(chunk))
        b = discord.ButtonStyle
        first = button(None, em("first"), b.secondary, self.go_first)
        prev = button(None, em("prev"), b.secondary, self.go_prev)
        dele = button(None, em("delete"), b.danger, self.go_delete)
        nxt = button(None, em("next"), b.secondary, self.go_next)
        last = button(None, em("last"), b.secondary, self.go_last)
        first.disabled = prev.disabled = self.page == 0
        nxt.disabled = last.disabled = self.page >= self.total() - 1
        head = [ui.TextDisplay(f"### {self.title} [{len(self.items)}]")]
        if self.header:
            head.append(ui.TextDisplay(self.header))
        self.add_item(ui.Container(
            *head, sep(), ui.TextDisplay(body or "*Nothing found.*"), sep(),
            ui.TextDisplay(f"Page `{self.page + 1}/{self.total()}`"),
            ui.ActionRow(first, prev, dele, nxt, last), accent_colour=self.color))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await i_err(interaction, "This list isn't yours.")
            return False
        return True

    async def _go(self, interaction, page):
        self.page = max(0, min(page, self.total() - 1))
        self._build()
        await interaction.response.edit_message(view=self)

    async def go_first(self, i): await self._go(i, 0)
    async def go_prev(self, i): await self._go(i, self.page - 1)
    async def go_next(self, i): await self._go(i, self.page + 1)
    async def go_last(self, i): await self._go(i, self.total() - 1)

    async def go_delete(self, interaction):
        await interaction.response.defer()
        await interaction.delete_original_response()
        self.stop()


async def send_list(ctx, title, items, header=None, per_page=10, color=config.INFO_COLOR, numbered=True):
    return await ctx.send(view=Paginated(ctx.author.id, title, items, per_page, header, color, numbered),
                          allowed_mentions=NO_MENTIONS)


class ConfirmView(ui.LayoutView):
    def __init__(self, author_id: int, text: str, timeout: float = 30):
        super().__init__(timeout=timeout)
        self.author_id, self.value = author_id, None
        yes = button("Yes", None, discord.ButtonStyle.danger, self._yes)
        no = button("No", None, discord.ButtonStyle.secondary, self._no)
        self.add_item(ui.Container(ui.TextDisplay(text), ui.ActionRow(yes, no), accent_colour=config.YELLOW))

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await i_err(interaction, "This isn't for you.")
            return False
        return True

    async def _yes(self, i):
        self.value = True
        await i.response.edit_message(view=Panel(f"{em('tick')} Confirmed.", color=config.GREEN, timeout=None))
        self.stop()

    async def _no(self, i):
        self.value = False
        await i.response.edit_message(view=Panel(f"{em('cross')} Cancelled.", color=config.RED, timeout=None))
        self.stop()


async def confirm(ctx, text: str) -> bool:
    v = ConfirmView(ctx.author.id, f"{em('warn')} {text}")
    msg = await ctx.send(view=v)
    await v.wait()
    if v.value is None:
        try:
            await msg.edit(view=Panel(f"{em('cross')} Timed out.", color=config.RED, timeout=None))
        except discord.HTTPException:
            pass
    return bool(v.value)


class AskModal(ui.Modal):
    """Single-field modal. handler(interaction, text)."""

    def __init__(self, title: str, label: str, handler, default: str = "", paragraph: bool = False,
                 max_length: int = 1000, required: bool = False, placeholder: str | None = None):
        super().__init__(title=title[:45])
        self.handler = handler
        self.field = ui.TextInput(label=label[:45], default=default[:max_length] or None, required=required,
                                  max_length=max_length, placeholder=placeholder,
                                  style=discord.TextStyle.paragraph if paragraph else discord.TextStyle.short)
        self.add_item(self.field)

    async def on_submit(self, interaction: discord.Interaction):
        await self.handler(interaction, str(self.field.value or "").strip())
