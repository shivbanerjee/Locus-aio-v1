"""No Prefix: plans with expiry, claim panel (7-day free trial), DM + log."""
import time

import discord
from discord import ui
from discord.ext import commands, tasks

import config
from emojis import em
from utils.v2 import Panel, sep, td, footer, button, send_ok, send_err, send_panel, send_list, i_ok, i_err

B = discord.ButtonStyle
PLANS = {"3d": ("3 Days", 3 * 86400), "1w": ("1 Week", 7 * 86400), "1m": ("1 Month", 30 * 86400),
         "3m": ("3 Months", 90 * 86400), "life": ("Lifetime", 0)}
TRIAL = 7 * 86400


def owner_only():
    async def pred(ctx):
        if await ctx.bot.is_owner(ctx.author) or ctx.author.id in config.OWNER_IDS:
            return True
        raise commands.CheckFailure("This command is for the **bot owner** only.")
    return commands.check(pred)


def left(exp: int) -> str:
    if not exp:
        return "Lifetime"
    s = exp - int(time.time())
    if s <= 0:
        return "Expired"
    d, r = divmod(s, 86400)
    h, r = divmod(r, 3600)
    return f"{d}d {h}h {r // 60}m"


class NoPrefix(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sweeper.start()

    async def cog_load(self):
        self.bot.add_view(self.claim_panel())

    def cog_unload(self):
        self.sweeper.cancel()

    # ---------- core ----------
    async def grant(self, uid: int, plan: str, by: int):
        secs = PLANS[plan][1]
        now = int(time.time())
        cur = self.bot.noprefix.get(uid)            # None = none, 0 = lifetime, int = expiry
        if secs == 0 or cur == 0:
            exp = 0
        else:
            exp = (max(now, cur) if cur else now) + secs   # adds on top of an active plan
        await self.bot.db.run("INSERT OR REPLACE INTO np_users VALUES(?,?,?,?)", uid, plan, exp, by)
        self.bot.noprefix[uid] = exp
        return exp

    async def revoke(self, uid: int):
        await self.bot.db.run("DELETE FROM np_users WHERE user_id=?", uid)
        self.bot.noprefix.pop(uid, None)

    async def _log(self, text):
        ch = self.bot.get_channel(config.NP_LOG_CHANNEL) if config.NP_LOG_CHANNEL else None
        if ch:
            try:
                await ch.send(view=Panel(f"### {em('noprefix')} No Prefix", text, color=config.BLURPLE, timeout=None),
                              allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                pass

    @tasks.loop(minutes=1)
    async def sweeper(self):
        now = time.time()
        for uid, exp in list(self.bot.noprefix.items()):
            if exp and exp <= now:
                await self.revoke(uid)
                await self._log(f"<@{uid}>'s plan has **expired**.")
                try:
                    u = await self.bot.fetch_user(uid)
                    await u.send(f"Your **No Prefix** plan has expired. You'll need the prefix `{config.PREFIX}` again.")
                except discord.HTTPException:
                    pass

    @sweeper.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()

    # ---------- claim panel ----------
    def claim_panel(self, title=None) -> ui.LayoutView:
        v = ui.LayoutView(timeout=None)

        async def claim(i: discord.Interaction):
            if await self.bot.db.one("SELECT 1 FROM np_claims WHERE user_id=?", i.user.id):
                return await i_err(i, "You've already claimed the free trial.")
            if self.bot.has_noprefix(i.user.id):
                return await i_err(i, "You already have an active No Prefix plan.")
            await self.bot.db.run("INSERT INTO np_claims VALUES(?,?)", i.user.id, int(time.time()))
            exp = int(time.time()) + TRIAL
            await self.bot.db.run("INSERT OR REPLACE INTO np_users VALUES(?,?,?,?)", i.user.id, "trial", exp, 0)
            self.bot.noprefix[i.user.id] = exp
            await self._log(f"{i.user.mention} claimed the **7-day free trial**.")
            await i_ok(i, "🎉 You got **7 days of No Prefix**! Use commands without a prefix now.")
        v.add_item(ui.Container(td(f"## {em('noprefix')} No Prefix — Free Trial"),
                                td("Press the button to use commands without a prefix for **7 days**. (One claim per user.)"),
                                sep(), ui.ActionRow(button("Claim 7 Days", em("gift"), B.success, claim, "locus:np:claim")),
                                td(footer()), accent_colour=config.HELP_COLOR))
        return v

    # ---------- commands ----------
    @commands.group(name="np", aliases=["noprefix"], invoke_without_command=True, help="No Prefix status / help")
    async def np(self, ctx):
        p = ctx.clean_prefix
        await send_panel(ctx, f"## {em('noprefix')} No Prefix", sep(),
                         f"`{p}np check [@user]` — status\n`{p}np add <@user> [3d|1w|1m|3m|life]` *(owner)*\n`{p}np remove <@user>` *(owner)*\n"
                         f"`{p}np list` *(owner)* • `{p}np setup [#channel]` *(owner)* — claim panel", footer(), color=config.HELP_COLOR)

    @np.command(name="check", aliases=["status"], help="Check no-prefix status")
    async def np_check(self, ctx, user: discord.User = None):
        u = user or ctx.author
        exp = self.bot.noprefix.get(u.id)
        if exp is None or (exp and exp <= time.time()):
            return await send_panel(ctx, f"{em('off')} {u.mention} **doesn't have** No Prefix.")
        await send_panel(ctx, f"{em('on')} {u.mention} — **Active** • Remaining: `{left(exp)}`")

    @np.command(name="add", help="Give no-prefix (plan: 3d, 1w, 1m, 3m, life)")
    @owner_only()
    async def np_add(self, ctx, user: discord.User, plan: str = None):
        if plan:
            plan = plan.lower()
            if plan not in PLANS:
                return await send_err(ctx, "Plans: `3d`, `1w`, `1m`, `3m`, `life`")
            return await self._done(ctx, user, plan)
        sel = ui.Select(placeholder="Choose a plan", options=[discord.SelectOption(label=v[0], value=k) for k, v in PLANS.items()])

        async def cb(i):
            exp = await self.grant(user.id, sel.values[0], ctx.author.id)
            await i.response.edit_message(view=Panel(f"{em('tick')} {user.mention} → **{PLANS[sel.values[0]][0]}** ({left(exp)})",
                                                     color=config.GREEN, timeout=None))
            await self._notify(user, sel.values[0], exp)
        sel.callback = cb
        await ctx.send(view=Panel(f"## {em('noprefix')} Add No Prefix", f"Target: {user.mention}", ui.ActionRow(sel),
                                  timeout=60, author_id=ctx.author.id), allowed_mentions=discord.AllowedMentions.none())

    async def _done(self, ctx, user, plan):
        exp = await self.grant(user.id, plan, ctx.author.id)
        await send_ok(ctx, f"{user.mention} → **{PLANS[plan][0]}** ({left(exp)})")
        await self._notify(user, plan, exp)

    async def _notify(self, user, plan, exp):
        await self._log(f"{user.mention} was given **{PLANS[plan][0]}** (`{left(exp)}`).")
        try:
            await user.send(f"🚀 You received **No Prefix**: **{PLANS[plan][0]}** — use commands without a prefix!")
        except discord.HTTPException:
            pass

    @np.command(name="remove", aliases=["rm"], help="Remove no-prefix from a user")
    @owner_only()
    async def np_remove(self, ctx, user: discord.User):
        if user.id not in self.bot.noprefix:
            return await send_err(ctx, "This user doesn't have No Prefix.")
        await self.revoke(user.id)
        await self._log(f"{user.mention}'s No Prefix was **removed**.")
        await send_ok(ctx, f"Removed No Prefix from {user.mention}.")

    @np.command(name="list", help="List all no-prefix users")
    @owner_only()
    async def np_list(self, ctx):
        rows = await self.bot.db.all("SELECT user_id, plan, expires FROM np_users ORDER BY expires")
        await send_list(ctx, f"{em('noprefix')} No Prefix Users", [f"<@{r['user_id']}> — `{r['plan']}` • `{left(r['expires'])}`" for r in rows], color=config.HELP_COLOR)

    @np.command(name="setup", help="Send the free-trial claim panel")
    @owner_only()
    async def np_setup(self, ctx, channel: discord.TextChannel = None):
        ch = channel or ctx.channel
        await ch.send(view=self.claim_panel())
        await send_ok(ctx, f"Claim panel sent to {ch.mention}.")


async def setup(bot):
    await bot.add_cog(NoPrefix(bot))
