import discord
from discord import ui
from discord.ext import commands

import config
from config import MODULES
from emojis import em
from utils.v2 import Panel, Paginated, sep, footer, button


def module_items(bot, key: str, prefix: str) -> list[str]:
    name = MODULES[key][0]
    cog = bot.get_cog(name.replace(" ", ""))
    cmds = sorted((c for c in cog.walk_commands() if not c.hidden), key=lambda c: c.qualified_name) if cog else []
    return [f"`{prefix}{c.qualified_name}{(' ' + c.signature) if c.signature else ''}` — {c.help or '—'}" for c in cmds]


def module_panel(bot, key: str, prefix: str, author_id: int) -> Paginated:
    name, ekey, _, _ = MODULES[key]
    items = module_items(bot, key, prefix)
    return Paginated(author_id, f"{em(ekey)} {name}", items, per_page=9, numbered=False,
                     header="-# `<>` Required • `[]` Optional", color=config.HELP_COLOR)


class ModuleSelect(ui.Select):
    def __init__(self, core: bool, prefix: str):
        self.prefix = prefix
        super().__init__(
            placeholder="Select a Core Module" if core else "Select an Extra Module",
            options=[
                discord.SelectOption(label=v[0], value=k, description=v[2], emoji=em(v[1]))
                for k, v in MODULES.items() if v[3] == core
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            view=module_panel(interaction.client, self.values[0], self.prefix, interaction.user.id), ephemeral=True
        )


def build_help(bot, author: discord.abc.User, guild) -> Panel:
    prefix = bot.prefix_for(guild)
    total = len([c for c in bot.walk_commands() if not c.hidden])
    core = "\n".join(f"| {em(m[1])} **{m[0]}**" for m in MODULES.values() if m[3])
    extra = "\n".join(f"| {em(m[1])} **{m[0]}**" for m in MODULES.values() if not m[3])
    head = ui.Section(
        ui.TextDisplay(f"### {bot.user.display_name} Help Dashboard"),
        ui.TextDisplay(
            f"{em('arrow')} **Prefix for this server:** `{prefix}`\n"
            f"{em('arrow')} **Total Commands:** `{total}`\n"
            f"{em('arrow')} **Setup:** Type `{prefix}antinuke enable`"
        ),
        accessory=ui.Thumbnail(bot.user.display_avatar.url),
    )
    return Panel(
        head,
        "`<>  - Required Argument | []  - Optional Argument`",
        sep(),
        f"{em('check')} __**Core Modules**__\n{core}",
        f"{em('check')} __**Extra Modules**__\n{extra}",
        sep(),
        f"{em('links')} __**Important Links**__",
        ui.ActionRow(button("Invite Me", url=config.INVITE_URL), button("Support Server", url=config.SUPPORT_URL)),
        ui.ActionRow(ModuleSelect(True, prefix)),
        ui.ActionRow(ModuleSelect(False, prefix)),
        footer(),
        color=config.HELP_COLOR, timeout=300, author_id=author.id,
    )


class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="help", aliases=["h", "commands"], help="Show the help dashboard")
    async def help_cmd(self, ctx, *, module: str = None):
        if module:
            q = module.lower().replace(" ", "")
            for k, v in MODULES.items():
                if q in (k, v[0].lower().replace(" ", "")):
                    return await ctx.send(view=module_panel(self.bot, k, self.bot.prefix_for(ctx.guild), ctx.author.id))
        await ctx.send(view=build_help(self.bot, ctx.author, ctx.guild))


async def setup(bot):
    await bot.add_cog(Help(bot))
