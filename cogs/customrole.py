import re
import discord
from discord.ext import commands

import config
from utils.v2 import send_ok, send_err

HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")


class CustomRole(commands.Cog):
    """Boosters and Manage Roles members can create a personal role."""

    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        if not ctx.guild:
            raise commands.NoPrivateMessage()
        return True

    def _allowed(self, m: discord.Member) -> bool:
        return m.guild_permissions.manage_roles or m.premium_since is not None

    async def _mine(self, ctx):
        rid = await self.bot.db.val("SELECT role_id FROM customroles WHERE guild_id=? AND user_id=?", ctx.guild.id, ctx.author.id)
        role = ctx.guild.get_role(rid) if rid else None
        if not role:
            await send_err(ctx, f"You don't have a custom role. Use `{ctx.clean_prefix}customrole create <name>`.")
        return role

    @commands.group(name="customrole", aliases=["cr"], invoke_without_command=True, help="Custom role help")
    async def customrole(self, ctx):
        p = ctx.clean_prefix
        await send_ok(ctx, f"`{p}cr create <name>` • `{p}cr rename <name>` • `{p}cr color <#hex>` • `{p}cr delete`")

    @customrole.command(name="create", help="Create your custom role")
    @commands.bot_has_permissions(manage_roles=True)
    async def cr_create(self, ctx, *, name: str):
        if not self._allowed(ctx.author):
            return await send_err(ctx, "Only **Server Boosters** or members with Manage Roles can use this.")
        if await self.bot.db.one("SELECT 1 FROM customroles WHERE guild_id=? AND user_id=?", ctx.guild.id, ctx.author.id):
            return await send_err(ctx, "You already have a custom role.")
        role = await ctx.guild.create_role(name=name[:50], reason=f"Custom role: {ctx.author}")
        try:
            await role.edit(position=max(1, ctx.guild.me.top_role.position - 1))
        except discord.HTTPException:
            pass
        await ctx.author.add_roles(role)
        await self.bot.db.run("INSERT INTO customroles VALUES(?,?,?)", ctx.guild.id, ctx.author.id, role.id)
        await send_ok(ctx, f"Created {role.mention}!")

    @customrole.command(name="rename", help="Rename your role")
    @commands.bot_has_permissions(manage_roles=True)
    async def cr_rename(self, ctx, *, name: str):
        if role := await self._mine(ctx):
            await role.edit(name=name[:50])
            await send_ok(ctx, f"Renamed to **{name[:50]}**")

    @customrole.command(name="color", aliases=["colour"], help="Change your role color (hex)")
    @commands.bot_has_permissions(manage_roles=True)
    async def cr_color(self, ctx, hex_color: str):
        m = HEX.match(hex_color)
        if not m:
            return await send_err(ctx, "Enter a hex colour, e.g. `#ff0000`.")
        if role := await self._mine(ctx):
            await role.edit(colour=discord.Colour(int(m.group(1), 16)))
            await send_ok(ctx, "Colour updated.")

    @customrole.command(name="delete", help="Delete your custom role")
    @commands.bot_has_permissions(manage_roles=True)
    async def cr_delete(self, ctx):
        if role := await self._mine(ctx):
            await role.delete()
            await self.bot.db.run("DELETE FROM customroles WHERE guild_id=? AND user_id=?", ctx.guild.id, ctx.author.id)
            await send_ok(ctx, "Role deleted.")

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        rid = await self.bot.db.val("SELECT role_id FROM customroles WHERE guild_id=? AND user_id=?", member.guild.id, member.id)
        if rid:
            role = member.guild.get_role(rid)
            if role:
                try:
                    await role.delete(reason="Owner left")
                except discord.HTTPException:
                    pass
            await self.bot.db.run("DELETE FROM customroles WHERE guild_id=? AND user_id=?", member.guild.id, member.id)


async def setup(bot):
    await bot.add_cog(CustomRole(bot))
