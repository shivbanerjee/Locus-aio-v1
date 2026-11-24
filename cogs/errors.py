import traceback
import discord
from discord.ext import commands
from utils.v2 import send_err


class Errors(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: Exception):
        if hasattr(ctx.command, "on_error"):
            return
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.CommandInvokeError):
            error = error.original

        if isinstance(error, (commands.MissingRequiredArgument, commands.BadArgument,
                              commands.BadUnionArgument, commands.TooManyArguments)):
            usage = f"{ctx.clean_prefix}{ctx.command.qualified_name} {ctx.command.signature}".strip()
            return await send_err(ctx, f"Invalid arguments.\n**Usage:** `{usage}`")
        if isinstance(error, commands.MissingPermissions):
            perms = ", ".join(p.replace("_", " ").title() for p in error.missing_permissions)
            return await send_err(ctx, f"You need this permission: **{perms}**")
        if isinstance(error, commands.BotMissingPermissions):
            perms = ", ".join(p.replace("_", " ").title() for p in error.missing_permissions)
            return await send_err(ctx, f"I need this permission: **{perms}**")
        if isinstance(error, commands.NotOwner):
            return await send_err(ctx, "This command is for the bot owner only.")
        if isinstance(error, commands.CommandOnCooldown):
            return await send_err(ctx, f"This command is on cooldown. Try again in **{error.retry_after:.1f}s**.")
        if isinstance(error, commands.NoPrivateMessage):
            return await send_err(ctx, "This command only works in servers.")
        if isinstance(error, commands.CheckFailure):
            msg = str(error)
            return await send_err(ctx, msg if msg and not msg.startswith("The check functions") else "You can't use this command.")
        if isinstance(error, discord.Forbidden):
            return await send_err(ctx, "I don't have permission, or my role is below the target.")

        traceback.print_exception(type(error), error, error.__traceback__)
        await send_err(ctx, f"Something went wrong: `{type(error).__name__}`")


async def setup(bot):
    await bot.add_cog(Errors(bot))
