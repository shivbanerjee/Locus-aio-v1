from discord.ext import commands
from emojis import sync_assets
from utils.v2 import send_ok, send_err, send_panel


class Owner(commands.Cog):
    """Hidden owner-only commands."""

    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        return await self.bot.is_owner(ctx.author)

    @commands.command(name="syncemojis", hidden=True, help="Upload assets/emojis to Application Emojis")
    async def syncemojis(self, ctx):
        done, failed = await sync_assets(self.bot)
        text = f"**Uploaded ({len(done)}):** {', '.join(done) or '—'}"
        if failed:
            text += "\n**Failed:**\n" + "\n".join(failed[:10])
        await send_panel(ctx, "## Emoji Sync", text)

    @commands.command(name="sync", hidden=True, help="Sync slash commands")
    async def sync(self, ctx):
        synced = await self.bot.tree.sync()
        await send_ok(ctx, f"**{len(synced)}** slash commands synced.")

    @commands.command(name="reload", hidden=True, help="Reload a cog")
    async def reload(self, ctx, cog: str):
        try:
            await self.bot.reload_extension(f"cogs.{cog}")
            await send_ok(ctx, f"`{cog}` reloaded.")
        except Exception as ex:
            await send_err(ctx, f"`{ex}`")


async def setup(bot):
    await bot.add_cog(Owner(bot))
