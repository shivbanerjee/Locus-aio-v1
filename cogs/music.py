"""Music via Lavalink v4 (lavalink.py >= 5). Set LAVALINK_* in .env."""
import asyncio
import random
import re

import discord
import lavalink
from discord import ui
from discord.ext import commands
from lavalink.errors import ClientError
from lavalink.events import QueueEndEvent, TrackExceptionEvent, TrackStartEvent, TrackStuckEvent

try:
    from lavalink.server import LoadType
except ImportError:  # pragma: no cover
    from lavalink import LoadType

import config
from emojis import em
from utils.v2 import Panel, sep, td, footer, button, send_ok, send_err, send_panel, send_list, i_err

URL_RE = re.compile(r"^https?://", re.I)
B = discord.ButtonStyle


def fmt(ms) -> str:
    if not ms or ms >= 9_000_000_000_000:
        return "LIVE"
    s = int(ms // 1000)
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


class LavalinkVoiceClient(discord.VoiceProtocol):
    """Official lavalink.py voice protocol."""

    def __init__(self, client: discord.Client, channel: discord.abc.Connectable):
        self.client, self.channel = client, channel
        self.guild_id = channel.guild.id
        self._destroyed = False
        self.lavalink = client.lavalink

    async def on_voice_server_update(self, data):
        await self.lavalink.voice_update_handler({"t": "VOICE_SERVER_UPDATE", "d": data})

    async def on_voice_state_update(self, data):
        channel_id = data["channel_id"]
        if not channel_id:
            await self._destroy()
            return
        self.channel = self.client.get_channel(int(channel_id))
        await self.lavalink.voice_update_handler({"t": "VOICE_STATE_UPDATE", "d": data})

    async def connect(self, *, timeout: float, reconnect: bool, self_deaf: bool = False, self_mute: bool = False):
        self.lavalink.player_manager.create(guild_id=self.channel.guild.id)
        await self.channel.guild.change_voice_state(channel=self.channel, self_mute=self_mute, self_deaf=self_deaf)

    async def disconnect(self, *, force: bool = False):
        player = self.lavalink.player_manager.get(self.channel.guild.id)
        if not force and not player.is_connected:
            return
        await self.channel.guild.change_voice_state(channel=None)
        player.channel_id = None
        await self._destroy()

    async def _destroy(self):
        self.cleanup()
        if self._destroyed:
            return
        self._destroyed = True
        try:
            await self.lavalink.player_manager.destroy(self.guild_id)
        except ClientError:
            pass


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.enabled = bool(config.LAVALINK["host"])
        self.idle: dict[int, asyncio.Task] = {}

    async def cog_load(self):
        if not self.enabled:
            print("[!] Music: LAVALINK_HOST is not set, so music commands are disabled.")
            return
        if not hasattr(self.bot, "lavalink"):
            self.bot.lavalink = lavalink.Client(self.bot.user.id)
            L = config.LAVALINK
            self.bot.lavalink.add_node(L["host"], L["port"], L["password"], "us", name=L["name"], ssl=L["ssl"])
        self.lavalink = self.bot.lavalink
        self.lavalink.add_event_hook(self.track_hook)

    async def cog_unload(self):
        if self.enabled and hasattr(self, "lavalink"):
            try:
                self.lavalink.remove_event_hook(self.track_hook)
            except Exception:
                pass

    async def cog_check(self, ctx):
        if not ctx.guild:
            raise commands.NoPrivateMessage()
        return True

    # ---------- helpers ----------
    async def ensure(self, ctx, connect: bool = False):
        if not self.enabled:
            await send_err(ctx, "Music isn't configured (set `LAVALINK_*` in .env).")
            return None
        if not ctx.author.voice or not ctx.author.voice.channel:
            await send_err(ctx, "Join a voice channel first.")
            return None
        player = self.lavalink.player_manager.create(ctx.guild.id)
        vc = ctx.guild.voice_client
        if not vc:
            if not connect:
                await send_err(ctx, "I'm not in a voice channel.")
                return None
            perms = ctx.author.voice.channel.permissions_for(ctx.guild.me)
            if not perms.connect or not perms.speak:
                await send_err(ctx, "I need **Connect** and **Speak** permissions in that voice channel.")
                return None
            player.store("channel", ctx.channel.id)
            await ctx.author.voice.channel.connect(cls=LavalinkVoiceClient, self_deaf=True)
        elif vc.channel.id != ctx.author.voice.channel.id:
            await send_err(ctx, "Join my voice channel first.")
            return None
        player.store("channel", ctx.channel.id)
        self._cancel_idle(ctx.guild.id)
        return player

    def _cancel_idle(self, gid):
        t = self.idle.pop(gid, None)
        if t:
            t.cancel()

    def _start_idle(self, gid, delay):
        self._cancel_idle(gid)
        self.idle[gid] = asyncio.create_task(self._idle(gid, delay))

    async def _idle(self, gid, delay):
        await asyncio.sleep(delay)
        g = self.bot.get_guild(gid)
        p = self.lavalink.player_manager.get(gid)
        if g and g.voice_client and (not p or not p.is_playing):
            if not (await self.bot.db.kget(gid, "247", {})).get("channel"):
                await g.voice_client.disconnect(force=True)

    # ---------- events ----------
    async def track_hook(self, event):
        player = event.player
        if isinstance(event, TrackStartEvent):
            player.store("last", event.track)
            played = player.fetch("played") or []
            played.append(event.track.identifier)
            player.store("played", played[-50:])
            await self.announce(player)
        elif isinstance(event, QueueEndEvent):
            await self.queue_end(player)
        elif isinstance(event, (TrackExceptionEvent, TrackStuckEvent)):
            ch = self.bot.get_channel(player.fetch("channel") or 0)
            if ch:
                await ch.send(view=Panel(f"{em('cross')} Couldn't play this track, skipping it.", color=config.RED, timeout=None), delete_after=8)

    async def queue_end(self, player):
        gid = player.guild_id
        if player.fetch("autoplay"):
            last = player.fetch("last")
            if last:
                queries = [f"https://www.youtube.com/watch?v={last.identifier}&list=RD{last.identifier}", f"ytsearch:{last.author} {last.title}"]
                for q in queries:
                    try:
                        res = await player.node.get_tracks(q)
                    except Exception:
                        continue
                    fresh = [t for t in (res.tracks or []) if t.identifier not in (player.fetch("played") or [])]
                    if fresh:
                        t = random.choice(fresh[:5])
                        player.add(t, requester=self.bot.user.id)
                        await player.play()
                        return
        if not (await self.bot.db.kget(gid, "247", {})).get("channel"):
            self._start_idle(gid, 120)

    # ---------- now playing panel ----------
    def np_panel(self, player) -> Panel:
        t = player.current
        pos, dur = player.position, t.duration
        bar = ""
        if dur and dur < 9_000_000_000_000:
            filled = int(14 * min(pos, dur) / dur)
            bar = "\n`" + "▬" * filled + "🔘" + "▬" * (14 - filled) + f"` {fmt(pos)} / {fmt(dur)}"
        loop = ["off", "track", "queue"][player.loop]
        text = (f"**[{t.title}]({t.uri})**\nby **{t.author}** • `{fmt(dur)}`{bar}\n"
                f"Requested by <@{t.requester}> • Loop `{loop}` • Vol `{player.volume}%` • Queue `{len(player.queue)}`")
        head = ui.Section(td(f"## {em('music')} Now Playing"), td(text), accessory=ui.Thumbnail(t.artwork_url)) if t.artwork_url \
            else td(f"## {em('music')} Now Playing\n{text}")
        row = ui.ActionRow(
            button(None, em("play"), B.primary, self.b_toggle), button(None, em("skip"), B.secondary, self.b_skip),
            button(None, em("stop"), B.danger, self.b_stop), button(None, em("loop"), B.secondary, self.b_loop),
            button(None, em("shuffle"), B.secondary, self.b_shuffle))
        return Panel(head, sep(), row, footer(), color=config.HELP_COLOR, timeout=900)

    async def announce(self, player):
        ch = self.bot.get_channel(player.fetch("channel") or 0)
        if not ch or not player.current:
            return
        old = player.fetch("np")
        if old:
            try:
                await ch.get_partial_message(old).delete()
            except discord.HTTPException:
                pass
        msg = await ch.send(view=self.np_panel(player), allowed_mentions=discord.AllowedMentions.none())
        player.store("np", msg.id)

    async def _btn(self, interaction):
        vc = interaction.guild.voice_client
        player = self.lavalink.player_manager.get(interaction.guild.id) if self.enabled else None
        if not vc or not player or not interaction.user.voice or interaction.user.voice.channel != vc.channel:
            await i_err(interaction, "Join my voice channel first.")
            return None
        return player

    async def b_toggle(self, i):
        if p := await self._btn(i):
            await p.set_pause(not p.paused)
            await i.response.send_message("⏸️ Paused" if p.paused else "▶️ Resumed", ephemeral=True)

    async def b_skip(self, i):
        if p := await self._btn(i):
            await p.skip()
            await i.response.send_message("⏭️ Skipped", ephemeral=True)

    async def b_stop(self, i):
        if p := await self._btn(i):
            p.queue.clear()
            await p.stop()
            await i.response.send_message("⏹️ Stopped", ephemeral=True)

    async def b_loop(self, i):
        if p := await self._btn(i):
            p.set_loop((p.loop + 1) % 3)
            await i.response.send_message(f"🔁 Loop: `{['off', 'track', 'queue'][p.loop]}`", ephemeral=True)

    async def b_shuffle(self, i):
        if p := await self._btn(i):
            p.set_shuffle(not p.shuffle)
            await i.response.send_message(f"🔀 Shuffle: `{'on' if p.shuffle else 'off'}`", ephemeral=True)

    # ---------- 24/7 reconnect + alone detection ----------
    @commands.Cog.listener()
    async def on_ready(self):
        if not self.enabled or getattr(self, "_rejoined", False):
            return
        self._rejoined = True
        await asyncio.sleep(6)
        for g in self.bot.guilds:
            cid = (await self.bot.db.kget(g.id, "247", {})).get("channel")
            ch = g.get_channel(cid) if cid else None
            if ch and not g.voice_client:
                try:
                    await ch.connect(cls=LavalinkVoiceClient, self_deaf=True)
                except Exception as ex:
                    print(f"[!] 24/7 rejoin failed in {g.id}: {ex!r}")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if not self.enabled:
            return
        vc = member.guild.voice_client
        if vc and before.channel == vc.channel and not [m for m in vc.channel.members if not m.bot]:
            self._start_idle(member.guild.id, 60)

    # ---------- commands ----------
    @commands.hybrid_command(name="join", aliases=["j", "connect"], help="Join your voice channel", description="Join your voice channel")
    async def join(self, ctx):
        if await self.ensure(ctx, connect=True):
            await send_ok(ctx, f"Joined **{ctx.author.voice.channel.name}**")

    @commands.hybrid_command(name="play", aliases=["p"], help="Play a song / URL / playlist", description="Play a song, URL or playlist")
    async def play(self, ctx, *, query: str):
        player = await self.ensure(ctx, connect=True)
        if not player:
            return
        await ctx.defer()
        q = query.strip("<>")
        if not URL_RE.match(q):
            q = f"ytsearch:{q}"
        try:
            res = await player.node.get_tracks(q)
        except Exception as ex:
            return await send_err(ctx, f"Search failed: `{str(ex)[:150]}`")
        if not res or not res.tracks:
            return await send_err(ctx, "Nothing found.")
        if res.load_type == LoadType.PLAYLIST:
            for t in res.tracks:
                player.add(t, requester=ctx.author.id)
            msg = f"Playlist **{res.playlist_info.name}** — `{len(res.tracks)}` tracks added."
        else:
            t = res.tracks[0]
            player.add(t, requester=ctx.author.id)
            msg = f"**[{t.title}]({t.uri})** `{fmt(t.duration)}` added."
        if player.is_playing:
            await send_panel(ctx, f"{em('music')} {msg}")
        else:
            await send_panel(ctx, f"{em('music')} {msg}", color=config.GREEN)
            await player.play()

    @commands.hybrid_command(name="skip", aliases=["s", "next"], help="Skip the current song", description="Skip the current song")
    async def skip(self, ctx):
        if p := await self.ensure(ctx):
            await p.skip()
            await send_ok(ctx, "Skipped ⏭️")

    @commands.hybrid_command(name="stop", aliases=["dc", "disconnect", "leave"], help="Stop music and leave the VC", description="Stop music and leave the VC")
    async def stop(self, ctx):
        if p := await self.ensure(ctx):
            p.queue.clear()
            await p.stop()
            await ctx.guild.voice_client.disconnect(force=True)
            await send_ok(ctx, "Stopped & disconnected 👋")

    @commands.hybrid_command(name="pause", help="Pause the music", description="Pause the music")
    async def pause(self, ctx):
        if p := await self.ensure(ctx):
            await p.set_pause(True)
            await send_ok(ctx, "Paused ⏸️")

    @commands.hybrid_command(name="resume", aliases=["unpause"], help="Resume the music", description="Resume the music")
    async def resume(self, ctx):
        if p := await self.ensure(ctx):
            await p.set_pause(False)
            await send_ok(ctx, "Resumed ▶️")

    @commands.hybrid_command(name="volume", aliases=["vol"], help="Set or view the volume (0-150)", description="Set or view the volume")
    async def volume(self, ctx, level: commands.Range[int, 0, 150] = None):
        if p := await self.ensure(ctx):
            if level is None:
                return await send_panel(ctx, f"🔊 Volume: **{p.volume}%**")
            await p.set_volume(level)
            await send_ok(ctx, f"Volume: **{level}%**")

    @commands.hybrid_command(name="loop", aliases=["repeat"], help="Loop: off / track / queue (no arg = toggle track)", description="Set loop mode")
    async def loop(self, ctx, mode: str = None):
        if p := await self.ensure(ctx):
            if mode is None:
                m = 0 if p.loop == 1 else 1
            else:
                m = {"off": 0, "track": 1, "song": 1, "queue": 2, "all": 2}.get(mode.lower())
                if m is None:
                    return await send_err(ctx, "Options: `off`, `track`, `queue`")
            p.set_loop(m)
            await send_ok(ctx, f"Loop: `{['off', 'track', 'queue'][m]}`")

    @commands.hybrid_command(name="shuffle", help="Toggle shuffle", description="Toggle shuffle")
    async def shuffle(self, ctx):
        if p := await self.ensure(ctx):
            p.set_shuffle(not p.shuffle)
            await send_ok(ctx, f"Shuffle: `{'on' if p.shuffle else 'off'}`")

    @commands.hybrid_command(name="queue", aliases=["q"], help="Show the queue", description="Show the queue")
    async def queue(self, ctx):
        if not self.enabled:
            return await send_err(ctx, "Music isn't configured.")
        p = self.lavalink.player_manager.get(ctx.guild.id)
        if not p or (not p.current and not p.queue):
            return await send_err(ctx, "The queue is empty.")
        items = [f"[{t.title[:55]}]({t.uri}) `{fmt(t.duration)}`" for t in p.queue]
        now = f"**Now:** [{p.current.title[:55]}]({p.current.uri})" if p.current else None
        await send_list(ctx, f"{em('music')} Queue", items, header=now, color=config.HELP_COLOR)

    @commands.hybrid_command(name="nowplaying", aliases=["nplay", "nowp"], help="Show the current song", description="Show the current song")
    async def nowplaying(self, ctx):
        if not self.enabled:
            return await send_err(ctx, "Music isn't configured.")
        p = self.lavalink.player_manager.get(ctx.guild.id)
        if not p or not p.current:
            return await send_err(ctx, "Nothing is playing.")
        await ctx.send(view=self.np_panel(p), allowed_mentions=discord.AllowedMentions.none())

    @commands.hybrid_command(name="247", aliases=["24/7", "stay"], help="Toggle 24/7 mode (the bot stays in the VC)", description="Toggle 24/7 mode")
    @commands.has_permissions(manage_guild=True)
    async def twentyfour(self, ctx):
        if not self.enabled:
            return await send_err(ctx, "Music isn't configured.")
        cur = (await self.bot.db.kget(ctx.guild.id, "247", {})).get("channel")
        if cur:
            await self.bot.db.kset(ctx.guild.id, "247", {})
            return await send_ok(ctx, "24/7 mode **off**.")
        if not ctx.author.voice:
            return await send_err(ctx, "Join a voice channel first.")
        if not await self.ensure(ctx, connect=True):
            return
        await self.bot.db.kset(ctx.guild.id, "247", {"channel": ctx.author.voice.channel.id})
        await send_ok(ctx, f"24/7 mode **on** — {ctx.author.voice.channel.mention}")

    @commands.hybrid_command(name="autoplay", aliases=["ap"], help="Toggle autoplay (plays similar songs when the queue ends)", description="Toggle autoplay")
    async def autoplay(self, ctx):
        if p := await self.ensure(ctx):
            p.store("autoplay", not p.fetch("autoplay"))
            await send_ok(ctx, f"Autoplay: `{'on' if p.fetch('autoplay') else 'off'}`")

    @commands.hybrid_command(name="remove", help="Remove a track from the queue by number", description="Remove a queued track")
    async def remove(self, ctx, index: int):
        if p := await self.ensure(ctx):
            if not 1 <= index <= len(p.queue):
                return await send_err(ctx, "Invalid number.")
            t = p.queue.pop(index - 1)
            await send_ok(ctx, f"Removed **{t.title[:60]}**")

    @commands.hybrid_command(name="clearqueue", aliases=["cq"], help="Clear the queue", description="Clear the queue")
    async def clearqueue(self, ctx):
        if p := await self.ensure(ctx):
            p.queue.clear()
            await send_ok(ctx, "Queue cleared.")

    @commands.hybrid_command(name="seek", help="Seek to a time like 1:30", description="Seek to a time like 1:30")
    async def seek(self, ctx, position: str):
        if p := await self.ensure(ctx):
            if not p.current:
                return await send_err(ctx, "Nothing is playing.")
            try:
                parts = [int(x) for x in position.split(":")]
            except ValueError:
                return await send_err(ctx, "Format: `1:30` or `90`")
            sec = sum(v * 60 ** i for i, v in enumerate(reversed(parts)))
            await p.seek(sec * 1000)
            await send_ok(ctx, f"Seek: **{fmt(sec * 1000)}**")


async def setup(bot):
    await bot.add_cog(Music(bot))
