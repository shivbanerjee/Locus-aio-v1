import discord
from discord.ext import commands

from utils.checks import guild_perms, bot_guild_perms
from utils.v2 import send_ok, send_err


class Voice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        if not ctx.guild:
            raise commands.NoPrivateMessage()
        return True

    def _vc(self, ctx):
        return ctx.author.voice.channel if ctx.author.voice else None

    async def _all(self, ctx, **kw):
        ch = self._vc(ctx)
        if not ch:
            await send_err(ctx, "Join a voice channel first.")
            return None
        n = 0
        for m in ch.members:
            if m.id != ctx.author.id and not m.bot:
                try:
                    await m.edit(**kw)
                    n += 1
                except discord.HTTPException:
                    pass
        return n

    @commands.command(help="Mute a member in VC")
    @guild_perms(mute_members=True)
    @bot_guild_perms(mute_members=True)
    async def vcmute(self, ctx, member: discord.Member):
        await member.edit(mute=True)
        await send_ok(ctx, f"{member.mention} was muted in voice.")

    @commands.command(help="Unmute a member in VC")
    @guild_perms(mute_members=True)
    @bot_guild_perms(mute_members=True)
    async def vcunmute(self, ctx, member: discord.Member):
        await member.edit(mute=False)
        await send_ok(ctx, f"{member.mention} was unmuted in voice.")

    @commands.command(help="Deafen a member in VC")
    @guild_perms(deafen_members=True)
    @bot_guild_perms(deafen_members=True)
    async def vcdeafen(self, ctx, member: discord.Member):
        await member.edit(deafen=True)
        await send_ok(ctx, f"{member.mention} deafened.")

    @commands.command(help="Undeafen a member in VC")
    @guild_perms(deafen_members=True)
    @bot_guild_perms(deafen_members=True)
    async def vcundeafen(self, ctx, member: discord.Member):
        await member.edit(deafen=False)
        await send_ok(ctx, f"{member.mention} undeafened.")

    @commands.command(help="Disconnect a member from VC")
    @guild_perms(move_members=True)
    @bot_guild_perms(move_members=True)
    async def vckick(self, ctx, member: discord.Member):
        if not member.voice:
            return await send_err(ctx, "That member isn't in a voice channel.")
        await member.move_to(None)
        await send_ok(ctx, f"{member.mention} disconnect.")

    @commands.command(help="Move a member to another VC")
    @guild_perms(move_members=True)
    @bot_guild_perms(move_members=True)
    async def vcmove(self, ctx, member: discord.Member, channel: discord.VoiceChannel):
        if not member.voice:
            return await send_err(ctx, "That member isn't in a voice channel.")
        await member.move_to(channel)
        await send_ok(ctx, f"{member.mention} → {channel.mention}")

    @commands.command(help="Move everyone in your VC to another VC")
    @guild_perms(move_members=True)
    @bot_guild_perms(move_members=True)
    async def vcmoveall(self, ctx, channel: discord.VoiceChannel):
        src = self._vc(ctx)
        if not src:
            return await send_err(ctx, "Join a voice channel first.")
        for m in list(src.members):
            try:
                await m.move_to(channel)
            except discord.HTTPException:
                pass
        await send_ok(ctx, f"Moved everyone to {channel.mention}.")

    @commands.command(help="Mute everyone in your VC")
    @guild_perms(mute_members=True)
    @bot_guild_perms(mute_members=True)
    async def vcmuteall(self, ctx):
        if (n := await self._all(ctx, mute=True)) is not None:
            await send_ok(ctx, f"**{n}** members muted.")

    @commands.command(help="Unmute everyone in your VC")
    @guild_perms(mute_members=True)
    @bot_guild_perms(mute_members=True)
    async def vcunmuteall(self, ctx):
        if (n := await self._all(ctx, mute=False)) is not None:
            await send_ok(ctx, f"**{n}** members unmuted.")


async def setup(bot):
    await bot.add_cog(Voice(bot))
